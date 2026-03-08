#!/usr/bin/env python3
import base64
import hashlib
import hmac
import json
import os
import re
import secrets
import threading
from datetime import datetime, timezone
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, quote, urlparse
from urllib.request import Request, urlopen

PROJECT_ROOT = Path(__file__).resolve().parent.parent
WEB_DIR = PROJECT_ROOT / "frontend"
DATA_DIR = PROJECT_ROOT / "data"
ENV_PATH = PROJECT_ROOT / ".env.local"
LEGACY_ENV_PATH = PROJECT_ROOT / ".env"
WEBHOOK_LOG_PATH = DATA_DIR / "hitpay_webhooks.ndjson"
WEBHOOK_FILE_LOCK = threading.Lock()
REF_SANITIZER = re.compile(r"[^A-Za-z0-9._-]")
LOOKUP_SANITIZER = re.compile(r"[^A-Za-z0-9_-]")


def load_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.exists():
        return values

    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue

        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if (
            len(value) >= 2
            and value[0] == value[-1]
            and value[0] in {"'", '"'}
        ):
            value = value[1:-1]
        values[key] = value
    return values


ENV_FILE_VALUES = {
    **load_env_file(LEGACY_ENV_PATH),
    **load_env_file(ENV_PATH),
}


def env_value(name: str, default: str = "") -> str:
    return os.environ.get(name) or ENV_FILE_VALUES.get(name, default)


def parse_port(raw_port: str) -> int:
    try:
        port = int(raw_port)
    except (TypeError, ValueError):
        return 3000
    return port if 1 <= port <= 65535 else 3000


PORT = parse_port(env_value("PORT", "3000"))
HITPAY_ENVIRONMENT = env_value("HITPAY_ENVIRONMENT", "sandbox").strip().lower()
HITPAY_API_BASE_URL = (
    "https://api.hit-pay.com/v1"
    if HITPAY_ENVIRONMENT == "production"
    else "https://api.sandbox.hit-pay.com/v1"
)
SITE_URL = env_value("SITE_URL", f"http://localhost:{PORT}").rstrip("/")
HITPAY_API_KEY = env_value("HITPAY_API_KEY", "").strip()
HITPAY_SALT = env_value("HITPAY_SALT", "").strip()
DEBUG = env_value("DEBUG", "false").strip().lower() == "true"


class ApiError(Exception):
    def __init__(self, status_code: int, message: str, details: Any = None):
        super().__init__(message)
        self.status_code = status_code
        self.message = message
        self.details = details


def iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def parse_amount(raw_amount: Any) -> float:
    try:
        amount = float(raw_amount)
    except (TypeError, ValueError) as exc:
        raise ApiError(400, "Invalid amount. Use a numeric value greater than 0.") from exc

    if amount <= 0:
        raise ApiError(400, "Amount must be greater than 0.")
    return round(amount + 1e-9, 2)


def build_reference_number(raw_reference: Any) -> str:
    candidate = str(raw_reference or "").strip()
    if not candidate:
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
        candidate = f"sp-{timestamp}-{secrets.token_hex(3)}"
    candidate = REF_SANITIZER.sub("-", candidate)
    candidate = re.sub(r"-{2,}", "-", candidate).strip("-")
    if not candidate:
        candidate = f"sp-{secrets.token_hex(4)}"
    return candidate[:80]


def sanitize_lookup_id(raw_value: str) -> str:
    value = LOOKUP_SANITIZER.sub("", str(raw_value or "").strip())
    if not value:
        raise ApiError(400, "payment_request_id is required.")
    return value[:120]


def first_query_value(params: dict[str, list[str]], keys: list[str]) -> str:
    for key in keys:
        values = params.get(key, [])
        if values and values[0]:
            return values[0]
    return ""


def hitpay_api_request(
    method: str,
    path: str,
    payload: dict[str, Any] | None = None,
) -> tuple[int, dict[str, Any]]:
    if not HITPAY_API_KEY:
        raise ApiError(500, "HITPAY_API_KEY is not set.")

    url = f"{HITPAY_API_BASE_URL}{path}"
    headers = {
        "X-BUSINESS-API-KEY": HITPAY_API_KEY,
        "Accept": "application/json",
        "User-Agent": "MosqueTech-HitPay-Server/1.0",
    }
    data = None
    if payload is not None:
        headers["Content-Type"] = "application/json"
        data = json.dumps(payload).encode("utf-8")

    request = Request(url=url, data=data, headers=headers, method=method.upper())
    try:
        with urlopen(request, timeout=30) as response:
            raw_response = response.read().decode("utf-8")
            parsed = json.loads(raw_response) if raw_response else {}
            if not isinstance(parsed, dict):
                parsed = {"data": parsed}
            return int(response.status), parsed
    except HTTPError as error:
        raw_error = error.read().decode("utf-8", "replace")
        details: Any = None
        message = f"HitPay API request failed ({error.code})."
        if raw_error:
            try:
                details = json.loads(raw_error)
                if isinstance(details, dict):
                    message = str(details.get("message") or details.get("error") or message)
                else:
                    details = {"response": details}
            except json.JSONDecodeError:
                details = {"response": raw_error}
        raise ApiError(int(error.code), message, details) from error
    except URLError as error:
        raise ApiError(502, f"Unable to reach HitPay API: {error.reason}") from error


def verify_webhook_signature(raw_body: bytes, signature: str) -> bool:
    if not HITPAY_SALT:
        raise ApiError(500, "HITPAY_SALT is not set.")
    if not signature:
        return False
    expected_hex = hmac.new(
        HITPAY_SALT.encode("utf-8"),
        raw_body,
        hashlib.sha256,
    ).hexdigest().lower()

    # HitPay normally sends a hex signature, but some proxies/tools prepend formats
    # like "sha256=<hex>" or comma-separated "v1=<sig>" style tokens.
    raw_signature = str(signature or "").strip()
    if not raw_signature:
        return False

    candidates: list[str] = [raw_signature]
    for token in re.split(r"[\s,]+", raw_signature):
        tok = token.strip()
        if not tok:
            continue
        if "=" in tok:
            _, value = tok.split("=", 1)
            if value:
                candidates.append(value.strip())
        candidates.append(tok)

    seen: set[str] = set()
    unique_candidates: list[str] = []
    for item in candidates:
        if item in seen:
            continue
        seen.add(item)
        unique_candidates.append(item)

    for candidate in unique_candidates:
        token = candidate.strip()
        if not token:
            continue

        if re.fullmatch(r"[A-Fa-f0-9]{64}", token):
            if hmac.compare_digest(expected_hex, token.lower()):
                return True
            continue

        # Fallback: accept base64-encoded 32-byte digest if present.
        try:
            padded = token + ("=" * ((4 - (len(token) % 4)) % 4))
            decoded = base64.b64decode(padded, validate=True)
        except Exception:
            continue
        if len(decoded) == 32 and hmac.compare_digest(expected_hex, decoded.hex().lower()):
            return True

    return False


def append_webhook_event(payload: dict[str, Any]) -> None:
    event = {
        "receivedAt": iso_now(),
        "payload": payload,
    }
    WEBHOOK_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with WEBHOOK_FILE_LOCK:
        with WEBHOOK_LOG_PATH.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(event, ensure_ascii=True) + "\n")


def default_user_file() -> str:
    return "skim-pintar4.html" if (WEB_DIR / "skim-pintar4.html").exists() else "index.html"


class HitPayHandler(SimpleHTTPRequestHandler):
    server_version = "HitPayHTTP/1.0"

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, directory=str(WEB_DIR), **kwargs)

    def send_json(self, status_code: int, payload: dict[str, Any]) -> None:
        raw = json.dumps(payload, ensure_ascii=True).encode("utf-8")
        self.send_response(status_code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(raw)

    def read_request_body(self) -> bytes:
        length_header = self.headers.get("Content-Length", "0").strip()
        try:
            content_length = int(length_header)
        except ValueError:
            raise ApiError(400, "Invalid Content-Length header.")
        if content_length < 0:
            raise ApiError(400, "Invalid request body length.")
        return self.rfile.read(content_length) if content_length else b""

    def parse_json_body(self, raw_body: bytes) -> dict[str, Any]:
        if not raw_body:
            return {}
        try:
            parsed = json.loads(raw_body.decode("utf-8"))
        except json.JSONDecodeError as error:
            raise ApiError(400, "Request body must be valid JSON.") from error
        if not isinstance(parsed, dict):
            raise ApiError(400, "JSON body must be an object.")
        return parsed

    def do_OPTIONS(self) -> None:
        self.send_response(HTTPStatus.NO_CONTENT)
        self.send_header("Allow", "GET, POST, OPTIONS")
        self.end_headers()

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/":
            default_file = default_user_file()
            self.path = f"/{default_file}"
            super().do_GET()
            return
        if parsed.path in {"/user", "/user/"}:
            user_file = default_user_file()
            self.path = f"/{user_file}"
            super().do_GET()
            return
        if parsed.path in {"/admin", "/admin/"} and (WEB_DIR / "skim-pintar4-admin.html").exists():
            self.path = "/skim-pintar4-admin.html"
            super().do_GET()
            return

        if parsed.path == "/api/health":
            self.send_json(
                HTTPStatus.OK,
                {
                    "ok": True,
                    "time": iso_now(),
                    "hitpayEnvironment": HITPAY_ENVIRONMENT,
                    "configured": bool(HITPAY_API_KEY),
                },
            )
            return

        if parsed.path == "/api/hitpay/payment-status":
            self.handle_payment_status(parsed.query)
            return

        super().do_GET()

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/api/hitpay/create-payment":
            self.handle_create_payment()
            return
        if parsed.path == "/api/hitpay/webhook":
            self.handle_webhook()
            return

        self.send_json(HTTPStatus.NOT_FOUND, {"ok": False, "error": "Endpoint not found."})

    def handle_create_payment(self) -> None:
        try:
            payload = self.parse_json_body(self.read_request_body())
            amount = parse_amount(payload.get("amount"))
            currency = str(payload.get("currency") or "SGD").strip().upper()
            if not re.fullmatch(r"[A-Z]{3}", currency):
                raise ApiError(400, "currency must be a 3-letter code, for example SGD.")

            reference_number = build_reference_number(
                payload.get("reference_number") or payload.get("reference")
            )
            redirect_url = str(
                payload.get("redirect_url") or f"{SITE_URL}/skim-pintar4.html"
            ).strip()
            purpose = str(
                payload.get("purpose") or "Skim Pintar Monthly Contribution"
            ).strip()[:200]
            name = str(payload.get("name") or "").strip()[:100]
            email = str(payload.get("email") or "").strip()[:160]
            phone = str(payload.get("phone") or "").strip()[:40]

            hitpay_payload: dict[str, Any] = {
                "amount": f"{amount:.2f}",
                "currency": currency,
                "purpose": purpose,
                "reference_number": reference_number,
                "redirect_url": redirect_url,
            }
            if name:
                hitpay_payload["name"] = name
            if email:
                hitpay_payload["email"] = email
            if phone:
                hitpay_payload["phone"] = phone

            _, hitpay_response = hitpay_api_request("POST", "/payment-requests", hitpay_payload)
            self.send_json(
                HTTPStatus.OK,
                {
                    "ok": True,
                    "paymentRequestId": hitpay_response.get("id"),
                    "checkoutUrl": hitpay_response.get("url"),
                    "status": hitpay_response.get("status"),
                    "referenceNumber": hitpay_response.get("reference_number") or reference_number,
                },
            )
        except ApiError as error:
            response: dict[str, Any] = {"ok": False, "error": error.message}
            if error.details is not None:
                response["details"] = error.details
            self.send_json(error.status_code, response)

    def handle_payment_status(self, query_string: str) -> None:
        try:
            query_params = parse_qs(query_string)
            raw_id = first_query_value(query_params, ["payment_request_id", "reference", "id"])
            payment_request_id = sanitize_lookup_id(raw_id)
            _, hitpay_response = hitpay_api_request(
                "GET",
                f"/payment-requests/{quote(payment_request_id)}",
            )

            payload: dict[str, Any] = {
                "ok": True,
                "paymentRequestId": hitpay_response.get("id"),
                "status": hitpay_response.get("status"),
                "amount": hitpay_response.get("amount"),
                "currency": hitpay_response.get("currency"),
                "referenceNumber": hitpay_response.get("reference_number"),
                "purpose": hitpay_response.get("purpose"),
                "paymentMethods": hitpay_response.get("payment_methods"),
            }
            if DEBUG:
                payload["raw"] = hitpay_response
            self.send_json(HTTPStatus.OK, payload)
        except ApiError as error:
            response: dict[str, Any] = {"ok": False, "error": error.message}
            if error.details is not None:
                response["details"] = error.details
            self.send_json(error.status_code, response)

    def handle_webhook(self) -> None:
        try:
            raw_body = self.read_request_body()
            signature = (
                self.headers.get("Hitpay-Signature")
                or self.headers.get("X-Hitpay-Signature")
                or ""
            ).strip()
            if not verify_webhook_signature(raw_body, signature):
                raise ApiError(
                    HTTPStatus.UNAUTHORIZED,
                    "Invalid webhook signature. Check HITPAY_SALT and sandbox/production environment match."
                )

            payload = self.parse_json_body(raw_body)
            append_webhook_event(payload)
            self.send_json(HTTPStatus.OK, {"ok": True})
        except ApiError as error:
            response: dict[str, Any] = {"ok": False, "error": error.message}
            if error.details is not None:
                response["details"] = error.details
            self.send_json(error.status_code, response)


def main() -> None:
    default_file = default_user_file()
    print(f"Serving {default_file} from: {WEB_DIR}")
    print(f"Listening on: http://localhost:{PORT}")
    print(f"HitPay environment: {HITPAY_ENVIRONMENT}")
    if not HITPAY_API_KEY:
        print("WARNING: HITPAY_API_KEY is missing. /api/hitpay/create-payment will fail.")
    if not HITPAY_SALT:
        print("WARNING: HITPAY_SALT is missing. Webhook verification will fail.")

    server = ThreadingHTTPServer(("0.0.0.0", PORT), HitPayHandler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down...")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()

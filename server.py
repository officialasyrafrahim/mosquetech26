from __future__ import annotations

import argparse
import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

DB_PATH = Path(__file__).with_name("skim_pintar.db")
DEFAULT_SEED_VERSION = "2026-03-08-v1"

app = FastAPI(title="Skim Pintar API", version="1.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@contextmanager
def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db(seed_defaults_on_create: bool = True) -> dict[str, Any]:
    db_preexisting = DB_PATH.exists()
    seed_result: dict[str, Any] | None = None
    with get_conn() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS users (
              id TEXT PRIMARY KEY,
              provider TEXT,
              singpass_sub TEXT,
              full_name TEXT,
              mobile TEXT,
              email TEXT,
              nric TEXT,
              notify_channel TEXT,
              address TEXT,
              password_hash TEXT,
              created_at TEXT,
              updated_at TEXT,
              singpass_profile_json TEXT
            );

            CREATE TABLE IF NOT EXISTS donor_submissions (
              application_id TEXT PRIMARY KEY,
              submitted_at TEXT,
              updated_at TEXT,
              donor_full_name TEXT,
              donor_nric TEXT,
              donor_nric_normalized TEXT,
              donor_mobile TEXT,
              donor_email TEXT,
              donor_address TEXT,
              donor_contribution REAL,
              donor_group_name TEXT,
              notify_channel TEXT,
              payment_method TEXT,
              hitpay_charge_mode TEXT,
              hitpay_recurring_email TEXT,
              egiro_bank TEXT,
              egiro_account TEXT,
              egiro_account_holder TEXT,
              egiro_deduction_day TEXT,
              egiro_start_month TEXT,
              auth_user_id TEXT,
              auth_user_email TEXT,
              auth_provider TEXT,
              terminated_at TEXT,
              terminated_reason TEXT,
              terminated_notes TEXT,
              terminated_by_user_id TEXT,
              terminated_by_admin INTEGER DEFAULT 0
            );

            CREATE TABLE IF NOT EXISTS submission_relatives (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              application_id TEXT NOT NULL,
              full_name TEXT,
              date_of_birth TEXT,
              relationship TEXT,
              address_type TEXT,
              address TEXT,
              FOREIGN KEY(application_id) REFERENCES donor_submissions(application_id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS member_directory (
              member_record_id TEXT PRIMARY KEY,
              user_id TEXT,
              full_name TEXT,
              mobile TEXT,
              email TEXT,
              provider TEXT,
              nric TEXT,
              first_registered_at TEXT,
              last_seen_at TEXT,
              last_auth_action TEXT
            );

            CREATE TABLE IF NOT EXISTS auth_events (
              event_id TEXT PRIMARY KEY,
              event_type TEXT,
              method TEXT,
              timestamp TEXT,
              user_id TEXT,
              full_name TEXT,
              email TEXT,
              provider TEXT,
              application_id TEXT,
              reason TEXT
            );

            CREATE TABLE IF NOT EXISTS app_meta (
              key TEXT PRIMARY KEY,
              value TEXT
            );
            """
        )
        ensure_column(conn, "donor_submissions", "updated_at TEXT")
        ensure_column(conn, "donor_submissions", "donor_nric_normalized TEXT")
        ensure_column(conn, "donor_submissions", "payment_method TEXT")
        ensure_column(conn, "donor_submissions", "notify_channel TEXT")
        ensure_column(conn, "donor_submissions", "hitpay_charge_mode TEXT")
        ensure_column(conn, "donor_submissions", "hitpay_recurring_email TEXT")
        ensure_column(conn, "donor_submissions", "auth_user_id TEXT")
        ensure_column(conn, "donor_submissions", "terminated_at TEXT")
        ensure_column(conn, "donor_submissions", "terminated_reason TEXT")
        ensure_column(conn, "donor_submissions", "terminated_notes TEXT")
        ensure_column(conn, "donor_submissions", "terminated_by_user_id TEXT")
        ensure_column(conn, "donor_submissions", "terminated_by_admin INTEGER DEFAULT 0")
        ensure_column(conn, "auth_events", "application_id TEXT")
        ensure_column(conn, "auth_events", "reason TEXT")
        ensure_column(conn, "users", "notify_channel TEXT")
        conn.execute("INSERT OR IGNORE INTO app_meta(key, value) VALUES('donor_counter', '1248')")
        if seed_defaults_on_create and not db_preexisting:
            seed_result = seed_default_data(conn, force=False)
    return {
        "created": not db_preexisting,
        "seededDefaults": bool(seed_result and seed_result.get("seeded")),
    }


def ensure_column(conn: sqlite3.Connection, table_name: str, column_def: str) -> None:
    column_name = column_def.split()[0].strip()
    existing = {
        row["name"]
        for row in conn.execute(f"PRAGMA table_info({table_name})").fetchall()
    }
    if column_name in existing:
        return
    conn.execute(f"ALTER TABLE {table_name} ADD COLUMN {column_def}")


def iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def normalize_nric(value: Any) -> str:
    return "".join(ch for ch in str(value or "").upper() if ch.isalnum())


def has_app_data(conn: sqlite3.Connection) -> bool:
    tables = ("users", "donor_submissions", "submission_relatives", "member_directory", "auth_events")
    for table_name in tables:
        row = conn.execute(f"SELECT 1 FROM {table_name} LIMIT 1").fetchone()
        if row is not None:
            return True
    return False


def build_default_seed_payload() -> dict[str, list[dict[str, Any]]]:
    users = [
        {
            "id": "usr_mock_basic_active",
            "provider": "local",
            "singpass_sub": "",
            "full_name": "Ahmad Bin Yusof",
            "mobile": "91234567",
            "email": "ahmad.yusof.mock01@skim-pintar.mock",
            "nric": "S9123456D",
            "notify_channel": "sms",
            "address": "Blk 101 Bukit Batok West Ave 6, #08-112, Singapore 650101",
            "password_hash": "5a69293f87f9fbc55bc7b797501c60d9d3bfae33c4ba322dc24bd215694668c1",
            "created_at": "2026-01-15T03:00:00+00:00",
            "updated_at": "2026-01-15T03:00:00+00:00",
            "singpass_profile_json": None,
        },
        {
            "id": "usr_mock_plus_active",
            "provider": "local",
            "singpass_sub": "",
            "full_name": "Nur Ain Bte Salleh",
            "mobile": "92345678",
            "email": "nurain.salleh.mock02@skim-pintar.mock",
            "nric": "T0345678H",
            "notify_channel": "whatsapp",
            "address": "Blk 210 Choa Chu Kang Ave 3, #05-88, Singapore 680210",
            "password_hash": "27fa93310da5de729b3dd254cd72f482f19034adb0d4858ea48aff350bbe0a90",
            "created_at": "2026-01-10T03:00:00+00:00",
            "updated_at": "2026-01-10T03:00:00+00:00",
            "singpass_profile_json": None,
        },
        {
            "id": "usr_mock_plus_ended",
            "provider": "local",
            "singpass_sub": "",
            "full_name": "Hafiz Bin Karim",
            "mobile": "93456789",
            "email": "hafiz.karim.mock03@skim-pintar.mock",
            "nric": "S7654321F",
            "notify_channel": "email",
            "address": "Blk 332 Jurong East St 31, #10-201, Singapore 600332",
            "password_hash": "a2d0b6b1dd5a851e81a25049952d980094fd553dd68ed0cc3e769780a142097d",
            "created_at": "2025-11-20T03:00:00+00:00",
            "updated_at": "2025-11-20T03:00:00+00:00",
            "singpass_profile_json": None,
        },
        {
            "id": "usr_mock_processing",
            "provider": "local",
            "singpass_sub": "",
            "full_name": "Siti Mariam Bte Osman",
            "mobile": "94567890",
            "email": "siti.mariam.mock04@skim-pintar.mock",
            "nric": "T1122334B",
            "notify_channel": "whatsapp",
            "address": "Blk 55 Tampines Street 11, #04-99, Singapore 521055",
            "password_hash": "c0ef10f76b7699a1a33593e1ee3547b64a6b71e02f9305c129d43f6c86b0efcb",
            "created_at": "2026-03-04T03:00:00+00:00",
            "updated_at": "2026-03-04T03:00:00+00:00",
            "singpass_profile_json": None,
        },
        {
            "id": "usr_mock_new",
            "provider": "local",
            "singpass_sub": "",
            "full_name": "Farid Bin Ismail",
            "mobile": "95678901",
            "email": "farid.ismail.mock05@skim-pintar.mock",
            "nric": "S5566778J",
            "notify_channel": "sms",
            "address": "Blk 88 Serangoon North Ave 1, #03-25, Singapore 550088",
            "password_hash": "4d94db32d34827ce233f357d07efd1a6df15a1780287b2c122eb1e3d4b788359",
            "created_at": "2026-03-06T03:00:00+00:00",
            "updated_at": "2026-03-06T03:00:00+00:00",
            "singpass_profile_json": None,
        },
    ]

    donor_submissions = [
        {
            "application_id": "SP-MOCK-2001",
            "submitted_at": "2026-01-28T00:00:00+00:00",
            "updated_at": "2026-01-28T00:00:00+00:00",
            "donor_full_name": "Ahmad Bin Yusof",
            "donor_nric": "S9123456D",
            "donor_mobile": "91234567",
            "donor_email": "ahmad.yusof.mock01@skim-pintar.mock",
            "donor_address": "Blk 101 Bukit Batok West Ave 6, #08-112, Singapore 650101",
            "donor_contribution": 8.0,
            "donor_group_name": "Skim Pintar Basic",
            "notify_channel": "sms",
            "payment_method": "egiro",
            "hitpay_charge_mode": "",
            "hitpay_recurring_email": "",
            "egiro_bank": "DBS/POSB",
            "egiro_account": "1234567890",
            "egiro_account_holder": "Ahmad Bin Yusof",
            "egiro_deduction_day": "1",
            "egiro_start_month": "2025-07",
            "auth_user_id": "usr_mock_basic_active",
            "auth_user_email": "ahmad.yusof.mock01@skim-pintar.mock",
            "auth_provider": "local",
            "terminated_at": "",
            "terminated_reason": "",
            "terminated_notes": "",
            "terminated_by_user_id": "",
            "terminated_by_admin": 0,
        },
        {
            "application_id": "SP-MOCK-2002",
            "submitted_at": "2025-12-31T00:00:00+00:00",
            "updated_at": "2025-12-31T00:00:00+00:00",
            "donor_full_name": "Nur Ain Bte Salleh",
            "donor_nric": "T0345678H",
            "donor_mobile": "92345678",
            "donor_email": "nurain.salleh.mock02@skim-pintar.mock",
            "donor_address": "Blk 210 Choa Chu Kang Ave 3, #05-88, Singapore 680210",
            "donor_contribution": 25.0,
            "donor_group_name": "Skim Pintar Plus",
            "notify_channel": "whatsapp",
            "payment_method": "egiro",
            "hitpay_charge_mode": "",
            "hitpay_recurring_email": "",
            "egiro_bank": "OCBC",
            "egiro_account": "2345678901",
            "egiro_account_holder": "Nur Ain Bte Salleh",
            "egiro_deduction_day": "5",
            "egiro_start_month": "2025-05",
            "auth_user_id": "usr_mock_plus_active",
            "auth_user_email": "nurain.salleh.mock02@skim-pintar.mock",
            "auth_provider": "local",
            "terminated_at": "",
            "terminated_reason": "",
            "terminated_notes": "",
            "terminated_by_user_id": "",
            "terminated_by_admin": 0,
        },
        {
            "application_id": "SP-MOCK-2003",
            "submitted_at": "2025-11-06T00:00:00+00:00",
            "updated_at": "2026-02-24T00:00:00+00:00",
            "donor_full_name": "Hafiz Bin Karim",
            "donor_nric": "S7654321F",
            "donor_mobile": "93456789",
            "donor_email": "hafiz.karim.mock03@skim-pintar.mock",
            "donor_address": "Blk 332 Jurong East St 31, #10-201, Singapore 600332",
            "donor_contribution": 30.0,
            "donor_group_name": "Skim Pintar Plus",
            "notify_channel": "email",
            "payment_method": "egiro",
            "hitpay_charge_mode": "",
            "hitpay_recurring_email": "",
            "egiro_bank": "UOB",
            "egiro_account": "3456789012",
            "egiro_account_holder": "Hafiz Bin Karim",
            "egiro_deduction_day": "10",
            "egiro_start_month": "2024-12",
            "auth_user_id": "usr_mock_plus_ended",
            "auth_user_email": "hafiz.karim.mock03@skim-pintar.mock",
            "auth_provider": "local",
            "terminated_at": "2026-02-24T00:00:00+00:00",
            "terminated_reason": "Moving to another arrangement",
            "terminated_notes": "Mock test record",
            "terminated_by_user_id": "usr_mock_plus_ended",
            "terminated_by_admin": 0,
        },
        {
            "application_id": "SP-MOCK-2004",
            "submitted_at": "2026-03-05T00:00:00+00:00",
            "updated_at": "2026-03-05T00:00:00+00:00",
            "donor_full_name": "Siti Mariam Bte Osman",
            "donor_nric": "T1122334B",
            "donor_mobile": "94567890",
            "donor_email": "siti.mariam.mock04@skim-pintar.mock",
            "donor_address": "Blk 55 Tampines Street 11, #04-99, Singapore 521055",
            "donor_contribution": 6.5,
            "donor_group_name": "Skim Pintar Basic",
            "notify_channel": "whatsapp",
            "payment_method": "egiro",
            "hitpay_charge_mode": "",
            "hitpay_recurring_email": "",
            "egiro_bank": "Maybank",
            "egiro_account": "4567890123",
            "egiro_account_holder": "Siti Mariam Bte Osman",
            "egiro_deduction_day": "1",
            "egiro_start_month": "2026-03",
            "auth_user_id": "usr_mock_processing",
            "auth_user_email": "siti.mariam.mock04@skim-pintar.mock",
            "auth_provider": "local",
            "terminated_at": "",
            "terminated_reason": "",
            "terminated_notes": "",
            "terminated_by_user_id": "",
            "terminated_by_admin": 0,
        },
    ]

    submission_relatives = [
        {
            "application_id": "SP-MOCK-2002",
            "full_name": "Salleh Bin Rahman",
            "date_of_birth": "1985-02-15",
            "relationship": "Husband",
            "address_type": "same-address",
            "address": "",
        },
        {
            "application_id": "SP-MOCK-2002",
            "full_name": "Aisha Bte Salleh",
            "date_of_birth": "2012-09-03",
            "relationship": "Daughter",
            "address_type": "same-address",
            "address": "",
        },
        {
            "application_id": "SP-MOCK-2002",
            "full_name": "Ramlah Bte Osman",
            "date_of_birth": "",
            "relationship": "Mother",
            "address_type": "different-address",
            "address": "Blk 318 Woodlands Street 31, #02-54, Singapore 730318",
        },
        {
            "application_id": "SP-MOCK-2003",
            "full_name": "Nurul Bte Hafiz",
            "date_of_birth": "2010-07-20",
            "relationship": "Daughter",
            "address_type": "same-address",
            "address": "",
        },
    ]

    member_directory = [
        {
            "member_record_id": "mem_usr_mock_basic_active",
            "user_id": "usr_mock_basic_active",
            "full_name": "Ahmad Bin Yusof",
            "mobile": "91234567",
            "email": "ahmad.yusof.mock01@skim-pintar.mock",
            "provider": "local",
            "nric": "S9123456D",
            "first_registered_at": "2026-01-15T03:00:00+00:00",
            "last_seen_at": "2026-03-07T10:00:00+00:00",
            "last_auth_action": "login",
        },
        {
            "member_record_id": "mem_usr_mock_plus_active",
            "user_id": "usr_mock_plus_active",
            "full_name": "Nur Ain Bte Salleh",
            "mobile": "92345678",
            "email": "nurain.salleh.mock02@skim-pintar.mock",
            "provider": "local",
            "nric": "T0345678H",
            "first_registered_at": "2026-01-10T03:00:00+00:00",
            "last_seen_at": "2026-03-07T11:00:00+00:00",
            "last_auth_action": "login",
        },
        {
            "member_record_id": "mem_usr_mock_plus_ended",
            "user_id": "usr_mock_plus_ended",
            "full_name": "Hafiz Bin Karim",
            "mobile": "93456789",
            "email": "hafiz.karim.mock03@skim-pintar.mock",
            "provider": "local",
            "nric": "S7654321F",
            "first_registered_at": "2025-11-20T03:00:00+00:00",
            "last_seen_at": "2026-02-24T00:00:00+00:00",
            "last_auth_action": "login",
        },
        {
            "member_record_id": "mem_usr_mock_processing",
            "user_id": "usr_mock_processing",
            "full_name": "Siti Mariam Bte Osman",
            "mobile": "94567890",
            "email": "siti.mariam.mock04@skim-pintar.mock",
            "provider": "local",
            "nric": "T1122334B",
            "first_registered_at": "2026-03-04T03:00:00+00:00",
            "last_seen_at": "2026-03-07T12:00:00+00:00",
            "last_auth_action": "register",
        },
        {
            "member_record_id": "mem_usr_mock_new",
            "user_id": "usr_mock_new",
            "full_name": "Farid Bin Ismail",
            "mobile": "95678901",
            "email": "farid.ismail.mock05@skim-pintar.mock",
            "provider": "local",
            "nric": "S5566778J",
            "first_registered_at": "2026-03-06T03:00:00+00:00",
            "last_seen_at": "2026-03-06T03:00:00+00:00",
            "last_auth_action": "register",
        },
    ]

    auth_events = [
        {
            "event_id": "evt_mock_seed_20260308",
            "event_type": "mock_seed",
            "method": DEFAULT_SEED_VERSION,
            "timestamp": "2026-03-08T00:00:00+00:00",
            "user_id": "system",
            "full_name": "Mock Seeder",
            "email": "system@local",
            "provider": "system",
            "application_id": "",
            "reason": "",
        }
    ]

    return {
        "users": users,
        "donor_submissions": donor_submissions,
        "submission_relatives": submission_relatives,
        "member_directory": member_directory,
        "auth_events": auth_events,
    }


def seed_default_data(conn: sqlite3.Connection, *, force: bool = False) -> dict[str, Any]:
    if not force and has_app_data(conn):
        return {"seeded": False, "reason": "existing_data"}

    if force:
        conn.execute("DELETE FROM submission_relatives")
        conn.execute("DELETE FROM donor_submissions")
        conn.execute("DELETE FROM member_directory")
        conn.execute("DELETE FROM auth_events")
        conn.execute("DELETE FROM users")

    payload = build_default_seed_payload()

    for row in payload["users"]:
        conn.execute(
            """
            INSERT OR REPLACE INTO users(
              id, provider, singpass_sub, full_name, mobile, email, nric, notify_channel, address, password_hash, created_at, updated_at, singpass_profile_json
            )
            VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                row["id"],
                row["provider"],
                row["singpass_sub"],
                row["full_name"],
                row["mobile"],
                row["email"],
                row["nric"],
                row.get("notify_channel", ""),
                row["address"],
                row["password_hash"],
                row["created_at"],
                row["updated_at"],
                row["singpass_profile_json"],
            ),
        )

    for row in payload["donor_submissions"]:
        conn.execute(
            """
            INSERT OR REPLACE INTO donor_submissions(
              application_id, submitted_at, updated_at, donor_full_name, donor_nric, donor_nric_normalized, donor_mobile, donor_email, donor_address, donor_contribution,
              donor_group_name, notify_channel, payment_method, hitpay_charge_mode, hitpay_recurring_email, egiro_bank, egiro_account, egiro_account_holder, egiro_deduction_day, egiro_start_month,
              auth_user_id, auth_user_email, auth_provider, terminated_at, terminated_reason, terminated_notes, terminated_by_user_id, terminated_by_admin
            )
            VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                row["application_id"],
                row["submitted_at"],
                row["updated_at"],
                row["donor_full_name"],
                row["donor_nric"],
                normalize_nric(row["donor_nric"]),
                row["donor_mobile"],
                row["donor_email"],
                row["donor_address"],
                row["donor_contribution"],
                row["donor_group_name"],
                row.get("notify_channel", ""),
                row["payment_method"],
                row["hitpay_charge_mode"],
                row["hitpay_recurring_email"],
                row["egiro_bank"],
                row["egiro_account"],
                row["egiro_account_holder"],
                row["egiro_deduction_day"],
                row["egiro_start_month"],
                row["auth_user_id"],
                row["auth_user_email"],
                row["auth_provider"],
                row["terminated_at"],
                row["terminated_reason"],
                row["terminated_notes"],
                row["terminated_by_user_id"],
                row["terminated_by_admin"],
            ),
        )

    conn.execute("DELETE FROM submission_relatives")
    for rel in payload["submission_relatives"]:
        conn.execute(
            "INSERT INTO submission_relatives(application_id, full_name, date_of_birth, relationship, address_type, address) VALUES(?, ?, ?, ?, ?, ?)",
            (
                rel["application_id"],
                rel["full_name"],
                rel["date_of_birth"],
                rel["relationship"],
                rel["address_type"],
                rel["address"],
            ),
        )

    for row in payload["member_directory"]:
        conn.execute(
            """
            INSERT OR REPLACE INTO member_directory(
              member_record_id, user_id, full_name, mobile, email, provider, nric, first_registered_at, last_seen_at, last_auth_action
            )
            VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                row["member_record_id"],
                row["user_id"],
                row["full_name"],
                row["mobile"],
                row["email"],
                row["provider"],
                row["nric"],
                row["first_registered_at"],
                row["last_seen_at"],
                row["last_auth_action"],
            ),
        )

    for row in payload["auth_events"]:
        conn.execute(
            """
            INSERT OR REPLACE INTO auth_events(
              event_id, event_type, method, timestamp, user_id, full_name, email, provider, application_id, reason
            )
            VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                row["event_id"],
                row["event_type"],
                row["method"],
                row["timestamp"],
                row["user_id"],
                row["full_name"],
                row["email"],
                row["provider"],
                row["application_id"],
                row["reason"],
            ),
        )

    upsert_meta(conn, "default_seed_version", DEFAULT_SEED_VERSION)
    upsert_meta(conn, "default_seeded_at", iso_now())

    return {
        "seeded": True,
        "users": len(payload["users"]),
        "donorSubmissions": len(payload["donor_submissions"]),
        "submissionRelatives": len(payload["submission_relatives"]),
        "memberDirectory": len(payload["member_directory"]),
        "authEvents": len(payload["auth_events"]),
    }


class CounterPayload(BaseModel):
    counter: int


def upsert_meta(conn: sqlite3.Connection, key: str, value: Any) -> None:
    conn.execute(
        "INSERT INTO app_meta(key, value) VALUES(?, ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        (key, json.dumps(value) if not isinstance(value, str) else value),
    )


def get_meta(conn: sqlite3.Connection, key: str, default: Any = None) -> Any:
    row = conn.execute("SELECT value FROM app_meta WHERE key = ?", (key,)).fetchone()
    if not row:
        return default
    value = row["value"]
    try:
        return json.loads(value)
    except Exception:
        return value


@app.on_event("startup")
def startup_event() -> None:
    init_db()


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/bootstrap")
def bootstrap() -> dict[str, Any]:
    with get_conn() as conn:
        users = [dict(r) for r in conn.execute("SELECT * FROM users ORDER BY created_at, id")]
        for u in users:
            raw = u.get("singpass_profile_json")
            u["singpassProfile"] = json.loads(raw) if raw else None
            u.pop("singpass_profile_json", None)
            u["singpassSub"] = u.pop("singpass_sub", "")
            u["fullName"] = u.pop("full_name", "")
            u["createdAt"] = u.pop("created_at", "")
            u["updatedAt"] = u.pop("updated_at", "")
            u["passwordHash"] = u.pop("password_hash", "")
            u["notifyChannel"] = str(u.pop("notify_channel", "") or "").strip().lower()

        donor_rows = [dict(r) for r in conn.execute("SELECT * FROM donor_submissions ORDER BY submitted_at, application_id")]
        rel_rows = [dict(r) for r in conn.execute("SELECT * FROM submission_relatives ORDER BY application_id, id")]
        rel_by_app: dict[str, list[dict[str, Any]]] = {}
        for rel in rel_rows:
            app_id = rel["application_id"]
            rel_by_app.setdefault(app_id, []).append(
                {
                    "fullName": rel.get("full_name", ""),
                    "dateOfBirth": rel.get("date_of_birth", ""),
                    "relationship": rel.get("relationship", ""),
                    "addressType": rel.get("address_type", ""),
                    "address": rel.get("address", ""),
                }
            )

        donor_records = []
        for row in donor_rows:
            donor_records.append(
                {
                    "applicationId": row.get("application_id", ""),
                    "submittedAt": row.get("submitted_at", ""),
                    "updatedAt": row.get("updated_at", ""),
                    "terminatedAt": row.get("terminated_at", ""),
                    "terminatedReason": row.get("terminated_reason", ""),
                    "terminatedNotes": row.get("terminated_notes", ""),
                    "terminatedByUserId": row.get("terminated_by_user_id", ""),
                    "terminatedByAdmin": bool(row.get("terminated_by_admin", 0)),
                    "donor": {
                        "fullName": row.get("donor_full_name", ""),
                        "nric": row.get("donor_nric", ""),
                        "nricNormalized": row.get("donor_nric_normalized", ""),
                        "mobile": row.get("donor_mobile", ""),
                        "email": row.get("donor_email", ""),
                        "address": row.get("donor_address", ""),
                        "contribution": row.get("donor_contribution"),
                        "group": row.get("donor_group_name", ""),
                        "notifyChannel": str(row.get("notify_channel", "") or "").strip().lower(),
                        "paymentMethod": row.get("payment_method", ""),
                        "hitpayChargeMode": row.get("hitpay_charge_mode", ""),
                        "hitpayRecurringEmail": row.get("hitpay_recurring_email", ""),
                        "egiroBank": row.get("egiro_bank", ""),
                        "egiroAccount": row.get("egiro_account", ""),
                        "egiroAccountHolder": row.get("egiro_account_holder", ""),
                        "egiroDeductionDay": row.get("egiro_deduction_day", ""),
                        "egiroStartMonth": row.get("egiro_start_month", ""),
                        "authUserId": row.get("auth_user_id", ""),
                        "authUserEmail": row.get("auth_user_email", ""),
                        "authProvider": row.get("auth_provider", ""),
                    },
                    "relatives": rel_by_app.get(row.get("application_id", ""), []),
                }
            )

        members = []
        for r in conn.execute("SELECT * FROM member_directory ORDER BY first_registered_at, member_record_id"):
            row = dict(r)
            members.append(
                {
                    "memberRecordId": row.get("member_record_id", ""),
                    "userId": row.get("user_id", ""),
                    "fullName": row.get("full_name", ""),
                    "mobile": row.get("mobile", ""),
                    "email": row.get("email", ""),
                    "provider": row.get("provider", ""),
                    "nric": row.get("nric", ""),
                    "firstRegisteredAt": row.get("first_registered_at", ""),
                    "lastSeenAt": row.get("last_seen_at", ""),
                    "lastAuthAction": row.get("last_auth_action", ""),
                }
            )

        auth_events = []
        for r in conn.execute("SELECT * FROM auth_events ORDER BY timestamp, event_id"):
            row = dict(r)
            auth_events.append(
                {
                    "eventId": row.get("event_id", ""),
                    "eventType": row.get("event_type", ""),
                    "method": row.get("method", ""),
                    "timestamp": row.get("timestamp", ""),
                    "userId": row.get("user_id", ""),
                    "fullName": row.get("full_name", ""),
                    "email": row.get("email", ""),
                    "provider": row.get("provider", ""),
                    "applicationId": row.get("application_id", ""),
                    "reason": row.get("reason", ""),
                }
            )

        donor_counter = int(get_meta(conn, "donor_counter", 1248))
        sync_pulse = get_meta(conn, "sync_pulse", None)
        return {
            "users": users,
            "donorRecords": donor_records,
            "memberDirectory": members,
            "authEvents": auth_events,
            "donorCounter": donor_counter,
            "syncPulse": sync_pulse,
        }


@app.put("/api/users")
def save_users(users: list[dict[str, Any]]) -> dict[str, int]:
    with get_conn() as conn:
        conn.execute("DELETE FROM users")
        for u in users:
            conn.execute(
                """
                INSERT INTO users(id, provider, singpass_sub, full_name, mobile, email, nric, notify_channel, address, password_hash, created_at, updated_at, singpass_profile_json)
                VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    u.get("id", ""),
                    u.get("provider", ""),
                    u.get("singpassSub", ""),
                    u.get("fullName", ""),
                    u.get("mobile", ""),
                    u.get("email", ""),
                    u.get("nric", ""),
                    u.get("notifyChannel", ""),
                    u.get("address", ""),
                    u.get("passwordHash", ""),
                    u.get("createdAt", ""),
                    u.get("updatedAt", ""),
                    json.dumps(u.get("singpassProfile")) if u.get("singpassProfile") else None,
                ),
            )
        upsert_meta(conn, "sync_pulse", {"source": "api", "sourceKey": "users", "timestamp": iso_now()})
    return {"saved": len(users)}


@app.put("/api/donor-records")
def save_donor_records(records: list[dict[str, Any]]) -> dict[str, int]:
    with get_conn() as conn:
        conn.execute("DELETE FROM submission_relatives")
        conn.execute("DELETE FROM donor_submissions")
        rel_count = 0
        for rec in records:
            donor = rec.get("donor", {})
            app_id = rec.get("applicationId", "")
            conn.execute(
                """
                INSERT INTO donor_submissions(
                  application_id, submitted_at, updated_at, donor_full_name, donor_nric, donor_nric_normalized, donor_mobile, donor_email, donor_address, donor_contribution,
                  donor_group_name, notify_channel, payment_method, hitpay_charge_mode, hitpay_recurring_email, egiro_bank, egiro_account, egiro_account_holder, egiro_deduction_day, egiro_start_month,
                  auth_user_id, auth_user_email, auth_provider, terminated_at, terminated_reason, terminated_notes, terminated_by_user_id, terminated_by_admin
                )
                VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    app_id,
                    rec.get("submittedAt", ""),
                    rec.get("updatedAt", ""),
                    donor.get("fullName", ""),
                    donor.get("nric", ""),
                    donor.get("nricNormalized", normalize_nric(donor.get("nric", ""))),
                    donor.get("mobile", ""),
                    donor.get("email", ""),
                    donor.get("address", ""),
                    donor.get("contribution"),
                    donor.get("group", ""),
                    donor.get("notifyChannel", ""),
                    donor.get("paymentMethod", ""),
                    donor.get("hitpayChargeMode", ""),
                    donor.get("hitpayRecurringEmail", ""),
                    donor.get("egiroBank", ""),
                    donor.get("egiroAccount", ""),
                    donor.get("egiroAccountHolder", ""),
                    donor.get("egiroDeductionDay", ""),
                    donor.get("egiroStartMonth", ""),
                    donor.get("authUserId", ""),
                    donor.get("authUserEmail", ""),
                    donor.get("authProvider", ""),
                    rec.get("terminatedAt", ""),
                    rec.get("terminatedReason", ""),
                    rec.get("terminatedNotes", ""),
                    rec.get("terminatedByUserId", ""),
                    1 if rec.get("terminatedByAdmin") else 0,
                ),
            )
            for rel in rec.get("relatives", []):
                rel_count += 1
                conn.execute(
                    "INSERT INTO submission_relatives(application_id, full_name, date_of_birth, relationship, address_type, address) VALUES(?, ?, ?, ?, ?, ?)",
                    (
                        app_id,
                        rel.get("fullName", ""),
                        rel.get("dateOfBirth", ""),
                        rel.get("relationship", ""),
                        rel.get("addressType", ""),
                        rel.get("address", ""),
                    ),
                )
        upsert_meta(conn, "sync_pulse", {"source": "api", "sourceKey": "donor-records", "timestamp": iso_now()})
    return {"saved": len(records), "relatives": rel_count}


@app.put("/api/member-directory")
def save_member_directory(members: list[dict[str, Any]]) -> dict[str, int]:
    with get_conn() as conn:
        conn.execute("DELETE FROM member_directory")
        for m in members:
            conn.execute(
                """
                INSERT INTO member_directory(member_record_id, user_id, full_name, mobile, email, provider, nric, first_registered_at, last_seen_at, last_auth_action)
                VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    m.get("memberRecordId", ""),
                    m.get("userId", ""),
                    m.get("fullName", ""),
                    m.get("mobile", ""),
                    m.get("email", ""),
                    m.get("provider", ""),
                    m.get("nric", ""),
                    m.get("firstRegisteredAt", ""),
                    m.get("lastSeenAt", ""),
                    m.get("lastAuthAction", ""),
                ),
            )
        upsert_meta(conn, "sync_pulse", {"source": "api", "sourceKey": "member-directory", "timestamp": iso_now()})
    return {"saved": len(members)}


@app.put("/api/auth-events")
def save_auth_events(events: list[dict[str, Any]]) -> dict[str, int]:
    with get_conn() as conn:
        conn.execute("DELETE FROM auth_events")
        for e in events:
            conn.execute(
                "INSERT INTO auth_events(event_id, event_type, method, timestamp, user_id, full_name, email, provider, application_id, reason) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    e.get("eventId", ""),
                    e.get("eventType", ""),
                    e.get("method", ""),
                    e.get("timestamp", ""),
                    e.get("userId", ""),
                    e.get("fullName", ""),
                    e.get("email", ""),
                    e.get("provider", ""),
                    e.get("applicationId", ""),
                    e.get("reason", ""),
                ),
            )
        upsert_meta(conn, "sync_pulse", {"source": "api", "sourceKey": "auth-events", "timestamp": iso_now()})
    return {"saved": len(events)}


@app.post("/api/next-application-id")
def next_application_id() -> dict[str, Any]:
    with get_conn() as conn:
        current = int(get_meta(conn, "donor_counter", 1248))
        next_value = current + 1
        upsert_meta(conn, "donor_counter", str(next_value))
    app_id = f"SP-{datetime.now(timezone.utc).year}-{next_value:04d}"
    return {"counter": next_value, "applicationId": app_id}


@app.put("/api/counter")
def set_counter(payload: CounterPayload) -> dict[str, int]:
    if payload.counter < 0:
        raise HTTPException(status_code=400, detail="Counter must be non-negative")
    with get_conn() as conn:
        upsert_meta(conn, "donor_counter", str(payload.counter))
    return {"counter": payload.counter}


def run_cli() -> int:
    parser = argparse.ArgumentParser(
        description="Skim Pintar SQLite helpers (API is run with: uvicorn server:app --host 0.0.0.0 --port 8000)"
    )
    parser.add_argument(
        "--seed-defaults",
        action="store_true",
        help="Insert default demo records. By default this is skipped when existing data is present.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Use with --seed-defaults to replace existing app data.",
    )
    args = parser.parse_args()

    if args.force and not args.seed_defaults:
        parser.error("--force can only be used together with --seed-defaults")

    init_result = init_db(seed_defaults_on_create=True)

    if args.seed_defaults:
        with get_conn() as conn:
            seeded = seed_default_data(conn, force=args.force)
        if not seeded.get("seeded"):
            print("Default seed skipped because data already exists. Re-run with --seed-defaults --force to replace.")
            return 0
        print(
            "Default seed inserted: "
            f"{seeded['users']} users, "
            f"{seeded['donorSubmissions']} donor submissions, "
            f"{seeded['submissionRelatives']} relatives, "
            f"{seeded['memberDirectory']} member entries, "
            f"{seeded['authEvents']} auth events."
        )
        return 0

    if init_result.get("created"):
        print("Database created and initialized.")
    else:
        print("Database initialized (existing file).")
    print("Run API with: uvicorn server:app --host 0.0.0.0 --port 8000")
    return 0


if __name__ == "__main__":
    raise SystemExit(run_cli())

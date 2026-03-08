# HitPay Integration Setup

For first-time setup, use `docs/START_HERE.md` first.

## What was added
- `backend/hitpay_server.py`
  - `POST /api/hitpay/create-payment`
  - `GET /api/hitpay/payment-status?payment_request_id=...`
  - `POST /api/hitpay/webhook` (HMAC verification using `HITPAY_SALT`)
- `frontend/skim-pintar4.html`
  - New **HitPay Checkout** card in **My Payments**
  - Frontend checkout launch + return status handling
  - Step 3 Join wizard now supports `eGIRO` or `HitPay` setup
  - HitPay now supports both `recurring` and `one-time` setup mode
  - If `HitPay` is selected, `Submit My Application` opens HitPay sandbox checkout
  - Successful return from HitPay redirects to `Payment Confirmation` page (`s-hitpay-confirm`)

## Run locally
```bash
PORT=3000 python3 backend/hitpay_server.py
```

Then open:
- `http://localhost:3000/`
- `http://localhost:3000/admin` (admin dashboard)

## Environment variables used
- `HITPAY_API_KEY`
- `HITPAY_SALT`
- `HITPAY_ENVIRONMENT` (`sandbox` or `production`)
- `SITE_URL`
- `PORT`

## HitPay dashboard configuration
- Add this webhook URL in HitPay dashboard:
  - `https://YOUR_DOMAIN/api/hitpay/webhook`
- Set redirect URL in your payment requests (already done by frontend/backend flow):
  - `https://YOUR_DOMAIN/skim-pintar4.html`

## Webhook logs
- Verified webhook events are appended to:
  - `data/hitpay_webhooks.ndjson`

## Admin dashboard
- New admin panel file:
  - `frontend/skim-pintar4-admin.html`
- User portal file remains:
  - `frontend/skim-pintar4.html`
- Admin dashboard reads from the same browser data keys used by the user portal.
- If API `/bootstrap` is unavailable, admin auto-falls back to browser local storage.
- Shortcut routes:
  - `/user` -> `skim-pintar4.html`
  - `/admin` -> `skim-pintar4-admin.html`
- Admin now includes subscriber cancellation flow with a confirmation form.

## Validation and flow updates
- HitPay payment confirmation page now also shows the Skim Pintar `Status ID` (application ID).
- Join flow requires login/register before entering payment setup, so submissions are tagged to user profile.
- Personal details validation now includes NRIC checksum and duplicate-data conflict checks (NRIC, email, mobile).

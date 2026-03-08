# Reminder Service Setup (WhatsApp, SMS, Email)

For first-time setup, use `docs/START_HERE.md` first.

This project now includes a real reminder backend at:

- `backend/reminder-service.js`

It sends overdue payment reminders through:

- WhatsApp (Twilio WhatsApp API)
- SMS (Twilio SMS API)
- Email (Resend API or SendGrid API)

## 1) Run the service

```bash
node backend/reminder-service.js
```

Default port is `8790`.

## 2) Required environment variables

Set these before running:

```bash
export SP_REMINDER_API_KEY="change-this-secret"
export SP_REMINDER_PORT="8790"
export SP_REMINDER_HOST="127.0.0.1"
export SP_REMINDER_INTERVAL_MINUTES="30"
export SP_REMINDER_OVERDUE_GRACE_DAYS="2"
export SP_REMINDER_PREFAIL_DAYS="2"
export SP_REMINDER_REACTIVATE_TTL_HOURS="168"
export SP_REMINDER_PUBLIC_BASE_URL="https://your-public-reminder-domain.example"
export SP_REMINDER_REACTIVATE_SECRET="change-this-reactivation-secret"
export SP_REMINDER_DATA_FILE="./data/reminder-store.json"
```

`SP_REMINDER_PUBLIC_BASE_URL` is used to build one-click reactivation links sent inside reminder messages.
Use a URL that donors can open from their phone (for example your server URL or ngrok URL).

If `SP_REMINDER_REACTIVATE_SECRET` is not set, service falls back to `SP_REMINDER_API_KEY`.

You can also place variables in:

- `.env.local` in the project root (auto-loaded by `reminder-service.js`)
- or a custom file via `SP_ENV_FILE=/path/to/file.env`

Twilio (for WhatsApp + SMS):

```bash
export TWILIO_ACCOUNT_SID="ACxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"
export TWILIO_AUTH_TOKEN="xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"
export TWILIO_WHATSAPP_FROM="whatsapp:+14155238886"
export TWILIO_SMS_FROM="+1xxxxxxxxxx"
```

Email (choose one provider):

Resend:

```bash
export RESEND_API_KEY="re_xxxxxxxxxxxxxxxxx"
export EMAIL_FROM="Masjid Ar-Raudhah <noreply@yourdomain.com>"
```

If `EMAIL_FROM` is not set and `RESEND_API_KEY` is present, the service falls back to:

`Skim Pintar <onboarding@resend.dev>` (good for initial testing).

or SendGrid:

```bash
export SENDGRID_API_KEY="SG.xxxxxxxxxxxxxxxxx"
export EMAIL_FROM="noreply@yourdomain.com"
```

## 3) Frontend sync config

`frontend/skim-pintar4.html` now syncs donor records to:

- `http://localhost:8790/api/sync/donors`
- and sends real-time account events to:
- `http://localhost:8790/api/notify/event`

If your backend URL is different, set in browser before loading app:

```js
window.SP_REMINDER_SYNC_URL = "https://your-domain/api/sync/donors";
window.SP_REMINDER_SYNC_API_KEY = "change-this-secret";
window.SP_NOTIFICATION_EVENT_URL = "https://your-domain/api/notify/event";
window.SP_NOTIFICATION_EVENT_API_KEY = "change-this-secret";
```

`SP_NOTIFICATION_EVENT_API_KEY` can be the same value as `SP_REMINDER_SYNC_API_KEY`.

## 4) Trigger a manual reminder run

```bash
curl -X POST http://localhost:8790/api/reminders/run \
  -H "x-sp-api-key: change-this-secret"
```

## 5) Trigger a manual event notification (test)

```bash
curl -X POST http://localhost:8790/api/notify/event \
  -H "Content-Type: application/json" \
  -H "x-sp-api-key: change-this-secret" \
  -d '{
    "eventType": "subscription_created",
    "donor": {
      "applicationId": "SP-2026-9999",
      "fullName": "Test Donor",
      "mobile": "91234567",
      "email": "test@example.com",
      "notifyChannel": "sms",
      "contribution": 20,
      "group": "Skim Pintar Plus Group"
    }
  }'
```

## 6) Health check

```bash
curl http://localhost:8790/health
```

## 7) Delivery logs

```bash
curl http://localhost:8790/api/reminders/log \
  -H "x-sp-api-key: change-this-secret"
```

## 8) One-click reactivation link

Each missed/overdue/failed/grace reminder can include a one-click reactivation URL:

- `GET /api/reactivate?token=...`

This endpoint is intentionally public (no API key needed) so donors can tap from SMS/WhatsApp/email directly.

When the link is valid, the service:

- records a reactivation request
- clears previous missed/overdue/failed dedupe markers for that cycle
- sends a `payment_reactivation_requested` confirmation notification

## How overdue is detected

For each active donor record:

- Use `donor.egiroDeductionDay` as due day each month.
- `SP_REMINDER_PREFAIL_DAYS` before due day: send `payment_due_soon`.
- On/after due day: send missed + grace/overdue/failed reminders based on lateness.
- Grace reminders are sent daily during `SP_REMINDER_OVERDUE_GRACE_DAYS`.
- Service deduplicates per donor per month cycle to avoid repeated duplicate sends.

Email fallback is built in: if preferred channel is WhatsApp/SMS and delivery fails or is unavailable, service can fallback to email when email provider is configured.

## Event notifications currently supported

- `subscription_created`
- `donation_amount_updated`
- `beneficiaries_added`
- `beneficiaries_updated`
- `beneficiaries_deleted`
- `donation_stopped`
- `payment_successful`
- `payment_due_soon`
- `payment_missed`
- `payment_grace_period`
- `payment_overdue`
- `payment_failed`
- `payment_reactivation_requested`
- `notification_preference_updated`

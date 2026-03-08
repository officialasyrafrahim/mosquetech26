# MosqueTech26 Simple Setup Guide

This guide is for first-time users.
Follow it in order. Copy and paste each command exactly.

## What this app does

When running locally, you will have:

- User portal: `http://localhost:3000/user`
- Admin portal: `http://localhost:3000/admin`

The app uses:

- a database service (Python)
- a web server (Python)
- an optional reminder service (Node.js)

## Before you start (one-time install)

You need these installed on your computer:

- Python 3.10 or newer
- Node.js 18 or newer

Quick check:

```bash
python3 --version
node --version
```

## Step 1: Open this project folder

In Terminal:

```bash
cd YOUR_DIR/mosquetech26
```

## Step 2: Install Python packages (one-time)

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r backend/requirements.txt
```

You only need to run `pip install` again if dependencies change.

## Step 3: Start the database service

Keep this terminal window open:

```bash
source .venv/bin/activate
uvicorn backend.server:app --host 0.0.0.0 --port 8000
```

If it starts correctly, leave it running.

## Step 4: Start the web server

Open a second terminal window:

```bash
cd YOUR_DIR/mosquetech26
source .venv/bin/activate
PORT=3000 python3 backend/hitpay_server.py
```

If it starts correctly, leave it running.

## Step 5: Open the app in your browser

- User portal: `http://localhost:3000/user`
- Admin portal: `http://localhost:3000/admin`

At this point, the core app is running.

## Step 6 (Optional): Start reminder service

Use this only if you want reminder events and reminder logs.

Open a third terminal window:

```bash
cd YOUR_DIR/mosquetech26
node backend/reminder-service.js
```

Reminder health check:

```bash
curl http://localhost:8790/health
```

## Environment file (`.env.local`)

You can place secrets in:

- `.env.local` (project root)

Common values:

```env
# Reminder service protection key
SP_REMINDER_API_KEY=change-this-secret
SP_REMINDER_PORT=8790
SP_REMINDER_PREFAIL_DAYS=2
SP_REMINDER_OVERDUE_GRACE_DAYS=2

# Optional email provider for reminders
RESEND_API_KEY=re_xxxxxxxxxxxxx
EMAIL_FROM=Skim Pintar <noreply@yourdomain.com>

# Optional: one-click reactivation links in reminder messages
# Use your public URL (for example your ngrok URL)
SP_REMINDER_PUBLIC_BASE_URL=https://your-public-url.example
SP_REMINDER_REACTIVATE_SECRET=change-this-reactivation-secret
```

## Optional: enable real HitPay

If you want real/sandbox HitPay checkout, add these to `.env.local`:

```env
HITPAY_API_KEY=your_hitpay_api_key
HITPAY_SALT=your_hitpay_webhook_salt
HITPAY_ENVIRONMENT=sandbox
SITE_URL=http://localhost:3000
```

## Optional: seed demo data

If you want sample records:

```bash
cd YOUR_DIR/mosquetech26
source .venv/bin/activate
python3 backend/server.py --seed-defaults
```

## Stopping the app

In each running terminal, press:

- `Ctrl + C`

## If something does not work

- `uvicorn: command not found`
  Run:
  ```bash
  source .venv/bin/activate
  pip install -r backend/requirements.txt
  ```
- `node: command not found`
  Install Node.js, then run again.
- Port already in use
  Use another port, for example:
  ```bash
  PORT=3001 python3 backend/hitpay_server.py
  ```

## Where files are now

- App pages: `frontend/`
- Backend services: `backend/`
- Database and logs: `data/`
- Documentation: `docs/`

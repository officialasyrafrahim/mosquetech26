# Skim Pintar Server Database

For first-time setup, use `docs/START_HERE.md` first.

This project supports a server-side **SQLite** database (`data/skim_pintar.db`) for:

- user accounts
- donor applications + relatives
- member directory
- auth/admin events
- donor counter + sync pulse metadata

## 1) Install and run database API (`backend/server.py`)

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r backend/requirements.txt
uvicorn backend.server:app --host 0.0.0.0 --port 8000
```

When `backend/server.py` starts, it auto-creates/migrates `data/skim_pintar.db`.

Default demo data is inserted automatically **only when the DB file is freshly created**.

To insert default demo data manually later:

```bash
python3 backend/server.py --seed-defaults
```

To force-replace existing data with defaults:

```bash
python3 backend/server.py --seed-defaults --force
```

## 2) Run web app server (`backend/hitpay_server.py`)

```bash
PORT=3000 python3 backend/hitpay_server.py
```

Open:

- User app: `http://localhost:3000/user`
- Admin app: `http://localhost:3000/admin`

By default, both apps target `http://localhost:8000/api` for database sync.

## 3) API endpoints used by web app

- `GET /api/bootstrap`
- `PUT /api/users`
- `PUT /api/donor-records`
- `PUT /api/member-directory`
- `PUT /api/auth-events`
- `PUT /api/counter`
- `POST /api/next-application-id` (available)

## 4) Optional custom API URL

Set before app script executes:

```html
<script>
  window.SkimPintarApiBase = 'https://your-server.example/api';
</script>
```

## 5) Admin data management

The admin page now persists cancellation and event updates back to the database API (not just local storage), so changes appear in user-facing views after refresh.

`notifyChannel` is now persisted for both users and donor submissions in SQLite and returned by `/api/bootstrap`, so notification preferences stay consistent between user and admin pages.

## 6) Reminder service integration (`backend/reminder-service.js`)

The user/admin pages now sync donor records to the reminder backend and send notification events.

Run reminder service:

```bash
node -v   # ensure Node.js is installed
node backend/reminder-service.js
```

Optional browser runtime config (before app script loads):

```html
<script>
  window.SP_REMINDER_SYNC_URL = 'http://localhost:8787/api/sync/donors';
  window.SP_REMINDER_SYNC_API_KEY = 'change-this-secret';
  window.SP_NOTIFICATION_EVENT_URL = 'http://localhost:8787/api/notify/event';
  window.SP_NOTIFICATION_EVENT_API_KEY = 'change-this-secret';
</script>
```

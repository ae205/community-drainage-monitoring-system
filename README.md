# Community Drainage Monitoring and Reporting System

A working prototype implementing the design in Chapters 1–3: citizen drainage
reporting with photo evidence and location pinning, admin triage with status
tracking, and notifications. Now offline-capable: the app itself (not just
previously-loaded data) works with zero internet connection, and reports
submitted offline are queued on-device and sync automatically once
connectivity returns.

## Requirements
- Python 3.10+
- pip packages: `flask`, `pyjwt`, `pillow`

```bash
pip install flask pyjwt pillow
```

## Setup and run

```bash
cd backend
python3 database.py          # creates database.db with the schema
python3 -c "
from werkzeug.security import generate_password_hash
from database import get_db
conn = get_db()
conn.execute(
    \"INSERT INTO Users (full_name, email, phone, password_hash, role) VALUES (?, ?, ?, ?, 'admin')\",
    ('Admin Officer', 'admin@drainage.local', '08000000000', generate_password_hash('admin123'))
)
conn.commit()
conn.close()
"
python3 app.py                # starts the server on http://localhost:5050
```

Then open **http://localhost:5050** in your browser.

- **Admin login:** admin@drainage.local / admin123
- **Resident:** register your own account via the Register page

## Offline capability

This is a Progressive Web App (PWA). A service worker (`sw.js`) caches the
entire app shell on first visit, so the interface loads even with zero
connectivity — try turning off WiFi and reloading any page after visiting it
once. Submitting a drainage report while offline saves it to the browser's
IndexedDB instead of failing; once connectivity returns, it's sent to the
server automatically (you'll see a "waiting to sync" indicator in the navbar
in the meantime). Each queued report carries a unique client-generated ID so
a retried sync can never create a duplicate report on the server.

What this does **not** cover: the admin/triage side assumes connectivity
(an environmental officer doing live triage needs current data), and there's
no cross-device sync — the offline queue lives in that one browser only,
on that one device, until it syncs.

## What's real vs. substituted

This runs on Flask + SQLite rather than the documented Node.js/Express +
PostgreSQL stack, and the map uses real Leaflet + OpenStreetMap tiles loaded
from a CDN (requires internet the first time a map is viewed; cached after
that). Everything else — schema, endpoints, JWT auth, password hashing,
status lifecycle, offline sync — is a full implementation, not a stub.

## Project structure
```
backend/
  app.py             — Flask API (all endpoints, including idempotent
                        report submission for safe offline-sync retries)
  database.py        — schema
  uploads/            — uploaded report photos
frontend/
  *.html              — 14 pages (resident + admin)
  app.js              — shared utilities + service worker registration +
                        offline/online detection + sync engine
  idb.js              — IndexedDB wrapper for the offline report queue
  sw.js               — service worker (app-shell caching, API cache fallback)
  manifest.json       — PWA manifest (installable on phone/desktop)
  locationpicker.js   — Leaflet + OpenStreetMap location picker
```

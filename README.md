# Wiretide Controller

Wiretide is a local, security-first controller for OpenWrt devices. It manages device registration/approval, configuration delivery, status/monitoring, and an optional AI/security module. The stack is FastAPI + SQLModel + server-rendered templates with minimal JS.

## Components
- `backend/`: FastAPI app (`wiretide.main:app`), API routes, templates, static assets, tests.
- `agent/`: OpenWrt agent overview docs.
- `UI/`: UI overview docs.
- `installer/`: Installer docs and `install_wiretide.sh`.

## Running the backend (dev)
```bash
cd backend
python -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
uvicorn wiretide.main:app --host 127.0.0.1 --port 9000
```
- Admin token defaults to `wiretide-admin-dev`; set `WIRETIDE_ADMIN_TOKEN` and `WIRETIDE_ADMIN_COOKIE_SECURE=true` for HTTPS.
- Static/templates served by FastAPI; Nginx proxy recommended for HTTPS.

## Installer (prod/test)
- Script: `installer/install_wiretide.sh`
- Flags: `--dry-run`, `--update` (tar backup), `--cert-cn <cn>` (self-signed TLS CN).
- Tasks: create `wiretide` user, deploy to `/opt/wiretide`, venv, systemd service on 127.0.0.1:9000, Nginx HTTPS proxy with self-signed certs.
- Example: `sudo installer/install_wiretide.sh --update --cert-cn wiretide.local`

## API/UI highlights
- Agent endpoints: `/register`, `/status`, `/config`, `/token/current`.
- Admin endpoints: `/api/devices`, `/api/devices/approve|block|delete`, `/api/settings`, `/api/settings/token/regenerate`, `/api/settings/monitoring`.
- UI pages: `/` landing, `/devices` list with filters/actions, `/devices/{id}` detail with tabs and actions; `/login` sets admin cookie (requires `python-multipart`).

## Docs
- `ARCHITECTURE.md` – system overview.
- `backend/BACKEND.md`, `agent/WRTAGENT.md`, `UI/UI.md`, `installer/INSTALLER.md` – component guides.

## Tests
```bash
cd backend
. ../.venv/bin/activate
pytest -q
```

## Notes
- `.gitignore` excludes venv, DBs, logs, caches.
- Self-signed TLS by default; replace certs in Nginx for production.
- Device DB (`wiretide.db`) is local; not tracked in git. Fresh installs start empty.***

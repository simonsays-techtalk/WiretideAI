# Backend testing (manual)

Quick checks for the backend skeleton (no network dependencies required).

## Setup
- Create and activate a venv: `python -m venv .venv && . .venv/bin/activate`
- Install deps: `pip install -r backend/requirements.txt`
- Start server from `backend/`: `uvicorn wiretide.main:app --host 127.0.0.1 --port 9000`

## Smoke tests
- Health: `curl http://127.0.0.1:9000/health`
- Fetch shared token: `curl http://127.0.0.1:9000/token/current` → note `shared_token`.
- Admin auth:
  - Password mode (installer default): use Basic auth, e.g. `-H "Authorization: Basic $(printf 'admin:<password>' | base64)"`.
  - Legacy token mode (when `WIRETIDE_ADMIN_PASSWORD_HASH` is unset): header `X-Admin-Token` (default `wiretide-admin-dev`; override via `WIRETIDE_ADMIN_TOKEN`).

## Agent flow (example)
- Register: `curl -X POST http://127.0.0.1:9000/register -H "X-Shared-Token: <token>" -H "Content-Type: application/json" -d '{"hostname":"demo-router","ssh_enabled":true}'`
- Status: `curl -X POST http://127.0.0.1:9000/status -H "X-Shared-Token: <token>" -H "Content-Type: application/json" -d '{"device_id":<id>,"dns_ok":true,"ssh_enabled":true}'`
- Config fetch (pops oldest): `curl "http://127.0.0.1:9000/config?device_id=<id>" -H "X-Shared-Token: <token>"`
- Approve device (regenerates shared token): `curl -X POST http://127.0.0.1:9000/api/devices/approve -H "Authorization: Basic $(printf 'admin:<password>' | base64)" -H "Content-Type: application/json" -d '{"device_id":<id>,"device_type":"router"}'`
- Queue config for approved device: `curl -X POST http://127.0.0.1:9000/api/queue-config -H "Authorization: Basic $(printf 'admin:<password>' | base64)" -H "Content-Type: application/json" -d '{"device_id":<id>,"package":"wiretide.firewall","package_json":{"profile":"strict"}}'`
- Clear queued configs for a device: `curl -X POST http://127.0.0.1:9000/api/configs/clear -H "Authorization: Basic $(printf 'admin:<password>' | base64)" -H "Content-Type: application/json" -d '{"device_id":<id>}'`
- After approval, fetch the refreshed token via `/token/current` and use it for subsequent agent calls (config fetches require the latest shared token).

## Admin/UI helpers
- List devices (supports filters: `device_type`, `status`, `search`, `limit`, `offset`): `curl "http://127.0.0.1:9000/api/devices?device_type=router&status=approved&search=demo" -H "Authorization: Basic $(printf 'admin:<password>' | base64)"`
- Device detail: `curl http://127.0.0.1:9000/api/devices/<id> -H "Authorization: Basic $(printf 'admin:<password>' | base64)"`
- Get settings: `curl http://127.0.0.1:9000/api/settings -H "Authorization: Basic $(printf 'admin:<password>' | base64)"`
- Regenerate shared token: `curl -X POST http://127.0.0.1:9000/api/settings/token/regenerate -H "Authorization: Basic $(printf 'admin:<password>' | base64)"`
- Update agent update policy: `curl -X PATCH http://127.0.0.1:9000/api/settings/agent-update -H "Authorization: Basic $(printf 'admin:<password>' | base64)" -H "Content-Type: application/json" -d '{"agent_update_policy":"off","agent_update_url":null,"agent_min_version":null}'`
- Toggle monitoring: `curl -X PATCH http://127.0.0.1:9000/api/settings/monitoring -H "Authorization: Basic $(printf 'admin:<password>' | base64)" -H "Content-Type: application/json" -d '{"monitoring_api_enabled":true}'`
- Block device: `curl -X POST http://127.0.0.1:9000/api/devices/block?device_id=<id> -H "Authorization: Basic $(printf 'admin:<password>' | base64)"`
- Remove device: `curl -X DELETE http://127.0.0.1:9000/api/devices/<id> -H "Authorization: Basic $(printf 'admin:<password>' | base64)"`
- Config queue cap: per-device queue keeps the 10 most recent entries; oldest are trimmed automatically.
- Simple server-rendered UI pages (require Jinja2): `/` landing, `/devices` list with filters (device_type, status, search, limit, offset).
- Browser login (requires `python-multipart`): POST `/login` with `admin_username` + `admin_password` (or legacy `admin_token` if no password hash is set), or use `/login` page; sets cookie `wiretide_admin`. `/logout` clears the cookie.
- To expose externally, run uvicorn on `0.0.0.0` (e.g., `uvicorn ... --host 0.0.0.0 --port 9000`) and consider placing Nginx in front for TLS + `/static` passthrough.
- Example Nginx snippet: see `backend/nginx/wiretide.conf.example` (proxies to `127.0.0.1:9000`, serves `/static` directly).
- When using HTTPS and Nginx: switch the admin cookie `secure=True` in settings; update cert paths in the example (replace snakeoil with real certs).
- If Nginx static alias causes 403 (home dir perms), remove the `/static` location and let uvicorn serve static assets, or move static files to a neutral path (e.g., `/opt/wiretide/static/`) and update the alias.
- Cookie flags: set `WIRETIDE_ADMIN_COOKIE_SECURE=true` when HTTPS is enforced; SameSite is `lax` by default.
- UI shell: devices list now links to detail pages and includes a topbar with a user menu (theme toggle stub, logout).
- Device detail view shows status fields (DNS/NTP/firewall profile/clients) and inline approve/block/remove actions.
- Device detail tabs added (Live/Firewall/Clients/Logs/Advanced); actions reused on detail page.
- Router/AP tabs rendered conditionally (firewall for router/firewall types, WiFi for APs); admin badge shown in topbar; action errors now surface API text.

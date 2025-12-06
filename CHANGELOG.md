# Changelog

All notable changes to this project will be documented in this file.

## Unreleased
### Added
- Placeholder for upcoming changes.
- Added a reference OpenWrt agent skeleton script (`agent/agent-skeleton.sh`) illustrating register/status/config/token flows.
- Expanded agent skeleton with token recovery, logging, status/config stubs, and SHA validation.
- Documented agent/controller contract and local config/state layout (`agent/CONTRACT.md`); refreshed `.plan` with agent build-out milestones.
- Hardened agent skeleton: env+config loading, state dir handling, basic SSH detection, HTTP timeouts/retries, token recovery guardrails, canonical JSON hashing (jq if available), safer logging defaults, richer status probes (DNS/NTP/firewall profile, DHCP+WiFi clients), DRY_RUN support, and stub handlers per package type.
- Added dry-run harness (`agent/dry-run.sh` + `agent/mock_backend.py`) for offline loop testing with a mock controller.
- Documented config package schemas (firewall/apps/wifi/update), clients payload shape, and dry-run behavior in `agent/CONTRACT.md`.
- Implemented initial applies: UCI-based firewall profile set + reload, WiFi UCI updates/reload, opkg app installs (adblock/banip), and update script download/execute (version skip, optional SHA) with configurable commands/paths; all honor DRY_RUN.
- Added OpenWrt packaging artifacts (`agent/wiretide-agent-run`, `agent/init.d/wiretide`) to align with procd service deployment.
- Agent HTTP fetchers now support curl/wget/uclient with env-based TLS opts (`CURL_OPTS`/`WGET_OPTS`/`*_CMD`); documented in `agent/CONTRACT.md` and `agent/WRTAGENT.md`.

### Fixed
- Corrected `/api/devices/approve` flow so approval and token rotation complete before config queueing; fixes 500 errors during approval.

### Added
- Admin UI endpoints for listing devices, viewing device details, and managing settings (shared token regen, agent update policy).
- Config queue management: per-device cap (10), clear endpoint, and config fetch now pops latest entry after delivery.
- Pinned `httpx` in backend requirements for future TestClient-based tests.
- Expanded manual testing guide with new admin/config flows (`backend/TESTING.md`).
- Added pytest-based in-memory backend tests covering register/approve, config pop, device listing, settings/token regeneration (`backend/tests/test_agent_flows.py`).
- Added device list filters + pagination metadata, stricter device type validation, monitoring toggle endpoint, and validated agent update policy.
- Added simple server-rendered templates (`/`, `/devices`) with sidebar layout and filters; static assets served via `/static`; timestamps remain UTC-aware.
- Added status transition enforcement (no type reset to unknown, approval requires allowed transitions), block/remove endpoints, and pagination controls in templates.
- Added minimal cookie-based admin login (`/login` form, `/logout`), with header-based admin access still supported; requires `python-multipart` for form parsing.
- Documented external access guidance (bind uvicorn to 0.0.0.0; recommend Nginx for TLS and static passthrough) in backend testing guide.
- Noted Nginx static alias caveat (403 from home dir perms) and workaround to serve `/static` via uvicorn or move assets to neutral path.
- Admin cookie Secure flag is configurable (`WIRETIDE_ADMIN_COOKIE_SECURE`); device list links to detail page; logout link added in UI chrome.
- Added device detail page with approve/block/remove actions and topbar user menu with theme toggle; improved light/dark theming and layout scaling.
- Devices list UI now includes inline approve/block/remove actions.
- Device detail view now surfaces status fields (DNS/NTP/firewall profile/clients).
- Added tabbed device detail UI (Live/Firewall/Clients/Logs/Advanced) with reusable actions.
- Router/AP tabs rendered conditionally; UI shows admin badge; action buttons now surface API error text on failure.
- Added controller installer script (`installer/install_wiretide.sh`) with dry-run/update flags (tar backup), self-signed TLS, systemd + nginx provisioning; documented usage in `installer/INSTALLER.md`.
- Fixed nginx template (removed map/connection helper) to avoid config parse errors.
- Installer/nginx example updated: add X-Real-IP, proxy_http_version 1.1, and plain Connection upgrade to avoid nginx parse errors.

## 0.0.1 - 2025-12-05
### Added
- Introduced `CHANGELOG.md` to track repository changes.
- Added initial FastAPI backend skeleton (`wiretide.main:app`) with SQLite-ready SQLModel setup and health endpoint.
- Defined core data models (devices, device_status, device_configs, settings) and configuration loader.
- Pinned backend dependencies in `backend/requirements.txt`.
- Added `.plan` to capture next implementation steps.
- Implemented agent-facing routes (`/register`, `/status`, `/config`, `/token/current`) with shared token validation and device approval endpoint (`/api/devices/approve`).
- Seeded controller settings with shared token generation on startup.
- Added admin-token-protected endpoints for approval and config queueing (`/api/queue-config`) with deterministic SHA256 hashing of package payloads.
- Documented manual smoke tests for agent and admin flows in `backend/TESTING.md`.

### Changed
- Cleaned and restructured Markdown guides (`AGENTS.md`, `ARCHITECTURE.md`, `agent/WRTAGENT.md`, `backend/BACKEND.md`, `installer/INSTALLER.md`, `UI/UI.md`) for clarity and consistency without altering intent.
- Added cross-links between architecture and component guides to speed up navigation.

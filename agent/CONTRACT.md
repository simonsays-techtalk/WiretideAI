# Wiretide Agent ↔ Controller Contract

Authoritative reference for the agent-facing HTTP contract and local configuration/state layout. Keep this in sync with the backend (`backend/wiretide/routes.py`, `backend/wiretide/schemas.py`) and the agent runner script.

## Transport & Auth
- Base URL: `controller_url` (e.g., `http://127.0.0.1:9000`), no trailing slash.
- Header: `X-Shared-Token: <shared_token>` required for `/register`, `/status`, `/config`.
- Missing token → `401 {"detail":"Missing shared token"}`; wrong token → `403 {"detail":"Invalid shared token"}`.
- JSON bodies are expected; FastAPI will also accept form-encoded payloads, but the agent should send JSON with `Content-Type: application/json`.
- Responses use ISO 8601 timestamps with timezone (`datetime` from FastAPI).

## Endpoint contract

### POST `/register`
Request JSON (see `RegisterRequest`):
- `hostname` (str, required)
- `description` (str, optional)
- `device_type` (str, optional, default `unknown`; one of `router|switch|firewall|access_point|unknown`)
- `ssh_enabled` (bool, default false)
- `ssh_fingerprint` (str, optional)
- `agent_version` (str, optional)
- `device_id` (int, optional; reuse an existing device)
- `ip_address` (str, optional)

Response JSON (`RegisterResponse`):
- `device_id` (int)
- `status` (str; `waiting|approved|blocked`)
- `approved` (bool)
- `device_type` (str)
- `shared_token_required` (bool, always true)

Error cases: invalid `device_type` (400), `device_type=="unknown"` while resetting an existing device (400), unknown `device_id` (404).

### POST `/status`
Request JSON (`StatusReport`):
- `device_id` (int, required)
- `dns_ok`, `ntp_ok` (bool, optional)
- `firewall_profile_active` (str, optional)
- `security_log_samples` (object, optional)
- `clients` (array of objects, optional; DHCP + WiFi). Fields typically include `ip`, `mac`, `host` for DHCP leases and `mac`, `iface`, `ssid`, `band` for WiFi associations.
  - WiFi clients are enriched with `ip` and `host` when a matching DHCP lease exists.
- `ssh_enabled` (bool, optional)
- `ssh_fingerprint` (str, optional)
- `agent_version` (str, optional)

Response JSON (`StatusResponse`):
- `status` (str, always `"ok"`)
- `last_seen` (ISO timestamp)

Error cases: device missing (404), token errors (401/403).

### GET `/config?device_id=<id>`
Response JSON (`ConfigResponse`) when a pending config exists:
- `device_id` (int)
- `package` (str; e.g., `wiretide.firewall`, `wiretide.apps`, `wiretide.ssid`, `wiretide.update`)
- `package_json` (object; payload to apply)
- `sha256` (hex string; computed by backend)
- `created_at` (ISO timestamp)

Behavior:
- Device must be approved and status `approved`; otherwise `403 {"detail":"Device not approved"}`.
- If no pending config: `404 {"detail":"No pending config"}`.
- After a successful fetch the backend deletes the most recent config entry (single delivery).
- Hashing: backend computes SHA256 over the **canonical JSON string** of `package_json` using `json.dumps(..., sort_keys=True, separators=(",", ":"))`. The agent must verify using the same canonicalization.

### GET `/token/current`
Response JSON (`TokenResponse`):
- `shared_token` (str)

No auth required; used after a `403` to recover a rotated token.

## Config package schemas (delivered via `/config`)
The backend returns the latest queued config per device; the agent must verify `sha256` against the canonical JSON string (`json.dumps(..., sort_keys=True, separators=(",", ":"))` on the backend).

Common fields:
- `package` (string) indicates handler.
- `package_json` (object) carries the payload.
- `sha256` (string) is the hex digest of the canonical JSON string of `package_json`.

Packages (current intent):
- `wiretide.firewall`:
  - `profile` (string; `default|strict|stealth|custom`)
  - `rules` (object; UCI fragments/templates for firewall)
- `wiretide.apps`:
  - `adblock_enabled` (bool)
  - `banip_enabled` (bool)
- `wiretide.ssid`:
  - `ssid` (string), `password` (string), `band` (e.g., `2g|5g`), `channel`, `htmode`, `country`, `txpower`, optional static IP fields.
- `wiretide.update`:
  - `url` (string), `version` (string), `script_sha256` (string, optional), `policy` (string aligned with controller settings).

Agent expectations:
- Treat `404 No pending config` as normal; do not log noisy errors.
- Reject payloads with SHA mismatch.
- Unknown `package` → log and ignore.
- Applies must be idempotent; reload services (firewall/wifi) only after successful writes.
- `DRY_RUN=1` short-circuits apply handlers for offline/dry testing.
- Configurable commands (env overrides) for reloads and installs: `FIREWALL_RELOAD_CMD`, `WIFI_RELOAD_CMD`, `OPKG_UPDATE_CMD`, `OPKG_INSTALL_CMD`, `DOWNLOAD_CMD`, `UPDATE_SCRIPT_PATH`.
- Update handler skips when `version` matches the current `agent_version`; if `script_sha256` is provided it is verified after download.
- Controllers should queue a `wiretide.update` package when shipping a newer agent; agents will apply it once and skip if the `version` matches.
- HTTP fetchers: agent tries `curl` → `wget` → `uclient-fetch`. TLS opts are honored via env: `CURL_OPTS`/`CURL_CMD`, `WGET_OPTS`/`WGET_CMD`. For self-signed controllers, set `CURL_OPTS="-k"` or `WGET_OPTS="--no-check-certificate"`. Installing `ca-bundle` is preferred where possible. Recovered shared tokens are cached under `STATE_DIR/shared_token` and reloaded on startup to avoid repeated `/token/current` calls after rotations.
- Loop backoff: on consecutive failures the agent increases sleep by `BACKOFF_STEP` seconds up to `BACKOFF_CAP` (defaults 10s/300s) to avoid hammering an unreachable controller.

## Local agent config & state layout
Config file: `/etc/wiretide/agent.conf` (shell key/value).

Supported keys (defaults in parentheses):
- `controller_url` (no default; required)
- `shared_token` (no default; required)
- `device_id` (optional; persisted copy of the assigned device id)
- `device_type` (optional hint; falls back to `unknown`)
- `description` (optional)
- `agent_version` (optional; reported in register/status)
- `interval` (seconds, default `30`)
- `state_dir` (default `/tmp/wiretide`)
- `log_file` (default `/var/wiretide-debug.log`)
- `dry_run` (default `0`; when `1` apply handlers log-only)

Runtime overrides (env): `CONTROLLER_URL`, `SHARED_TOKEN`, `DEVICE_ID`, `INTERVAL`, `DRY_RUN`.

State files:
- `${state_dir}/device_id` caches the assigned id.
- Future state (heartbeat timestamps, last config hash) should also live under `${state_dir}`.

Logging:
- Append-only to `log_file`, timestamps via `date -Iseconds`, redact secrets (tokens, hashes).

Notes:
- Keep config/state writable for BusyBox environments; avoid hard dependencies beyond `wget`, `jsonfilter`, `sha256sum`.
- Agent must tolerate `404 No pending config` as a normal condition and back off per `interval`.

## Dry-run harness
- Script: `agent/dry-run.sh` starts `agent/mock_backend.py` (local HTTP server) and runs `agent-skeleton.sh` with `DRY_RUN=1`, short interval, and test token.
- Default values: port `9000`, token `drytoken`, interval `5s`, log `"/tmp/wiretide-dry.log"`, state `"/tmp/wiretide-dry"`.
- View recent log tail after the run; adjust with `TIMEOUT_SECS`, `MOCK_PORT`, `SHARED_TOKEN`, `INTERVAL` as needed.

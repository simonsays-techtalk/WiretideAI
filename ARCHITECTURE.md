# Wiretide Architecture

Wiretide is a lightweight, security-first controller for **OpenWrt devices**. It manages inventory, configuration, monitoring, security controls, app management, and (future) WiFi provisioning without heavy device-side software. The platform stays local/offline by default.

## Components
- **Wiretide Controller** (Backend + UI).
- **Wiretide Agent** (OpenWrt-side).
- **Data Model** (devices, status, configs, settings).
- **Optional Security Monitoring API** (AI integration), disabled by default and toggleable via Settings → System → AI Integration.
- Zie ook: `agent/WRTAGENT.md`, `backend/BACKEND.md`, `installer/INSTALLER.md`, `UI/UI.md`, `AGENTS.md`.

## 0. Installer (Controller)
- Target: Ubuntu Server 24.04 or higher.
- Installs all dependencies; see `pseudoinstaller.sh` for a known working version.

## 1. System Overview
- Similar gedrag als een UniFi Controller, maar voor OpenWrt.
- Minimal agent; central controller voor UI + API.
- Device control via SSH (agent verifieert, controller nooit).
- Approval workflow met security token.
- Voorspelbare configuratie delivery via `/config`.

## 2. Controller Architecture
### 2.1 Technology Stack
- Python backend (FastAPI-stijl).
- Serveert REST API (agents, UI, optionele AI-integraties) en statische HTML-templates (Jinja-achtig); minimale JS.
- Database-tabellen: `devices`, `device_status`, `device_configs`, `settings`, optioneel `security_events` voor AI monitoring.

### 2.2 Core Agent-Facing Endpoints
- **POST `/register`**: init device-registratie. Zet status `waiting`, slaat SSH-info/agentversie op. Controller test SSH nooit; agent doet validatie. Approval vereist `device_type != unknown` en `ssh_enabled=1`.
- **POST `/status`**: heartbeat met `last_seen`, `agent_version`, optionele SSH-info, `device_status`-velden (dns/ntp, firewallprofiel, security log samples, LAN clients, `updated_at`).
- **GET `/config`**: approved device + geldig shared token → returns device-specifieke config of globale fallback.
- **GET `/token/current`**: agent vraagt nieuwe token na expiratie.
- **POST `/api/devices/approve`**: UI-trigger; zet `approved=1`, `status="approved"`, issues/refreshes shared token.
- **POST `/api/queue-config`**: UI “Send to Device”; schrijft JSON-config in `device_configs`; agent haalt op via `/config`.

### 2.3 Security Model
- **Shared token**: configurable in UI, vereist voor `/config` en gevoelige calls; agent kan automatisch herstellen via `/token/current`.
- **SSH aannames**: controller voert geen SSH-validatie uit; agent checkt en rapporteert `ssh_enabled`; UI toont Approve alleen wanneer `status="waiting"` en `ssh_enabled=1`.

### 2.4 Agent Update System
- Policies: `off`, `per_device`, `force_on`.
- Settings: update-URL, minimum vereiste versie.
- Endpoint: `/api/agent-update/settings`.
- Agent checkt periodiek policy en update indien nodig.

## 3. Web UI Architecture
### 3.1 Layout
- Sidebar: Dashboard/Clients; Devices (Routers, APs, Switches, Firewalls); Settings (System, WiFi, Tokens, Agent Updates); optioneel AI Integration (bij enabled).

### 3.2 Device Discovery & Approval Flow
- Lijst toont hostname/IP/MAC, type, SSH-status, approval state, agentversie.
- Approval vereist `ssh_enabled=1` en device type ≠ `unknown`.

### 3.3 Router UI (`router.html`)
- Tabs: Live, Firewall, DHCP, Apps, Logs, Advanced (layout minimaal houden).
- Features: firewallprofiel-selectie; security log display; app management (adblock, banIP); live clients list.

### 3.4 Access Point UI (`access_point.html`)
- WiFi-config velden: hostname, SSID + wachtwoord, roaming (802.11r/k/v), landcode, kanaal + `htmode`, TX power, optioneel statisch IP (ip/gateway/dns). Waarden gaan via `/config` naar agent.

### 3.5 Settings → WiFi (Roadmap)
- Global SSID; roaming domain (802.11r/k/v); automatische provisioning van nieuwe APs; multi-band coördinatie (2.4 + 5 GHz).

## 4. Agent Architecture (OpenWrt)
### 4.1 Installation & Files
- Script: `/usr/bin/wiretide-agent-run`; service: `/etc/init.d/wiretide`.
- Controller-URL niet hardcoded; zelfde structuur voor `main` en `beta`.

### 4.2 Agent Responsibilities
- **Registratie & status**: stuurt SSH-blok, agentversie, device-details; periodieke `/status` met firewallstaat, security log samples, LAN clients, DNS/NTP status.
- **SSH detection**: detectie via `ss`, `netstat`, `/proc`; bepaalt `ssh_enabled` en optioneel `ssh_fingerprint`.
- **Firewallprofielen**: `default`, `strict`, `stealth`, `custom`; toegepast via UCI.
- **Security logging**: drop/accept events, WiFi assoc/auth attempts, SSH failures; samples in `/status`.
- **App management**: kan `adblock`, `banIP` installeren en rapporteert status.
- **Config pull**: periodieke `/config`, past firewallprofiel, WiFi settings, app toggles, advanced settings toe.
- **Token handling**: shared token mee; bij 403 → `/token/current`.
- **Update mechanisme**: pull-based; leest controllerpolicy, downloadt update indien vereist, past veilig toe.

## 5. Data Model
- **devices**: id, hostname, IP/MAC, device_type, approved, status, ssh_enabled, ssh_fingerprint, agent_version, last_seen.
- **device_status**: firewall_profile_active, dns, ntp, security_log_samples, clients (LAN), updated_at.
- **settings**: shared_token, agent update policy, update URL, min vereiste agentversie, WiFi-domain settings (planned), AI Integration toggle, Security Monitoring API enabled.
- **device_configs**: queued config JSON voor delivery via `/config`.
- **security_events** (optioneel): parsed/enriched firewall + WiFi events (timestamp, device_id, type, src/dest, severity, tags, raw line); alleen bij ingeschakelde Monitoring API.

## 6. Optional Module: AI Security Monitoring API
- **Status**: opt-in, disabled by default (Settings → System → AI Integration). Disabled → alle `/api/security/*` endpoints return 404/403; geen events opgeslagen; geen overhead.

### 6.1 Purpose
- Biedt AI firewall events, verdachte WiFi attempts, samenvattingen/trends en high-level action requests (firewallprofiel wijziging, client block). Acties verlopen via normale config pipeline.

### 6.2 Authentication
- Dedicated API token: `Authorization: Bearer <AI_API_TOKEN>`. Beperkte permissies.

### 6.3 Event Model (uniform JSON)
```json
{
  "id": "evt_2025_000123",
  "device_id": 42,
  "device_name": "edge-router",
  "time": "2025-12-04T12:34:56Z",
  "type": "firewall_drop",
  "severity": "medium",
  "src_ip": "203.0.113.5",
  "src_port": 445,
  "dest_ip": "192.168.1.10",
  "dest_port": 445,
  "protocol": "tcp",
  "interface": "wan",
  "ssid": "HomeWiFi",
  "client_mac": "AA:BB:CC:DD:EE:FF",
  "message": "DROP TCP ...",
  "tags": ["scan", "bruteforce"]
}
```

### 6.4 Endpoints
- **GET `/api/security/events`**: filters `device_id`, `type`, `severity`, `since`, `limit`, `offset`; returns `{ events, total, limit, offset }`.
- **GET `/api/security/summary`**: aggregated counters, suspicious clients, notes.
- **GET `/api/security/wifi-attempts`**: aggregated authentication successes/failures.
- **POST `/api/security/actions/block-client`**: queued firewall rule/WiFi MAC block via device config.
  ```json
  { "device_id": 42, "client_mac": "AA:BB:CC:DD:EE:FF", "duration": "1h", "reason": "Suspected brute-force" }
  ```
- **POST `/api/security/actions/set-firewall-profile`**: queued firewallprofiel update.
  ```json
  { "device_id": 42, "profile": "strict", "reason": "Port scan detected" }
  ```

## 7. Future Roadmap
- WiFi roaming domain (multi-AP).
- Grafische netwerk topologie.
- Real-time log streaming (WebSockets).
- Per-device secret/HMAC tokens.
- Uitgebreide AP- en switch-templates.
- Verdere AI-analyse (ML anomaly detection).

## 8. High-Level Flows
- **Registratie**: agent → `/register`; controller slaat waiting op → admin approve → agent haalt shared token → normaal pollen.
- **Config**: admin triggert `/api/queue-config` → agent pollt `/config` → past change toe → rapporteert via `/status`.
- **AI Monitoring (optioneel)**: agent stuurt log samples via `/status`; controller parseert → `security_events`; AI pollt `/api/security/events|summary`; AI kan `/api/security/actions/*` aanroepen; controller queue’t config → agent past toe.

## 9. Design Philosophy
- Security first; voorspelbaar en eenvoudig.
- Agent verifieert, controller orkestreert.
- Minimale overhead.
- Uitbreidbaar via optionele modules (bijv. AI Integration).

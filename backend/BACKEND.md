# Wiretide Backend

(Functioneel + technisch overzicht)

De Wiretide backend is het centrale coördinatiepunt van het platform: een stateless HTTP API (FastAPI) voor UI, agents en externe integraties, met een configuratie- en statusdatabase, een renderinglaag (Jinja2-templates) voor de UI, een optionele Monitoring API voor AI-integratie, en een reverse-proxylaag via Nginx. Het systeem scheidt UI, agents en administratie strikt en vermijdt zware runtime-afhankelijkheden.

## Kernverantwoordelijkheden
- **Device inventory & lifecycle**: registratie, status, agentversies, SSH-fingerprintinformatie, typebeheer, approval/block/remove workflow.
- **Configuratie-orkestratie**: queue van configuraties, genereren van JSON-profielen per device type, uitserveren van `/config`-payloads, agent-updatebeleid (`off`/`per_device`/`force_on`).
- **Authenticatie & security**: shared-tokenvalidatie voor agents, admin login voor UI, per-device status-updates met tokenvalidatie, toekomstige HMAC-optie.
- **Monitoring & integratie (optioneel)**: event-ingest API voor firewall- en WiFi-events, aggregatie, AI-ontsluiting, in- of uitschakelbaar.
- **UI-rendering**: server-rendered HTML-pages (Jinja) voor settings, device-lijsten en detailpagina’s.

## Technische componenten
### FastAPI applicatie
- Routermodules:
  - `routes/ui.py` → HTML-templates.
  - `routes/devices.py` → device-API’s (approve, list, details, delete).
  - `routes/agent.py` → `/register`, `/status`, `/config`, `/token/current`.
  - `routes/settings.py` → shared token, agent update settings, WiFi-domain settings.
  - `routes/monitoring.py` (optioneel) → AI event ingest.
- JSON payloads tolereren form-data en pure JSON (agentversies gebruiken beide).
- Backend doet geen netwerk- of SSH-calls; response-snelheid staat centraal.

### Database (SQLite of PostgreSQL)
- Tabellen:
  - `devices`: id, hostname, description, device_type, status (waiting/approved/blocked), approved (bool), last_seen, ssh_enabled, ssh_fingerprint, agent_version, agent_update_allowed, ip_last (optioneel).
  - `device_status`: id, device_id (FK), dns_ok, ntp_ok, firewall_profile_active, security_log_samples (JSON), clients (JSON), updated_at.
  - `device_configs`: id, device_id, package (type config), package_json (JSON payload), sha256 (integriteitscontrole), created_at.
  - `settings`: shared_token, agent_update_policy, agent_update_url, agent_min_version, monitoring_api_enabled, wifi_domain_config (JSON, toekomst).
- Database-interacties verlopen via SQLModel/Pydantic-modellen.

### NGINX reverse proxy & TLS-certificaatbeheer
De backend wordt typisch achter Nginx geplaatst; backend (Uvicorn) draait intern zonder TLS (bijv. `127.0.0.1:9000`), Nginx verzorgt TLS-terminatie, routing, caching van statische assets en securityheaders.

#### Rol en security
- Reverse proxy voor `/` (UI), `/api/` (JSON), `/static/` (assets).
- TLS-terminatie met HSTS, CSP, X-Frame-Options, X-Content-Type-Options, Referrer-Policy; optioneel rate-limiting en IP-based admin controls.
- Statische assets direct geserveerd voor snelheid; cache-headers mogelijk.
- Onafhankelijke configuratielaag: Nginx-herloads zonder backend-restarts.

#### TLS-keuzes
- **Self-signed (default, interne deployments)**:
  - Certificaten in `/etc/nginx/ssl/wiretide.crt|.key`.
  - Minimale externe afhankelijkheden; geschikt voor off-grid omgevingen.
- **Publiek certificaat (Let’s Encrypt/commercieel)**:
  - Certbot voor HTTP-01 challenges; automatische vernieuwing.
  - Certpaden: `/etc/letsencrypt/live/.../fullchain.pem|privkey.pem`.
- **Interne CA/PKI**:
  - Certificaten via SCEP of interne CA; automatische rotatie mogelijk.
- TLS beschermt transport; authenticatie blijft via shared token.

#### Voorbeeldconfig
- Zie `backend/nginx/wiretide.conf.example` voor een HTTPS + static passthrough + proxy setup.
- Pas `server_name`, certificaatpaden en static pad (`/opt/wiretide/static/`) aan. Uvicorn draait bij voorkeur op `127.0.0.1:9000`; Nginx exposeert 80/443 en redirect HTTP → HTTPS.
- Als `/static` via Nginx een 403 geeft (home-permissies), verwijder de `/static` location en laat uvicorn de assets serveren, of verplaats assets naar een neutrale locatie met juiste alias.

#### Voorbeeldconfig (high level)
- HTTPS op 443 met HTTP/2, securityheaders, `/static` alias naar `/opt/wiretide/static/`.
- Proxy-pass naar `http://127.0.0.1:9000` voor UI en API.
- HTTP (80) redirect naar HTTPS.

#### Integratie met Uvicorn
- Typische start: `uvicorn wiretide.main:app --host 127.0.0.1 --port 9000 --workers 2`.
- Nginx verzorgt load distribution, logging/audit, buffering van grote JSON payloads en keep-alive voor efficiënte agent polling.
- Voor LAN-exposure zonder Nginx: start met `--host 0.0.0.0` (alle interfaces); voor productie blijft Nginx + TLS de voorkeur.

### Backendproces: intake & lifecycle
#### `/register`
- Agent meldt zich aan via `POST /register`.
- Backend valideert shared token, lookup device, maakt nieuw device met status `waiting` indien onbekend.
- Slaat `ssh_enabled`, agent_version, fingerprints en metadata op; response bevat status (`waiting`/`approved`).

#### `/status`
- Device stuurt DNS/NTP-status, firewallprofiel, clientinformatie, `ssh_enabled`, agent_version.
- Backend doet upsert naar `device_status`, refresht `last_seen`, werkt `ssh_enabled`/fingerprint bij. Response bevestigt succes; geen config.

#### `/config`
- Alleen geldig voor approved devices met geldige token.
- Backend zoekt pending config in `device_configs` en levert JSON-config terug:
  ```json
  {
    "package": "wiretide.firewall",
    "package_json": { ... },
    "sha256": "...hash..."
  }
  ```
- Geen pending config → “no config needed”.

#### `/api/devices/approve`
- UI gebruikt dit endpoint; controleert voorwaarden (type != `unknown`, `ssh_enabled=1`).
- Zet device op approved, genereert nieuwe shared token, initialiseert config-template per device type.

### Configuratie-orkestratie
- Backend genereert nooit directe shell-commando’s; UI schrijft gewijzigde settings, backend zet dit om in een configpayload (`device_configs`), agent haalt het op en past het lokaal toe.
- Houdt backend security-neutraal, auditbaar (DB bevat historiek) en schaalbaar (geen SSH).

### Securitymodel
- **Shared token (globale agent authenticatie)**:
  - Vereist voor `/register`, `/status`, `/config`.
  - UI kan token regenereren; agents herstellen via `/token/current`.
- **Per-device toetsing**:
  - Vertrouwt op geldige token, device-id, device status (waiting/approved/blocked).
  - Geen per-device certificaten, ruimte voor future HMAC.
- **Admin authenticatie**:
  - UI login (sessie-cookie), CSRF-bescherming voor POST-acties, admin-only routes voor CRUD.
- **Geen backend-SSH**:
  - Geen SSH-connecties naar devices i.v.m. security, schaalbaarheid en betrouwbaarheid; agent is bron van waarheid.

### Monitoring API (optioneel)
- Expliciet in/uit te schakelen via system settings.
- Endpoints:
  - `/monitoring/events/firewall`
  - `/monitoring/events/wifi`
  - `/monitoring/events/system`
- Functies: persistente opslag (event-tabel), API voor AI om events op te vragen, UI-secties zichtbaar zodra monitoring aan staat, volumebegrenzing/throttling (toekomst).

### NGINX of reverse-proxylaag (samenvatting)
- Aanbevolen pad: internet/LAN → Nginx → backend.
- Gzip + caching op statische assets; securityheaders; scheiding UI/API-kanalen.
- Backend draait doorgaans met `uvicorn main:app --host 127.0.0.1 --port 9000`; Nginx exposeert 80/443.

### Externe integratie (AI) via API
- Exposeert Monitoring API, device inventory API (read-only), firewall/WiFi eventstreams, event push endpoints.
- AI kan anomalies analyseren en beleid terugkoppelen via `/api/queue-config` (bijv. auto-firewall tightening).

### Backend fail-safe & operationeel gedrag
- Bij databasefouten → API retourneert 500 met duidelijke foutcode.
- `/status` calls worden geaccepteerd zolang token klopt, zelfs voor blocked devices.
- `/config` geeft nooit errors naar agent; error wordt gemarkeerd als “no config”.
- Consistent gebruik van timestamps voor auditing; geen blocking I/O of langlopende taken in request handlers.

### Samenvatting (executive)
De Wiretide backend is een veilige, stateless FastAPI-service met een persistente device-inventaris, een configuratie-queue, een centraal shared-token securitymodel en server-rendered UI-views. Agents leveren registraties, status en configuratieaanvragen aan; de backend levert alleen JSON-configuraties terug en voert geen SSH-operaties uit. Device approval en typevalidatie zijn verplicht voor toegang tot configuratie. Optioneel kan een Monitoring API worden geactiveerd om firewall- en WiFi-security events te verzamelen en door AI-systemen te laten verwerken.

### Auto-updater
- Agent pulled nieuwe versies van de backend; operator kan in de UI aangeven of dit per device of voor alle devices automatisch mag.
- Controller kan geüpdatet worden via `update.sh`; het script maakt eerst een backup van cruciale bestanden en start dan de automatische update.

Zie ook: `ARCHITECTURE.md`, `agent/WRTAGENT.md`, `installer/INSTALLER.md`, `UI/UI.md`, `AGENTS.md`.

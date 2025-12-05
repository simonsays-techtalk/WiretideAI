# Wiretide Controller Installer

(Installatie-, configuratie- en provisioninglaag voor de controlleromgeving)

De Wiretide Controller Installer is een geautomatiseerd setup-mechanisme dat een complete, veilige en production-ready Wiretide backendomgeving uitrolt. De installer zorgt dat alle vereiste componenten aanwezig zijn, backend en UI via Uvicorn draaien, Nginx is ingericht als reverse proxy met TLS, directories consistent zijn, database en initiële settings worden geprovisioned en updates eenvoudig door te voeren zijn. Doelplatform: Ubuntu/Debian (generiek genoeg voor vergelijkbare distro’s).

## Doelen
- Volledig autonoom een werkende Wiretide-installatie opleveren.
- Consistente mappenstructuur aanmaken:
  - `/opt/wiretide/` (codebase)
  - `/opt/wiretide/static/` (UI assets)
  - `/opt/wiretide/venv/` (Python virtual environment)
  - `/var/lib/wiretide/` (database, config storage)
  - `/etc/wiretide/` (configbestanden)
  - `/var/log/wiretide/` (controller logs)
- Backend-proces configureren via systemd service.
- Nginx configureren voor UI/API routing + HTTPS.
- TLS-certificaten genereren (self-signed) of importeren.
- Database migraties uitvoeren en initial shared token genereren.
- Updatepad faciliteren via `update.sh`.

## Installatieflow (hoog niveau)
1. Packages en dependencies installeren.
2. Wiretide codebase deployen.
3. Backend provisioning (Python, DB, settings).
4. Nginx + TLS-setup + systemd activatie.

## Script (install_wiretide.sh)
- Locatie: `installer/install_wiretide.sh`
- Flags:
  - `--dry-run` → toon acties, voer ze niet uit.
  - `--update` → maak een tar-backup van `/opt/wiretide` voordat je overschrijft.
  - `--cert-cn <cn>` → CN voor self-signed cert (default `wiretide.local`).
- Taken:
  - Maakt `wiretide` user/group, directories (`/opt/wiretide`, `/var/lib/wiretide`, `/etc/wiretide`, `/var/log/wiretide`).
  - Installeert packages (python3, venv, pip, nginx, sqlite3, curl).
  - Copiet backend naar `/opt/wiretide/backend`, zet venv op en installeert requirements.
  - Schrijft systemd unit (`/etc/systemd/system/wiretide.service`) en start/enable’t uvicorn op 127.0.0.1:9000.
  - Schrijft Nginx config (`/etc/nginx/sites-available/wiretide.conf`), maakt self-signed cert in `/etc/ssl/nginx/`, redirect HTTP→HTTPS en proxy’t naar uvicorn. `/static` gaat via uvicorn om permissie-issues te vermijden.
- Gebruik (voorbeeld):
  ```bash
  sudo installer/install_wiretide.sh --update --cert-cn wiretide.local
  ```

### Permissions & TLS
- Certs: standaard self-signed. Vervang door echte certs in `/etc/ssl/nginx/wiretide.crt|key`.
- Uvicon draait als user `wiretide`; directories worden ge-owned door `wiretide:wiretide`.
- Admin cookie `secure=true` in systemd unit (Nginx/TLS verwacht).

Installer is idempotent (`install_wiretide.sh`); herhalen is mogelijk zonder dubbele configuraties en maakt upgrades eenvoudig.

## Technische componenten
### Systeempakketten
- Installeert: `python3`, `python3-venv`, `python3-pip`, `nginx`, `sqlite3` (tenzij PostgreSQL gekozen), `curl`, `git`, `unzip`, `wget`, `openssl`, build tools.
- Voorafgaande checks op ontbrekende onderdelen.

### Code deployment
- Directory-structuur aanmaken of vernieuwen:
  - `/opt/wiretide/` → applicatiecode (beta of main branch).
  - `/opt/wiretide/venv/` → Python venv.
  - `/opt/wiretide/static/` → UI assets (css/js/images).
  - `/var/lib/wiretide/` → database & persistent settings.
  - `/etc/wiretide/` → configbestanden.
  - `/var/log/wiretide/` → controller logs.
- Branch-selectie: `main` (stable) of `beta` (dev); gedrag identiek, andere bron.

### Backend provisioning
- **Virtual environment + dependencies**:
  - Maakt venv in `/opt/wiretide/venv/`.
  - Installeert Python dependencies uit `requirements.txt` (optioneel integriteitscontrole via hash-lists).
- **Database-initialisatie**:
  - Maakt SQLite DB (`/var/lib/wiretide/wiretide.db`).
  - Voert SQLModel/Pydantic migraties uit.
  - Maakt basistabellen: `devices`, `device_status`, `device_configs`, `settings`.
  - Initialiseert settings-record met o.a. shared_token (random 32–64 chars), agent_update_policy, monitoring_api_enabled=false.
- **Static assets**:
  - UI-assets kopiëren naar `/opt/wiretide/static/`; minificatie waar relevant.

### TLS-certificaatbeheer
- Default: self-signed certificaat voor interne deployments:
  ```bash
  openssl req -x509 -newkey rsa:4096 \
    -keyout /etc/nginx/ssl/wiretide.key \
    -out /etc/nginx/ssl/wiretide.crt \
    -days 3650 -nodes \
    -subj "/CN=wiretide.local"
  ```
- Certificaten kunnen later worden vervangen door Let’s Encrypt of interne PKI.

### Nginx configuratie
- Plaatst `/etc/nginx/sites-available/wiretide.conf` en symlinkt naar `sites-enabled/`.
- Proxy naar backend: `http://127.0.0.1:9000`.
- `/static` direct geserveerd; HTTPS + HSTS + securityheaders; HTTP → HTTPS redirect; maximale header hardening.
- Reload & test: `nginx -t` en `systemctl reload nginx`.

### Systemd backend service
- Unit: `/etc/systemd/system/wiretide.service`
  ```ini
  [Unit]
  Description=Wiretide Controller Backend
  After=network.target

  [Service]
  User=wiretide
  Group=wiretide
  WorkingDirectory=/opt/wiretide
  ExecStart=/opt/wiretide/venv/bin/uvicorn wiretide.main:app --host 127.0.0.1 --port 9000 --workers 2
  Restart=always
  Environment=WIRETIDE_ENV=production
  Environment=DATABASE_PATH=/var/lib/wiretide/wiretide.db

  [Install]
  WantedBy=multi-user.target
  ```
- Registratie: `systemctl daemon-reload`, `systemctl enable wiretide`, `systemctl start wiretide`.

### Eerste-run provisioning
- Backend checkt DB bij eerste start; indien leeg → initial migration.
- Shared token wordt aangemaakt indien nog niet aanwezig.
- UI direct beschikbaar op `https://<host>`.
- Admin logt in, controleert devices, past configuraties aan (firewallprofielen, AP-domeinen, updatebeleid).

### Updatepad (`update.sh`)
- Script op `/opt/wiretide/update.sh`:
  - Download nieuwste versie van gekozen branch (main/beta).
  - Voert migraties uit.
  - Werkt static assets bij.
  - Voert systemd restart uit.
  - Behoudt config en DB.
- Agents worden nooit automatisch doorgedrukt; backend-agent-updateflow blijft optioneel afhankelijk van instellingen.

### Verwijderen of resetten
- Reset-optie:
  - Stopt systemd-unit.
  - Behoudt of reset database (optie in script).
  - Laat Nginx-config intact.
  - Vernieuwt codebase bij herinstallatie.
- Volledige verwijdering (niet standaard geautomatiseerd):
  - Directories, systemd-units, Nginx-bestanden en SSL-certificaten verwijderen.

## Samenvatting
De Wiretide Controller Installer is een betrouwbaar, idempotent installatiescript dat automatisch de volledige backendomgeving uitrolt. Het installeert alle systeemafhankelijkheden, maakt een Python-venv, initialiseert database en settings, zet Nginx op als reverse proxy met TLS, activeert een systemd backendservice en faciliteert updates via `update.sh`. Hierdoor is een nieuwe Wiretide-controller binnen minuten operationeel, met consistente configuraties, een veilige HTTPS-endpointstructuur en een robuuste runtime-omgeving.

Zie ook: `ARCHITECTURE.md`, `agent/WRTAGENT.md`, `backend/BACKEND.md`, `UI/UI.md`, `AGENTS.md`.

# Wiretide Agent

(Functioneel + technisch overzicht)

De Wiretide Agent is een lichtgewicht client voor elk OpenWrt-device dat door de Wiretide controller beheerd moet worden. De agent is ontworpen voor maximale betrouwbaarheid (geen zware runtimes), maximale veiligheid (whitelisting van controller, hash-validatie, firewall-profielen), minimale footprint (shell + busybox + enkele JSON-tools), en een pull-based configuratiemodel (agent vraagt actief om configuratie; controller pusht nooit). De agent draait als een permanent procd-managed service (`/etc/init.d/wiretide`) en rapporteert zowel systeemstatus als netwerkbeveiligingsinformatie.

## Functies
- Registratie bij de controller (`/register`).
- Periodieke statusrapportage (`/status`).
- Configuratiepull (`/config`).
- Automatische token recovery (`/token/current`).
- Skeleton reference: `agent/agent-skeleton.sh` bevat register/status/config/token-loop met logging, token recovery, WiFi/DHCP-clients, apply-handlers en DRY_RUN-ondersteuning (log-only); HTTP fetchers ondersteunen `curl`/`wget`/`uclient-fetch` en TLS-opties via env (`CURL_OPTS`/`WGET_OPTS`), en opgehaalde tokens worden ook lokaal gecached (`STATE_DIR/shared_token`) na rotatie.
- Verwerking van securityprofielen (firewalltemplates).
- Installatie van apps (adblock, banIP).
- Lokale SSH-validatie en rapportage (`ssh_enabled`, fingerprint detectie).
- Security logging (suricata-lite, firewall events, authentication events).
- Doorgeven van clients achter het device (dynamische client discovery).
- Optionele update-module (afhankelijk van controllerinstellingen).

## Technische bouwstenen
- Shell-script(s) met primair bestand `/usr/bin/wiretide-agent-run`.
- Busybox utilities: `wget`, `ubus`, `uci`, `ss`, `logread`, `opkg`, `jsonfilter`.
- Procd init script: `/etc/init.d/wiretide` (zie `agent/init.d/wiretide`); wrapper entrypoint `agent/wiretide-agent-run`.
- Firewall-profieltemplates: `/etc/wiretide/firewall/...`.
- Debug logging: `/var/wiretide-debug.log`.
- Dry-run harness: `agent/dry-run.sh` met `agent/mock_backend.py` voor offline testen.
- Geen Python of externe dependencies; volledig self-contained.

## Communicatie met controller
### Endpoints
- `/register`: eerste aanmelding, levert status `waiting` of `approved`.
- `/status`: periodieke levenssignalen + securitystatus.
- `/config`: ophalen van pending configuraties.
- `/token/current`: ophalen van nieuw shared token bij `403`.

### Transport
- HTTP(S) via `wget`.
- TLS-validatie optioneel, afhankelijk van OpenWrt-build.
- Controller-URL nooit hardcoded; staat in `/etc/wiretide/agent.conf` en kan door de controller worden overschreven.
- Ingebouwde timeouts en retries, foutmeldingen in `/var/wiretide-debug.log`.

## Registratieproces (`register_once()`)
Bij eerste start of wanneer het device nog geen ID heeft:
- Agent verzamelt hostname en board-id/UCI hardware-info.
- Lokale SSH-bereikbaarheid (`ssh_enabled`) via checks:
  - Detectie: `which dropbear` of `which sshd`.
  - Poortcontrole via `ss -ltn`.
  - Optionele fingerprint:
    - Dropbear: hash van `/etc/dropbear/dropbear_rsa_host_key`.
    - OpenSSH: hash van `/etc/ssh/ssh_host_rsa_key.pub`.
- Stuurt JSON naar backend `/register`.
- Controller retourneert device-ID en status (`waiting` of `approved`).
- Agent slaat device-ID op in `/etc/wiretide/device_id` en gaat bij `waiting` door met interval-checks.
- Alle SSH-validatie gebeurt lokaal; controller ontvangt alleen de rapportage.

## Periodieke statusrapportage (`send_status()`)
Elke 20–60 seconden rapporteert de agent:
- `dns_ok` via `nslookup`.
- `ntp_ok` via `busybox ntpd -q` of tijdsdrift.
- Actief firewallprofiel (`uci get firewall.wiretide.profile`).
- Security log samples (laatste N regels uit `logread` met filters).
- Clients achter het device:
  - ARP entries (`ip neigh`).
  - DHCP leases (`/tmp/dhcp.leases`).
  - Hostnames indien bekend.
- `ssh_enabled` en fingerprint-update.
- `agent_version` (string).

Backend-reactie:
- Upsert van `device_status`.
- Bijwerken van `last_seen`.
- Mogelijke instructie voor approved devices om `/config` te poll'en.
- Geen configuraties worden hier verwerkt; alleen health reporting.

## Configuratiepull en verwerking (`check_for_config()`)
Agent vraagt bij elke interval (of bij status `approved`) de backend:
- `GET /config?device_id=<id>`

Indien backend een configuratie retourneert:
- Agent valideert SHA256-hash en JSON-structuur.
- Bepaalt het type package:
  - `wiretide.firewall`
  - `wiretide.apps`
  - `wiretide.ssid` (voor AP’s)
  - `wiretide.update` (agent update)
- Voert passende handler uit:
  - Firewall: toepassen iptables/nftables rules via UCI + reload.
  - Apps: `opkg update` + `opkg install <pkg>`.
  - WiFi/AP: aanpassen `/etc/config/wireless` + `wifi reload`.
  - Device update: download + signature/SHA-validatie + herstart service.
- Logt elke actie naar `/var/wiretide-debug.log`.
- Pull-model garandeert geen remote execution in backend en maakt rollback mogelijk bij invalidatie.

## Shared token en automatische herstelmechanismen
- Agent stuurt bij elke call de token mee.
- Bij ongeldige token → backend stuurt `403`.
- Agent vraagt direct `/token/current` zonder credentials:
  - Backend levert nieuwe token.
  - Agent slaat nieuwe token op en herprobeert de oorspronkelijke call.
- Voorkomt problemen bij tokenrotatie en massale foutcondities; minimaliseert handmatig ingrijpen.

## Firewallprofielen
- Ondersteunde standaardprofielen: `default`, `strict`, `stealth`, `custom` (door admin beheerd).
- Bij profielwissel:
  - Download + valideer JSON-template van backend.
  - Schrijf UCI-secties in `/etc/config/firewall`.
  - Reload firewall: `fw3 reload` of `service firewall restart` (OpenWrt afhankelijk).
  - Meld nieuw profiel terug via `/status`.
- Profielen kunnen aanvullende security-acties bevatten (WAN-management blokkeren, geforceerde DNS via DoT/DoH, rate-limits, logging).

## Security logging
- Verzamelt beveiligingsinformatie:
  - Firewall blocked packets.
  - DHCP/host-auth events.
  - Kernel security markers (`logread | grep`).
  - WiFi-auth failures (AP’s).
- Logverzameling wordt gedecimeerd tot kleine samples voor `/status`.
- Optioneel (Monitoring API ingeschakeld): volledige eventpayload naar monitoring-endpoints.

## Client discovery (achterliggend netwerk)
- Inventariseert:
  - ARP-tabel.
  - DHCP leases.
  - WiFi-associaties (`iwinfo assoclist` of `iw dev wlan0 station dump`) met iface/SSID/band.
- Clientinformatie wordt in JSON doorgegeven via `/status` en voedt UI-clients, securityanalyse en toekomstige roam-optimalisatie.

## Agent-update module
- Backend bepaalt beleid:
  - `off`: agent negeert update-instructies.
  - `per_device`: alleen specifieke devices mogen updaten.
  - `force_on`: alle devices moeten minimaal een bepaalde versie draaien.
- Bij update-config package:
  - Agent downloadt update-script (`url` in config).
  - Valideert optioneel `script_sha256`.
  - Slaat update over als `version` gelijk is aan huidige `agent_version`.
  - Voert update uit (downloaded script of `/usr/bin/wiretide-agent-update`), respecteert DRY_RUN=1 voor log-only.
  - Herstart dienst (handmatig/extern) en meldt nieuwe agentversie via `/status`.
- Voorkomt ongecontroleerde massaupdates.

## Procd integratie
- Init-script `/etc/init.d/wiretide`:
  - Definieert service en start `wiretide-agent-run` in loop.
  - Gebruikt respawn policy voor automatische herstart.
  - Integreert met enable/disable van OpenWrt.
- Houdt de agent systeemvriendelijk en consistent met andere OpenWrt-diensten.

## Lokale configuratiebestanden
- `/etc/wiretide/agent.conf` bevat:
  - `controller_url`
  - `shared_token`
  - `device_id` (na registratie)
  - `device_type` (hint), `agent_version`, `interval`, `dry_run`
  - Extra velden: wifi-domain membership, roam settings, debuglevel.
- `/var/wiretide-debug.log` bevat runtime logging, waaronder registratiefouten, config-validatie, installs, firewall reloads en update-flow.

## Samenvatting
De Wiretide Agent is een volledig self-contained, pull-based beheerclient voor OpenWrt. De agent registreert zichzelf bij de controller, rapporteert status, haalt configuraties op en past ze lokaal toe, valideert JSON- en SHA256 payloads, beheert firewallprofielen en securityapps, detecteert clients achter het device, en herstelt automatisch tokens bij 403-responses. De agent werkt zonder afhankelijkheden, via procd, en communiceert uitsluitend via de Wiretide backend-API’s: het device controleert zichzelf; de controller stuurt nooit shellopdrachten uit.

Zie ook: `ARCHITECTURE.md`, `backend/BACKEND.md`, `installer/INSTALLER.md`, `UI/UI.md`, `AGENTS.md`.

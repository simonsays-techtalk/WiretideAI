# Wiretide UI

(Functioneel overzicht)

De Wiretide UI is de beheerconsole voor alle OpenWrt-devices die door de controller worden aangestuurd. De UI is primair server-rendered HTML (Jinja/FastAPI templates) met zeer beperkte JavaScript voor formulieren, tabbladen en async-acties.

## Doelen en scope
- **Inventarisatie en lifecycle management**: overzicht van alle devices, goedkeuren/afwijzen van nieuwe devices, beheer van device-eigenschappen (type, hostname, omschrijving, labels).
- **Configuratie en orkestratie**: firewallprofielen en beveiligingsopties toekennen, extra packages installeren (adblock/banIP), configuraties pushen via backend `/config`-queue.
- **Monitoring en status**: inzicht in online/offline, laatst gezien, agentversie, device-status (DNS/NTP, actief firewallprofiel, security log samples, clients), optioneel security/monitoring events indien Monitoring API is ingeschakeld.

## Hoofdstructuur en navigatie
- Vaste layout:
  - Sidebar: Dashboard/Home (optioneel), Clients/Devices (centrale lijst), Settings (systeem/agent/veiligheid), (toekomst) Monitoring/Madison/WiFi-domain.
  - Contentgebied toont geselecteerde pagina; bovenbalk kan statusinfo/branding tonen.
- Geen SPA; elke pagina is server-rendered met eventueel kleine AJAX-calls.

## Devices / Clients
### Overzichtslijst
- Pagina `/devices` of `/clients`.
- Tabel met o.a. hostname, IP/laatste IP, device type (router/switch/firewall/access point/unknown), status (waiting/approved/offline/error), `ssh_enabled`, laatst gezien, agent-versie.
- Basisfilters (type, status, laatst gezien).
- Acties: View/Open (detail), Approve (alleen bij `status='waiting'` én `ssh_enabled=1`), toekomstig Decommission/Disable/Remove.

### Device detailpagina’s
- Varianten: `router.html` (router/firewall-achtige devices) en `access_point.html` (AP-specifiek), beide via `extends base.html` met tabs.

## Router detail UI (`router.html`)
### Tabstructuur
- Tabs: Live, Firewall, DHCP, Apps, Logs, Advanced (layout behouden; geen Tailwind-SPA-refactor zonder expliciete vraag).

### Live-tab
- Basisinformatie: hostname, IP, device type, beschrijving.
- Status, laatst gezien, agentversie, `ssh_enabled` + agent-aanmeldstatus.
- Security/statusinformatie uit `device_status`: DNS/NTP status, actief firewallprofiel, security log samples, samenvatting verbonden clients.

### Firewall-tab
- Selectie van firewallprofiel (`default`, `strict`, `stealth`, `custom`, toekomstige profielen).
- Korte toelichting per profiel.
- Formulier slaat keuze op via backend-endpoint en queue’t configuratie naar agent (`/api/queue-config` of vergelijkbaar).
- Visuele indicatie van actief profiel (zoals gerapporteerd door agent/device_status).

### DHCP-tab
- Huidig of toekomstig: subnet, range, lease-tijd, optioneel statische leases (MAC → IP), koppeling van clientinformatie aan DHCP-data.

### Apps-tab
- Schakelbare extra apps: `adblock`, `banip`, andere Wiretide-managed pakketten.
- UI: checkboxen/toggles per app + status (geïnstalleerd/running vs. niet).
- Acties: opslaan en configuratie pushen naar device via backend.

### Logs-tab
- Overzicht van security- en systeemlogs voor het device.
- Opties: laatste N logregels; later live tail via async endpoint.
- Filters op logtype (security/system/firewall).

### Advanced-tab
- Device-specifieke geavanceerde instellingen: handmatige overrides, debugopties, raw JSON-config bekijken of beperkt aanpassen.

## Access Point detail UI (`access_point.html`)
### Tabstructuur
- Tabs: Live, WiFi, Clients, Logs, Advanced (zelfde patroon als router).

### WiFi-tab
- Basis WiFi-instellingen:
  - Hostname.
  - SSID + wachtwoord (masker in UI, aparte actie tonen/wijzigen).
  - Landcode (regulatoir kanaalbeleid).
- Roaming-instellingen:
  - 802.11r / 11k / 11v aan/uit.
  - Domain/mobility domain ID (voor 11r).
- Radio/frequentie:
  - Kanaal (2.4/5 GHz).
  - `htmode` (20/40/80 MHz e.d.).
  - `txpower`.
- Netwerk:
  - DHCP of statisch IP; bij statisch: IP, gateway, DNS.
- UI levert deze waarden als één consistente configuratie aan backend; backend pusht naar agent.

### Clients-tab
- Overzicht verbonden WiFi-clients: MAC, hostname (indien bekend), IP, signaalsterkte/kwaliteit (indien gerapporteerd).
- Basisfilters (2.4/5 GHz, per SSID).

## Settings UI
### System / Security settings
- Shared token voor agents: tonen (gemaskeerd), regenereren, waarschuwing over impact (agents moeten token ophalen via `/token/current`).
- Algemene systeeminstellingen: controller-naam, host/URL, locale/timezone (optioneel).

### Agent update policy
- Instellingen: mode (`off`, `per_device`, `force_on`), update URL (basis voor `wget` door agent), minimum vereiste agentversie.
- UI: radio/select voor policy, inputvelden voor URL en minimumversie.
- Backend: UI schrijft naar `/api/agent-update/settings`; devices zien via `/config` of ze moeten updaten.

### Monitoring / Madison integratie (optioneel)
- Schakelaar “Monitoring API enabled”.
- Endpoint/API-key configuratie richting Madison.
- UI toont alleen monitoring-/AI-onderdelen als Monitoring API in backend is ingeschakeld.

## Intakeproces (“binnelaten van nieuwe devices”)
Wiretide hanteert een strikt intakeproces met vier fases: (1) eerste aanmelding, (2) pending/waiting, (3) type-selectie + approval, (4) block/remove.

### Fase 1 — Eerste aanmelding
- Agent → `POST /register` met shared token, hostname, description (optioneel), serienummer/board-id, SSH-status (`ssh_enabled`, optional fingerprint + server type), agentversie, runtime status (IPv4/IPv6, uptime).
- Backend: valideert token; mismatch → 403 (agent haalt nieuwe token via `/token/current`); device lookup; nieuw device krijgt status `waiting`.
- Controller registreert first contact, SSH-bereikbaarheid, fingerprint, laatste agentversie. Controller test geen SSH zelf.

### Fase 2 — Waiting for Approval
- UI-sectie “New device pending approval”; status `waiting`.
- Approve-knop alleen zichtbaar bij `ssh_enabled=1`; anders waarschuwing “Device not reachable via SSH — approval blocked.”
- Device Type is verplicht (router/switch/firewall/access_point/unknown). Approval onmogelijk zolang type `unknown` is.

### Fase 3 — Type-selectie + Approval
- Voorwaarden: geldig device type + `ssh_enabled=1` + expliciete Approve.
- Backend (`POST /api/devices/approve`): zet `approved=1`, `status='approved'`, slaat definitief device type op, voert token-reset uit (niet uniek per device, wel standaard Wiretide tokenrefresh), zet pending configuraties klaar (type-afhankelijk; bijv. WiFi defaults voor AP’s, firewallprofiel default/custom).
- Device verhuist naar Approved Devices; type-specifieke functies worden zichtbaar (router-tabs of AP-tabs).

### Alternatief: Block
- Knop “Block Device”.
- Backend: `status=blocked`, `approved=0`; geen configuraties; `/status` wordt nog aangenomen maar controller reageert nooit met config.
- Use case: ongewenste devices, PoC/test buiten productie.

### Alternatief: Remove
- Knop “Remove”.
- Backend: record + `device_status` + `device_configs` worden gewist; device moet opnieuw `/register` doen om terug te komen.
- UI: device verdwijnt volledig.
- Use case: defecte devices vervangen, tests opruimen, inventaris opschonen.

### Samenvattende tabel
- **Registratie** → status `waiting`, device verschijnt voor het eerst.
- **Pending** → status `waiting`, type kiezen vereist voor approval.
- **Approval** → status `approved`, device krijgt volledige functionaliteit.
- **Block** → status `blocked`, device geweigerd (geen config).
- **Remove** → device verwijderd; herregistratie nodig.

### Veiligheidsprincipes
- Aanmelden vereist valide shared token (anders 403).
- Controller vertrouwt nooit automatisch een device zonder SSH-bevestiging.
- Geen automatische approval; menselijke validatie is verplicht.
- Device type bepaalt welke controller-functies worden ontsloten (voorkomt verkeerde configuraties).
- Blocked devices blijven zichtbaar voor auditdoeleinden; Remove verwijdert volledig voor schone herregistratie.

Zie ook: `ARCHITECTURE.md`, `agent/WRTAGENT.md`, `backend/BACKEND.md`, `installer/INSTALLER.md`, `AGENTS.md`.

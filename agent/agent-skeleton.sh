#!/bin/sh
# Wiretide Agent (skeleton)
# Reference shell for OpenWrt agents. Not production-ready: fill in apply_* handlers.

set -eu

# Config + state defaults (overridable via env or config file).
CONFIG_FILE="${CONFIG_FILE:-/etc/wiretide/agent.conf}"
state_dir="${STATE_DIR:-/tmp/wiretide}"
LOG_FILE="${LOG_FILE:-/var/wiretide-debug.log}"
device_id_file="$state_dir/device_id"
interval="${INTERVAL:-30}"
http_timeout="${HTTP_TIMEOUT:-10}"
http_tries="${HTTP_TRIES:-2}"
controller_host=""

controller_url="${CONTROLLER_URL:-}"
shared_token="${SHARED_TOKEN:-}"
device_id="${DEVICE_ID:-}"
device_type="${DEVICE_TYPE:-unknown}"
description="${DESCRIPTION:-}"
agent_version="${AGENT_VERSION:-}"
dry_run="${DRY_RUN:-0}"
controller_host=""
uci_commit="${UCI_COMMIT:-1}"
wifi_reload_cmd="${WIFI_RELOAD_CMD:-wifi reload}"
firewall_reload_cmd="${FIREWALL_RELOAD_CMD:-/etc/init.d/firewall reload}"
opkg_update_cmd="${OPKG_UPDATE_CMD:-opkg update}"
opkg_install_cmd="${OPKG_INSTALL_CMD:-opkg install}"
download_cmd="${DOWNLOAD_CMD:-wget -qO-}"
update_script_path="${UPDATE_SCRIPT_PATH:-/tmp/wiretide-agent-update.sh}"

log() {
  ts="$(date -Iseconds)"
  # Avoid breaking if the log path is unwritable.
  printf "%s %s\n" "$ts" "$*" >>"$LOG_FILE" 2>/dev/null || true
}

load_config() {
  [ -f "$CONFIG_FILE" ] && . "$CONFIG_FILE"
  controller_url="${CONTROLLER_URL:-${controller_url:-}}"
  shared_token="${SHARED_TOKEN:-${shared_token:-}}"
  device_id="${DEVICE_ID:-${device_id:-}}"
  device_type="${DEVICE_TYPE:-${device_type:-unknown}}"
  description="${DESCRIPTION:-${description:-}}"
  agent_version="${AGENT_VERSION:-${agent_version:-}}"
  interval="${INTERVAL:-${interval:-30}}"
  state_dir="${STATE_DIR:-${state_dir:-/tmp/wiretide}}"
  log_path="${LOG_FILE:-/var/wiretide-debug.log}"
  LOG_FILE="$log_path"
  http_timeout="${HTTP_TIMEOUT:-${http_timeout:-10}}"
  http_tries="${HTTP_TRIES:-${http_tries:-2}}"
  dry_run="${DRY_RUN:-${dry_run:-0}}"
  uci_commit="${UCI_COMMIT:-${uci_commit:-1}}"
  wifi_reload_cmd="${WIFI_RELOAD_CMD:-${wifi_reload_cmd:-wifi reload}}"
  firewall_reload_cmd="${FIREWALL_RELOAD_CMD:-${firewall_reload_cmd:-/etc/init.d/firewall reload}}"
  opkg_update_cmd="${OPKG_UPDATE_CMD:-${opkg_update_cmd:-opkg update}}"
  opkg_install_cmd="${OPKG_INSTALL_CMD:-${opkg_install_cmd:-opkg install}}"
  download_cmd="${DOWNLOAD_CMD:-${download_cmd:-wget -qO-}}"
  update_script_path="${UPDATE_SCRIPT_PATH:-${update_script_path:-/tmp/wiretide-agent-update.sh}}"
  device_id_file="$state_dir/device_id"
  mkdir -p "$state_dir"
  [ -f "$device_id_file" ] && device_id="$(cat "$device_id_file" 2>/dev/null || true)"
  controller_host="$(echo "$controller_url" | sed -E 's|https?://||; s|/.*||; s|:.*||')"
}

require_settings() {
  case "$controller_url" in
    http://*|https://*) ;;
    *) echo "controller_url missing/invalid; set CONTROLLER_URL or controller_url in $CONFIG_FILE" >&2
       log "controller_url missing/invalid"
       exit 1 ;;
  esac
  if [ -z "$shared_token" ]; then
    echo "Shared token not set; export SHARED_TOKEN or set shared_token in $CONFIG_FILE" >&2
    log "Shared token missing"
    exit 1
  fi
}

save_device_id() {
  echo "$device_id" >"$device_id_file"
}

http_post_json() {
  path="$1"; data="$2"
  wget -qO- \
    --tries="$http_tries" \
    --timeout="$http_timeout" \
    --header="Content-Type: application/json" \
    --header="X-Shared-Token: $shared_token" \
    --post-data="$data" \
    "$controller_url/$path" 2>/dev/null || true
}

http_get() {
  path="$1"
  wget -qO- \
    --tries="$http_tries" \
    --timeout="$http_timeout" \
    --header="X-Shared-Token: $shared_token" \
    "$controller_url/$path" 2>/dev/null || true
}

http_get_public() {
  path="$1"
  wget -qO- \
    --tries="$http_tries" \
    --timeout="$http_timeout" \
    "$controller_url/$path" 2>/dev/null || true
}

recover_token() {
  new_token="$(http_get_public "token/current" | jsonfilter -e '@.shared_token' 2>/dev/null || true)"
  if [ -n "$new_token" ]; then
    shared_token="$new_token"
    log "Recovered shared token"
  else
    log "Token recovery failed"
  fi
}

handle_auth_errors() {
  resp="$1"
  echo "$resp" | grep -q '"detail":"Invalid shared token"' && { recover_token; return 1; }
  echo "$resp" | grep -q '"detail":"Missing shared token"' && { recover_token; return 1; }
  return 0
}

get_hostname_safe() {
  for cmd in "hostname" "/bin/hostname" "/usr/bin/hostname" "busybox hostname" "/bin/busybox hostname" "/usr/bin/busybox hostname"; do
    bin="${cmd%% *}"
    command -v "$bin" >/dev/null 2>&1 || continue
    name="$(sh -c "$cmd" 2>/dev/null || true)"
    [ -n "$name" ] && { echo "$name"; return; }
  done
  if [ -f /proc/sys/kernel/hostname ]; then
    name="$(cat /proc/sys/kernel/hostname 2>/dev/null || true)"
    [ -n "$name" ] && { echo "$name"; return; }
  fi
  echo "wiretide-device"
}

detect_ssh_enabled() {
  # Basic detection: check listeners and binaries.
  if command -v ss >/dev/null 2>&1 && ss -ltn 2>/dev/null | grep -q ':22 '; then
    echo "true"; return
  fi
  if command -v netstat >/dev/null 2>&1 && netstat -ltn 2>/dev/null | grep -q ':22 '; then
    echo "true"; return
  fi
  if command -v dropbear >/dev/null 2>&1 || command -v sshd >/dev/null 2>&1; then
    echo "true"; return
  fi
  echo "false"
}

probe_dns_ok() {
  command -v nslookup >/dev/null 2>&1 || { echo ""; return; }
  target="${controller_host:-openwrt.lan}"
  if nslookup "$target" >/dev/null 2>&1; then
    echo "true"
  else
    echo "false"
  fi
}

probe_ntp_ok() {
  if command -v ubus >/dev/null 2>&1; then
    synced="$(ubus call system ntpstate 2>/dev/null | jsonfilter -e '@.synced' 2>/dev/null || true)"
    [ -n "$synced" ] && echo "$synced" && return
  fi
  echo ""
}

current_firewall_profile() {
  command -v uci >/dev/null 2>&1 || { echo ""; return; }
  uci -q get firewall.wiretide.profile 2>/dev/null || true
}

sample_clients() {
  leases_file="/tmp/dhcp.leases"
  clients=""
  [ -f "$leases_file" ] || { echo "[]"; return; }
  while read -r _ts mac ip host _id; do
    [ -n "$ip" ] || continue
    h="${host:-unknown}"
    entry="{\"ip\":\"$(json_escape "$ip")\",\"mac\":\"$(json_escape "$mac")\",\"host\":\"$(json_escape "$h")\"}"
    if [ -z "$clients" ]; then
      clients="$entry"
    else
      clients="$clients,$entry"
    fi
  done <"$leases_file"
  [ -n "$clients" ] && echo "[$clients]" || echo "[]"
}

json_escape() {
  echo "$1" | sed 's/\\/\\\\/g; s/"/\\"/g'
}

sample_wifi_clients() {
  # Returns JSON array of wifi stations (mac, iface, ssid, band)
  command -v iw >/dev/null 2>&1 || command -v iwinfo >/dev/null 2>&1 || { echo "[]"; return; }
  wifi_clients=""
  for iface in $(iw dev 2>/dev/null | awk '/Interface/ {print $2}'); do
    ssid=""
    band=""
    if command -v iwinfo >/dev/null 2>&1; then
      ssid="$(iwinfo "$iface" info 2>/dev/null | awk -F': ' '/ESSID/ {gsub(/"/,"",$2); print $2; exit}')"
      chan="$(iwinfo "$iface" info 2>/dev/null | awk -F'[ (]' '/Channel/ {print $2; exit}')"
      case "$chan" in
        '' ) band="";;
        [0-9]|1[0-4]) band="2g";;
        *) band="5g";;
      esac
    fi
    if command -v iwinfo >/dev/null 2>&1; then
      assoc_list="$(iwinfo "$iface" assoclist 2>/dev/null | awk '/^[0-9A-Fa-f][0-9A-Fa-f]:/ {print $1}')"
    else
      assoc_list="$(iw dev "$iface" station dump 2>/dev/null | awk '/Station/ {print $2}')"
    fi
    for mac in $assoc_list; do
      entry="{\"mac\":\"$(json_escape "$mac")\",\"iface\":\"$(json_escape "$iface")\""
      [ -n "$ssid" ] && entry="$entry,\"ssid\":\"$(json_escape "$ssid")\""
      [ -n "$band" ] && entry="$entry,\"band\":\"$band\""
      entry="$entry}"
      if [ -z "$wifi_clients" ]; then
        wifi_clients="$entry"
      else
        wifi_clients="$wifi_clients,$entry"
      fi
    done
  done
  [ -n "$wifi_clients" ] && echo "[$wifi_clients]" || echo "[]"
}

merge_json_arrays() {
  a="$1"; b="$2"
  if command -v jq >/dev/null 2>&1; then
    printf '%s\n%s\n' "$a" "$b" | jq -s 'add' 2>/dev/null
    return
  fi
  a_stripped="${a#[}"; a_stripped="${a_stripped%]}"
  b_stripped="${b#[}"; b_stripped="${b_stripped%]}"
  combined="$a_stripped"
  [ -n "$a_stripped" ] && [ -n "$b_stripped" ] && combined="$combined,$b_stripped"
  [ -z "$a_stripped" ] && combined="$b_stripped"
  echo "[$combined]"
}

build_status_payload() {
  dns_ok="$(probe_dns_ok)"; ntp_ok="$(probe_ntp_ok)"; fw_prof="$(current_firewall_profile)"
  ssh_enabled="$(detect_ssh_enabled)"
  dhcp_clients="$(sample_clients)"
  wifi_clients="$(sample_wifi_clients)"
  clients_json="$(merge_json_arrays "$dhcp_clients" "$wifi_clients")"
  payload="\"device_id\":$device_id"
  [ -n "$dns_ok" ] && payload="$payload,\"dns_ok\":$dns_ok"
  [ -n "$ntp_ok" ] && payload="$payload,\"ntp_ok\":$ntp_ok"
  [ -n "$fw_prof" ] && payload="$payload,\"firewall_profile_active\":\"$(json_escape "$fw_prof")\""
  payload="$payload,\"ssh_enabled\":$ssh_enabled"
  [ -n "$agent_version" ] && payload="$payload,\"agent_version\":\"$(json_escape "$agent_version")\""
  [ "$clients_json" != "[]" ] && payload="$payload,\"clients\":$clients_json"
  printf "{%s}" "$payload"
}

register_once() {
  [ -n "$device_id" ] && return 0
  ssh_enabled="$(detect_ssh_enabled)"
  host="$(get_hostname_safe)"
  payload="{\"hostname\":\"$host\",\"device_type\":\"$device_type\",\"ssh_enabled\":$ssh_enabled,\"description\":\"$description\",\"agent_version\":\"$agent_version\"}"
  resp="$(http_post_json "register" "$payload")"
  handle_auth_errors "$resp" || return
  device_id="$(echo "$resp" | jsonfilter -e '@.device_id' 2>/dev/null || true)"
  if [ -n "$device_id" ]; then
    save_device_id
    log "Registered device_id=$device_id status=$(echo "$resp" | jsonfilter -e '@.status' 2>/dev/null || true)"
  else
    log "Register failed, resp=$resp"
  fi
}

send_status() {
  [ -z "$device_id" ] && return 0
  payload="$(build_status_payload)"
  resp="$(http_post_json "status" "$payload")"
  handle_auth_errors "$resp" || return
}

canonicalize_json() {
  raw="$1"
  if command -v jq >/dev/null 2>&1; then
    echo "$raw" | jq -c -S . 2>/dev/null || echo "$raw"
  else
    echo "$raw"
  fi
}

validate_nonempty_json() {
  raw="$1"
  [ -z "$raw" ] && return 1
  if command -v jq >/dev/null 2>&1; then
    jq -e . >/dev/null 2>&1 <<EOF
$raw
EOF
    return $?
  fi
  return 0
}

apply_firewall_config() {
  json="$1"
  validate_nonempty_json "$json" || { log "Invalid firewall config JSON"; return; }
  profile="$(echo "$json" | jsonfilter -e '@.profile' 2>/dev/null || true)"
  [ -z "$profile" ] && { log "Missing firewall profile"; return; }
  [ "$dry_run" = "1" ] && { log "DRY_RUN: skip firewall apply profile=$profile"; return; }
  command -v uci >/dev/null 2>&1 || { log "uci not available; skip firewall apply"; return; }
  log "Apply firewall profile=$profile"
  uci -q set firewall.wiretide=defaults || true
  uci -q set firewall.wiretide.profile="$profile" || true
  if [ "$uci_commit" = "1" ]; then
    uci -q commit firewall || log "uci commit firewall failed"
  fi
  sh -c "$firewall_reload_cmd" >/dev/null 2>&1 || log "firewall reload failed"
}

apply_apps_config() {
  json="$1"
  validate_nonempty_json "$json" || { log "Invalid apps config JSON"; return; }
  adblock="$(echo "$json" | jsonfilter -e '@.adblock_enabled' 2>/dev/null || true)"
  banip="$(echo "$json" | jsonfilter -e '@.banip_enabled' 2>/dev/null || true)"
  [ "$dry_run" = "1" ] && { log "DRY_RUN: skip apps apply adblock=$adblock banip=$banip"; return; }
  command -v opkg >/dev/null 2>&1 || { log "opkg not available; skip apps apply"; return; }
  sh -c "$opkg_update_cmd" >/dev/null 2>&1 || log "opkg update failed"
  if [ "$adblock" = "true" ]; then
    sh -c "$opkg_install_cmd adblock" >/dev/null 2>&1 || log "install adblock failed"
  fi
  if [ "$banip" = "true" ]; then
    sh -c "$opkg_install_cmd banip" >/dev/null 2>&1 || log "install banip failed"
  fi
  log "Apply apps adblock=$adblock banip=$banip"
}

apply_wifi_config() {
  json="$1"
  validate_nonempty_json "$json" || { log "Invalid wifi config JSON"; return; }
  ssid="$(echo "$json" | jsonfilter -e '@.ssid' 2>/dev/null || true)"
  band="$(echo "$json" | jsonfilter -e '@.band' 2>/dev/null || true)"
  [ "$dry_run" = "1" ] && { log "DRY_RUN: skip wifi apply ssid=$ssid band=$band"; return; }
  command -v uci >/dev/null 2>&1 || { log "uci not available; skip wifi apply"; return; }
  [ -z "$ssid" ] && { log "wifi config missing ssid"; return; }
  section="wireless.wiretide"
  uci -q set "$section"=wifi-iface || true
  uci -q set "$section".ssid="$ssid" || true
  [ -n "$band" ] && uci -q set "$section".band="$band" || true
  psk="$(echo "$json" | jsonfilter -e '@.password' 2>/dev/null || true)"
  [ -n "$psk" ] && uci -q set "$section".key="$psk" || true
  channel="$(echo "$json" | jsonfilter -e '@.channel' 2>/dev/null || true)"
  [ -n "$channel" ] && uci -q set "$section".channel="$channel" || true
  htmode="$(echo "$json" | jsonfilter -e '@.htmode' 2>/dev/null || true)"
  [ -n "$htmode" ] && uci -q set "$section".htmode="$htmode" || true
  country="$(echo "$json" | jsonfilter -e '@.country' 2>/dev/null || true)"
  [ -n "$country" ] && uci -q set "$section".country="$country" || true
  txpower="$(echo "$json" | jsonfilter -e '@.txpower' 2>/dev/null || true)"
  [ -n "$txpower" ] && uci -q set "$section".txpower="$txpower" || true
  if [ "$uci_commit" = "1" ]; then
    uci -q commit wireless || log "uci commit wireless failed"
  fi
  sh -c "$wifi_reload_cmd" >/dev/null 2>&1 || log "wifi reload failed"
  log "Apply wifi ssid=$ssid band=$band"
}

apply_update_config() {
  json="$1"
  validate_nonempty_json "$json" || { log "Invalid update config JSON"; return; }
  url="$(echo "$json" | jsonfilter -e '@.url' 2>/dev/null || true)"
  ver="$(echo "$json" | jsonfilter -e '@.version' 2>/dev/null || true)"
  [ "$dry_run" = "1" ] && { log "DRY_RUN: skip update apply url=$url version=$ver"; return; }
  [ -z "$url" ] && { log "Update missing url"; return; }
  if [ -n "$ver" ] && [ -n "$agent_version" ] && [ "$agent_version" = "$ver" ]; then
    log "Update version $ver matches current; skip"
    return
  fi
  script_sha="$(echo "$json" | jsonfilter -e '@.script_sha256' 2>/dev/null || true)"
  dl_path="$update_script_path"
  sh -c "$download_cmd '$url'" >"$dl_path" 2>/dev/null || { log "download update failed"; return; }
  if [ -n "$script_sha" ] && command -v sha256sum >/dev/null 2>&1; then
    calc="$(sha256sum "$dl_path" | awk '{print $1}')"
    if [ "$calc" != "$script_sha" ]; then
      log "update sha mismatch expected=$script_sha got=$calc"
      return
    fi
  fi
  chmod +x "$dl_path" || true
  sh "$dl_path" >/dev/null 2>&1 || log "update script failed"
  log "Apply update url=$url version=$ver"
}

apply_config() {
  pkg="$1"; json="$2"
  case "$pkg" in
    wiretide.firewall) apply_firewall_config "$json";;
    wiretide.apps) apply_apps_config "$json";;
    wiretide.ssid) apply_wifi_config "$json";;
    wiretide.update) apply_update_config "$json";;
    *) log "Unknown package $pkg";;
  esac
}

fetch_config() {
  [ -z "$device_id" ] && return 0
  cfg="$(http_get "config?device_id=$device_id")"
  handle_auth_errors "$cfg" || return
  echo "$cfg" | grep -q '"detail":"Device not approved"' && { log "Device not approved"; return; }
  echo "$cfg" | grep -q '"detail":"No pending config"' && return
  echo "$cfg" | grep -q '"package"' || return
  pkg="$(echo "$cfg" | jsonfilter -e '@.package' 2>/dev/null || true)"
  sha="$(echo "$cfg" | jsonfilter -e '@.sha256' 2>/dev/null || true)"
  body="$(echo "$cfg" | jsonfilter -e '@.package_json' 2>/dev/null || true)"
  if [ -n "$sha" ] && [ -n "$body" ]; then
    if command -v jq >/dev/null 2>&1; then
      canonical="$(canonicalize_json "$body")"
      calc="$(printf "%s" "$canonical" | sha256sum | awk '{print $1}')"
      [ "$calc" = "$sha" ] || { log "SHA mismatch for $pkg"; return; }
    else
      log "Skipping SHA verification for $pkg (jq not available)"
    fi
  fi
  apply_config "$pkg" "$body"
}

main_loop() {
  while true; do
    load_config
    require_settings
    register_once
    send_status
    fetch_config
    sleep "$interval"
  done
}

main_loop

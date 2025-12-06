#!/bin/sh
# Wiretide Agent (skeleton)
# Reference shell for OpenWrt agents. Not production-ready: fill in apply_* handlers.

set -eu

CONFIG_FILE="/etc/wiretide/agent.conf"
STATE_DIR="/tmp/wiretide"
DEVICE_ID_FILE="$STATE_DIR/device_id"
LOG_FILE="/var/wiretide-debug.log"
INTERVAL="${INTERVAL:-30}"

controller_url="${CONTROLLER_URL:-http://127.0.0.1:9000}"
shared_token="${SHARED_TOKEN:-}"
device_id="${DEVICE_ID:-}"

mkdir -p "$STATE_DIR"

log() {
  echo "$(date -Iseconds) $*" >>"$LOG_FILE"
}

load_config() {
  [ -f "$CONFIG_FILE" ] && . "$CONFIG_FILE"
  [ -f "$DEVICE_ID_FILE" ] && device_id="$(cat "$DEVICE_ID_FILE")"
}

save_device_id() {
  echo "$device_id" >"$DEVICE_ID_FILE"
}

http_post_json() {
  path="$1"; data="$2"
  wget -qO- \
    --header="Content-Type: application/json" \
    --header="X-Shared-Token: $shared_token" \
    --post-data="$data" \
    "$controller_url/$path" 2>/dev/null || true
}

http_get() {
  path="$1"
  wget -qO- \
    --header="X-Shared-Token: $shared_token" \
    "$controller_url/$path" 2>/dev/null || true
}

recover_token() {
  new_token="$(wget -qO- "$controller_url/token/current" 2>/dev/null | jsonfilter -e '@.shared_token' || true)"
  if [ -n "$new_token" ]; then
    shared_token="$new_token"
    log "Recovered shared token"
  fi
}

register_once() {
  [ -n "$device_id" ] && return 0
  payload="{\"hostname\":\"$(hostname)\",\"ssh_enabled\":true}"
  resp="$(http_post_json "register" "$payload")"
  device_id="$(echo "$resp" | jsonfilter -e '@.device_id' 2>/dev/null || true)"
  if [ -n "$device_id" ]; then
    save_device_id
    log "Registered device_id=$device_id"
  else
    log "Register failed, resp=$resp"
  fi
}

send_status() {
  [ -z "$device_id" ] && return 0
  payload="{\"device_id\":$device_id,\"dns_ok\":true,\"ntp_ok\":true,\"ssh_enabled\":true}"
  resp="$(http_post_json "status" "$payload")"
  if echo "$resp" | grep -q '"detail":"Invalid shared token"'; then
    recover_token
  fi
}

apply_config() {
  pkg="$1"; json="$2"
  case "$pkg" in
    wiretide.firewall) log "Apply firewall (stub)";;
    wiretide.apps) log "Apply apps (stub)";;
    wiretide.ssid) log "Apply wifi (stub)";;
    wiretide.update) log "Apply update (stub)";;
    *) log "Unknown package $pkg";;
  esac
}

fetch_config() {
  [ -z "$device_id" ] && return 0
  cfg="$(http_get "config?device_id=$device_id")"
  echo "$cfg" | grep -q '"package"' || return 0
  pkg="$(echo "$cfg" | jsonfilter -e '@.package' 2>/dev/null || true)"
  sha="$(echo "$cfg" | jsonfilter -e '@.sha256' 2>/dev/null || true)"
  body="$(echo "$cfg" | jsonfilter -e '@.package_json' 2>/dev/null || true)"
  if [ -n "$sha" ]; then
    echo "$body" | sha256sum | grep -q "$sha" || { log "SHA mismatch"; return; }
  fi
  apply_config "$pkg" "$body"
}

main_loop() {
  while true; do
    load_config
    register_once
    send_status
    fetch_config
    sleep "$INTERVAL"
  done
}

if [ -z "$shared_token" ]; then
  echo "Shared token not set; export SHARED_TOKEN or set in $CONFIG_FILE" >&2
  exit 1
fi

main_loop

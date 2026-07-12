#!/bin/bash
# Shared helpers for Gongserver installer

set -euo pipefail

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

log()  { echo -e "${GREEN}[+]${NC} $*"; }
warn() { echo -e "${YELLOW}[!]${NC} $*"; }
err()  { echo -e "${RED}[x]${NC} $*" >&2; }
die()  { err "$*"; exit 1; }

require_root() {
  if [[ ${EUID:-$(id -u)} -ne 0 ]]; then
    die "Run as root: sudo $0 $*"
  fi
}

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"

load_config() {
  local cfg="${GONG_CONFIG_FILE:-$REPO_ROOT/config.env}"
  if [[ -f "$cfg" ]]; then
    log "Loading config: $cfg"
    # shellcheck disable=SC1090
    set -a
    # shellcheck source=/dev/null
    source "$cfg"
    set +a
  else
    warn "No config.env found — using defaults from config.env.example"
    # shellcheck disable=SC1090
    set -a
    # shellcheck source=/dev/null
    source "$REPO_ROOT/config.env.example"
    set +a
  fi

  : "${GONG_HOSTNAME:=DhammaGong}"
  : "${GONG_TIMEZONE:=Asia/Kolkata}"
  : "${GONG_DB_NAME:=gong}"
  : "${GONG_DB_USER:=gong}"
  : "${GONG_DB_PASS:=ChangeThisDbPassword}"
  : "${GONG_AUDIO_PLAYER:=mpg123}"
  : "${GONG_CONFIGURE_AP:=0}"
  : "${GONG_WLAN_IFACE:=wlan0}"
  : "${GONG_AP_ADDRESS:=192.168.5.1}"
  : "${GONG_WIFI_SSID:=DhammaGong}"
  : "${GONG_WIFI_PASSPHRASE:=Dhamma4all}"
  : "${GONG_WIFI_CHANNEL:=6}"
  : "${GONG_WIFI_COUNTRY:=IN}"
  : "${GONG_DHCP_START:=192.168.5.5}"
  : "${GONG_DHCP_END:=192.168.5.50}"
  : "${GONG_INSTALL_PHPMYADMIN:=0}"
  : "${GONG_APP_USER:=dhamma}"
  : "${GONG_APP_HOME:=/home/dhamma}"
}

is_raspberry_pi() {
  [[ -f /proc/device-tree/model ]] && grep -qi raspberry /proc/device-tree/model 2>/dev/null
}

export DEBIAN_FRONTEND=noninteractive

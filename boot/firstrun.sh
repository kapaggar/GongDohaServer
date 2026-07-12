#!/bin/bash
#
# Gongserver complete first-boot provisioner
# ==========================================
# Place this file on the Raspberry Pi boot partition as firstrun.sh and wire
# cmdline.txt (see cmdline.txt.example). Optionally place:
#   gong-firstrun.env     — overrides
#   gongserver/           — full payload (this git repo) for offline install
#   gongserver/config.env — installer secrets
#
# Stage 0 (always): hostname, SSH, user, timezone, optional client Wi-Fi
# Stage 1: install Gongserver LAMP stack via installer/install.sh
#          (immediate or deferred systemd oneshot — see GONG_FIRSTRUN_MODE)
#
# Designed to finish even if individual steps fail (so the Pi still boots).
# Logs: /var/log/gong-firstrun.log  and  /boot[/firmware]/gong-firstrun.status
#

# Do not use set -e: a failed step must not strand first boot mid-script.
set +e

export DEBIAN_FRONTEND=noninteractive
export PATH="/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"

LOG=/var/log/gong-firstrun.log
STATUS_NAME=gong-firstrun.status
MARKER_DONE=/var/lib/gongserver/firstrun.done

mkdir -p /var/log /var/lib/gongserver 2>/dev/null
exec >>"$LOG" 2>&1
echo "======== gong firstrun start $(date -Is 2>/dev/null || date) ========"

log()  { echo "[+] $*"; }
warn() { echo "[!] $*"; }
err()  { echo "[x] $*"; }

# ---------------------------------------------------------------------------
# Locate boot partition paths (Buster/Bullseye: /boot ; Bookworm: /boot/firmware)
# ---------------------------------------------------------------------------
find_boot_dir() {
  local d
  for d in /boot/firmware /boot; do
    if [[ -d "$d" ]] && ( [[ -f "$d/cmdline.txt" ]] || [[ -f "$d/config.txt" ]] || [[ -f "$d/firstrun.sh" ]] ); then
      echo "$d"
      return 0
    fi
  done
  # fallback
  if [[ -d /boot/firmware ]]; then echo /boot/firmware; else echo /boot; fi
}

BOOT_DIR="$(find_boot_dir)"
log "Boot dir: $BOOT_DIR"

write_status() {
  local msg="$1"
  echo "$msg" >"$BOOT_DIR/$STATUS_NAME" 2>/dev/null
  echo "$msg" >"/boot/$STATUS_NAME" 2>/dev/null
  log "STATUS: $msg"
}

# ---------------------------------------------------------------------------
# Load optional env from boot partition
# ---------------------------------------------------------------------------
load_firstrun_env() {
  local f
  for f in \
    "$BOOT_DIR/gong-firstrun.env" \
    /boot/firmware/gong-firstrun.env \
    /boot/gong-firstrun.env
  do
    if [[ -f "$f" ]]; then
      log "Loading $f"
      # shellcheck disable=SC1090
      set -a
      # shellcheck source=/dev/null
      source "$f"
      set +a
      return 0
    fi
  done
  warn "No gong-firstrun.env found — using built-in defaults"
}

# Defaults (overridden by gong-firstrun.env)
: "${GONG_HOSTNAME:=DhammaGong}"
: "${GONG_TIMEZONE:=Asia/Kolkata}"
: "${GONG_KEYMAP:=us}"
: "${GONG_ENABLE_SSH:=1}"
: "${GONG_PI_PASSWORD_HASH:=}"
: "${GONG_CLIENT_WIFI_SSID:=}"
: "${GONG_CLIENT_WIFI_PSK:=}"
: "${GONG_WIFI_COUNTRY:=IN}"
: "${GONG_FIRSTRUN_MODE:=deferred}"
: "${GONG_PAYLOAD_DIR:=}"
: "${GONG_INSTALL_CONFIG:=}"
: "${GONG_CONFIGURE_AP:=1}"
: "${GONG_REBOOT_AFTER_INSTALL:=0}"
: "${GONG_NETWORK_WAIT:=180}"

load_firstrun_env

# Re-apply defaults for any still-empty after source
: "${GONG_HOSTNAME:=DhammaGong}"
: "${GONG_TIMEZONE:=Asia/Kolkata}"
: "${GONG_KEYMAP:=us}"
: "${GONG_ENABLE_SSH:=1}"
: "${GONG_FIRSTRUN_MODE:=deferred}"
: "${GONG_CONFIGURE_AP:=1}"
: "${GONG_WIFI_COUNTRY:=IN}"
: "${GONG_NETWORK_WAIT:=180}"
: "${GONG_REBOOT_AFTER_INSTALL:=0}"

write_status "running stage0 $(date -Is 2>/dev/null || date)"

# ---------------------------------------------------------------------------
# Already completed?
# ---------------------------------------------------------------------------
if [[ -f "$MARKER_DONE" ]]; then
  log "Marker $MARKER_DONE exists — cleaning boot hooks only"
  cleanup_boot_hooks
  write_status "already-done $(date -Is 2>/dev/null || date)"
  exit 0
fi

# ---------------------------------------------------------------------------
# Stage 0 helpers (Imager-compatible)
# ---------------------------------------------------------------------------
set_hostname() {
  local host="$1"
  log "Hostname -> $host"
  if [[ -x /usr/lib/raspberrypi-sys-mods/imager_custom ]]; then
    /usr/lib/raspberrypi-sys-mods/imager_custom set_hostname "$host" || true
  else
    local current
    current=$(tr -d " \t\n\r" </etc/hostname 2>/dev/null)
    echo "$host" >/etc/hostname
    if grep -q "127.0.1.1" /etc/hosts 2>/dev/null; then
      sed -i "s/127.0.1.1.*/127.0.1.1\t${host}/" /etc/hosts
    else
      echo -e "127.0.1.1\t${host}" >>/etc/hosts
    fi
    hostname "$host" 2>/dev/null || true
  fi
}

enable_ssh() {
  [[ "$GONG_ENABLE_SSH" == "1" ]] || { log "SSH enable skipped"; return 0; }
  log "Enabling SSH"
  if [[ -x /usr/lib/raspberrypi-sys-mods/imager_custom ]]; then
    /usr/lib/raspberrypi-sys-mods/imager_custom enable_ssh || true
  else
    systemctl enable ssh 2>/dev/null || systemctl enable sshd 2>/dev/null || true
    touch /boot/ssh 2>/dev/null
    touch "$BOOT_DIR/ssh" 2>/dev/null
  fi
  systemctl start ssh 2>/dev/null || systemctl start sshd 2>/dev/null || true
}

ensure_pi_user() {
  log "Ensuring user pi"
  local FIRSTUSER FIRSTUSERHOME
  FIRSTUSER=$(getent passwd 1000 | cut -d: -f1)
  FIRSTUSERHOME=$(getent passwd 1000 | cut -d: -f6)

  if [[ -n "$GONG_PI_PASSWORD_HASH" ]]; then
    if [[ -x /usr/lib/userconf-pi/userconf ]]; then
      /usr/lib/userconf-pi/userconf 'pi' "$GONG_PI_PASSWORD_HASH" || true
    else
      if [[ -n "$FIRSTUSER" ]]; then
        echo "${FIRSTUSER}:${GONG_PI_PASSWORD_HASH}" | chpasswd -e || true
      fi
    fi
  else
    warn "GONG_PI_PASSWORD_HASH empty — not changing passwords"
  fi

  # Rename uid 1000 to pi if needed (Imager path already handles via userconf)
  if [[ -n "$FIRSTUSER" && "$FIRSTUSER" != "pi" ]]; then
    if ! id pi >/dev/null 2>&1; then
      log "Renaming user $FIRSTUSER -> pi"
      usermod -l "pi" "$FIRSTUSER" 2>/dev/null || true
      usermod -m -d "/home/pi" "pi" 2>/dev/null || true
      groupmod -n "pi" "$FIRSTUSER" 2>/dev/null || true
      if [[ -f /etc/lightdm/lightdm.conf ]] && grep -q "^autologin-user=" /etc/lightdm/lightdm.conf; then
        sed /etc/lightdm/lightdm.conf -i -e "s/^autologin-user=.*/autologin-user=pi/"
      fi
      if [[ -f /etc/systemd/system/getty@tty1.service.d/autologin.conf ]]; then
        sed /etc/systemd/system/getty@tty1.service.d/autologin.conf -i -e "s/$FIRSTUSER/pi/"
      fi
      if [[ -f /etc/sudoers.d/010_pi-nopasswd ]]; then
        sed -i "s/^$FIRSTUSER /pi /" /etc/sudoers.d/010_pi-nopasswd
      fi
    fi
  fi

  # Passwordless sudo for pi if missing (common on Pi images)
  if id pi >/dev/null 2>&1 && [[ ! -f /etc/sudoers.d/010_pi-nopasswd ]]; then
    echo "pi ALL=(ALL) NOPASSWD: ALL" >/etc/sudoers.d/010_pi-nopasswd
    chmod 440 /etc/sudoers.d/010_pi-nopasswd
  fi
}

set_locale_tz() {
  log "Timezone=$GONG_TIMEZONE keymap=$GONG_KEYMAP"
  if [[ -x /usr/lib/raspberrypi-sys-mods/imager_custom ]]; then
    /usr/lib/raspberrypi-sys-mods/imager_custom set_keymap "$GONG_KEYMAP" || true
    /usr/lib/raspberrypi-sys-mods/imager_custom set_timezone "$GONG_TIMEZONE" || true
  else
    rm -f /etc/localtime
    echo "$GONG_TIMEZONE" >/etc/timezone
    if command -v timedatectl >/dev/null 2>&1; then
      timedatectl set-timezone "$GONG_TIMEZONE" 2>/dev/null || true
    else
      ln -sf "/usr/share/zoneinfo/$GONG_TIMEZONE" /etc/localtime 2>/dev/null || true
      dpkg-reconfigure -f noninteractive tzdata 2>/dev/null || true
    fi
    cat >/etc/default/keyboard <<KBEOF
XKBMODEL="pc105"
XKBLAYOUT="${GONG_KEYMAP}"
XKBVARIANT=""
XKBOPTIONS=""
KBEOF
    dpkg-reconfigure -f noninteractive keyboard-configuration 2>/dev/null || true
  fi

  # Wi-Fi country
  if command -v raspi-config >/dev/null 2>&1; then
    raspi-config nonint do_wifi_country "$GONG_WIFI_COUNTRY" 2>/dev/null || true
  fi
  rfkill unblock wifi 2>/dev/null || true
  for filename in /var/lib/systemd/rfkill/*:wlan; do
    [[ -e "$filename" ]] && echo 0 >"$filename"
  done
}

set_client_wifi() {
  if [[ -z "${GONG_CLIENT_WIFI_SSID:-}" ]]; then
    log "No client Wi-Fi SSID configured — skip station mode"
    return 0
  fi
  log "Configuring client Wi-Fi SSID=${GONG_CLIENT_WIFI_SSID} country=${GONG_WIFI_COUNTRY}"
  local psk="${GONG_CLIENT_WIFI_PSK:-}"
  if [[ -x /usr/lib/raspberrypi-sys-mods/imager_custom ]]; then
    /usr/lib/raspberrypi-sys-mods/imager_custom set_wlan \
      "$GONG_CLIENT_WIFI_SSID" "$psk" "$GONG_WIFI_COUNTRY" || true
  else
    cat >/etc/wpa_supplicant/wpa_supplicant.conf <<WPAEOF
country=${GONG_WIFI_COUNTRY}
ctrl_interface=DIR=/var/run/wpa_supplicant GROUP=netdev
ap_scan=1
update_config=1
network={
	ssid="${GONG_CLIENT_WIFI_SSID}"
	psk=${psk}
}
WPAEOF
    # If PSK is not hex-64, quote it as passphrase
    if [[ ${#psk} -ne 64 ]]; then
      cat >/etc/wpa_supplicant/wpa_supplicant.conf <<WPAEOF
country=${GONG_WIFI_COUNTRY}
ctrl_interface=DIR=/var/run/wpa_supplicant GROUP=netdev
ap_scan=1
update_config=1
network={
	ssid="${GONG_CLIENT_WIFI_SSID}"
	psk="${psk}"
}
WPAEOF
    fi
    chmod 600 /etc/wpa_supplicant/wpa_supplicant.conf
  fi
  rfkill unblock wifi 2>/dev/null || true
  systemctl restart wpa_supplicant 2>/dev/null || true
  systemctl restart dhcpcd 2>/dev/null || true
  systemctl restart NetworkManager 2>/dev/null || true
}

# ---------------------------------------------------------------------------
# Payload discovery / install helpers
# ---------------------------------------------------------------------------
find_payload() {
  local d
  if [[ -n "${GONG_PAYLOAD_DIR:-}" && -d "$GONG_PAYLOAD_DIR" ]]; then
    echo "$GONG_PAYLOAD_DIR"
    return 0
  fi
  for d in \
    "$BOOT_DIR/gongserver" \
    /boot/firmware/gongserver \
    /boot/gongserver \
    /opt/gongserver \
    /home/pi/gongserver \
    /home/dhamma/gongserver
  do
    if [[ -x "$d/installer/install.sh" ]] || [[ -f "$d/installer/install.sh" ]]; then
      echo "$d"
      return 0
    fi
  done
  return 1
}

install_payload_to_opt() {
  local src="$1"
  local dst=/opt/gongserver
  if [[ "$src" == "$dst" ]]; then
    echo "$dst"
    return 0
  fi
  log "Copying payload $src -> $dst"
  mkdir -p "$dst"
  if command -v rsync >/dev/null 2>&1; then
    rsync -a --delete \
      --exclude '.git' \
      --exclude 'docker' \
      --exclude '.DS_Store' \
      "$src/" "$dst/" || cp -a "$src/." "$dst/"
  else
    cp -a "$src/." "$dst/"
  fi
  chmod +x "$dst/installer/install.sh" "$dst/installer/lib/common.sh" 2>/dev/null || true
  chmod +x "$dst/boot/firstrun.sh" 2>/dev/null || true
  echo "$dst"
}

resolve_install_config() {
  local payload="$1"
  if [[ -n "${GONG_INSTALL_CONFIG:-}" && -f "$GONG_INSTALL_CONFIG" ]]; then
    echo "$GONG_INSTALL_CONFIG"
    return 0
  fi
  if [[ -f "$payload/config.env" ]]; then
    echo "$payload/config.env"
    return 0
  fi
  if [[ -f "$BOOT_DIR/gong-config.env" ]]; then
    echo "$BOOT_DIR/gong-config.env"
    return 0
  fi
  # Generate a minimal config for first boot
  local gen=/etc/gongserver/firstboot-config.env
  mkdir -p /etc/gongserver
  cat >"$gen" <<EOF
GONG_HOSTNAME=${GONG_HOSTNAME}
GONG_TIMEZONE=${GONG_TIMEZONE}
GONG_DB_NAME=gong
GONG_DB_USER=gong
GONG_DB_PASS=$(tr -dc 'A-Za-z0-9' </dev/urandom 2>/dev/null | head -c 16 || echo ChangeMeGongDb)
GONG_AUDIO_PLAYER=mpg123
GONG_CONFIGURE_AP=${GONG_CONFIGURE_AP}
GONG_WLAN_IFACE=wlan0
GONG_AP_ADDRESS=192.168.5.1
GONG_WIFI_SSID=DhammaGong
GONG_WIFI_PASSPHRASE=Dhamma4all
GONG_WIFI_CHANNEL=6
GONG_WIFI_COUNTRY=${GONG_WIFI_COUNTRY}
GONG_DHCP_START=192.168.5.5
GONG_DHCP_END=192.168.5.50
GONG_INSTALL_PHPMYADMIN=0
GONG_APP_USER=dhamma
GONG_APP_HOME=/home/dhamma
EOF
  chmod 600 "$gen"
  warn "Generated $gen — change GONG_DB_PASS / Wi-Fi passphrase after first login"
  echo "$gen"
}

run_installer() {
  local payload="$1"
  local cfg
  cfg="$(resolve_install_config "$payload")"
  log "Running installer from $payload config=$cfg AP=${GONG_CONFIGURE_AP}"

  # Ensure installer sees AP flag even if config.env says otherwise
  if [[ "$GONG_CONFIGURE_AP" == "1" ]]; then
    # shellcheck disable=SC1090
    set -a
    # shellcheck source=/dev/null
    source "$cfg" 2>/dev/null || true
    set +a
    export GONG_CONFIGURE_AP=1
    # rewrite AP=1 into a temp config merge
    local merged=/etc/gongserver/firstboot-merged.env
    mkdir -p /etc/gongserver
    cat "$cfg" >"$merged"
    grep -q '^GONG_CONFIGURE_AP=' "$merged" \
      && sed -i 's/^GONG_CONFIGURE_AP=.*/GONG_CONFIGURE_AP=1/' "$merged" \
      || echo 'GONG_CONFIGURE_AP=1' >>"$merged"
    cfg="$merged"
  fi

  chmod +x "$payload/installer/install.sh" 2>/dev/null || true
  if [[ "$GONG_CONFIGURE_AP" == "1" ]]; then
    GONG_CONFIG_FILE="$cfg" bash "$payload/installer/install.sh" --with-ap
  else
    GONG_CONFIG_FILE="$cfg" bash "$payload/installer/install.sh" --skip-ap
  fi
}

wait_for_network() {
  local max="${1:-180}"
  local i=0
  log "Waiting up to ${max}s for network…"
  while [[ $i -lt $max ]]; do
    if ping -c1 -W2 1.1.1.1 >/dev/null 2>&1 \
      || ping -c1 -W2 8.8.8.8 >/dev/null 2>&1 \
      || ping -c1 -W2 deb.debian.org >/dev/null 2>&1; then
      log "Network is up after ${i}s"
      return 0
    fi
    # also accept default route without internet (local AP later)
    if ip route 2>/dev/null | grep -q default; then
      if ping -c1 -W2 "$(ip route | awk '/default/ {print $3; exit}')" >/dev/null 2>&1; then
        log "Default gateway reachable after ${i}s"
        return 0
      fi
    fi
    sleep 2
    i=$((i + 2))
  done
  warn "Network wait timed out — apt may fail if mirrors unreachable"
  return 1
}

# ---------------------------------------------------------------------------
# Deferred install unit (runs after first multi-user boot)
# ---------------------------------------------------------------------------
install_deferred_unit() {
  local payload="$1"
  local cfg
  cfg="$(resolve_install_config "$payload")"
  local runner=/usr/local/sbin/gongserver-firstboot-install
  local unit=/etc/systemd/system/gongserver-firstboot.service

  log "Installing deferred oneshot: $unit"

  cat >"$runner" <<EOF
#!/bin/bash
set +e
export PATH="/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
export DEBIAN_FRONTEND=noninteractive
LOG=/var/log/gong-firstboot-install.log
exec >>"\$LOG" 2>&1
echo "======== deferred install \$(date -Is 2>/dev/null || date) ========"

MARKER=/var/lib/gongserver/firstrun.done
if [[ -f "\$MARKER" ]]; then
  echo "Already done"
  systemctl disable gongserver-firstboot.service 2>/dev/null || true
  exit 0
fi

# shellcheck disable=SC1091
[[ -f /etc/gongserver/firstrun-runtime.env ]] && source /etc/gongserver/firstrun-runtime.env

PAYLOAD="\${GONG_PAYLOAD_INSTALLED:-/opt/gongserver}"
CFG="\${GONG_INSTALL_CONFIG_RESOLVED:-$cfg}"
AP="\${GONG_CONFIGURE_AP:-1}"
WAIT="\${GONG_NETWORK_WAIT:-180}"

# Wait for network if we need apt
if ! command -v apache2 >/dev/null 2>&1; then
  i=0
  while [[ \$i -lt \$WAIT ]]; do
    if ping -c1 -W2 1.1.1.1 >/dev/null 2>&1 || ping -c1 -W2 8.8.8.8 >/dev/null 2>&1; then
      break
    fi
    sleep 2
    i=\$((i+2))
  done
fi

if [[ ! -x "\$PAYLOAD/installer/install.sh" && -f "\$PAYLOAD/installer/install.sh" ]]; then
  chmod +x "\$PAYLOAD/installer/install.sh" || true
fi

if [[ ! -f "\$PAYLOAD/installer/install.sh" ]]; then
  echo "Missing installer at \$PAYLOAD"
  echo "FAILED missing-installer \$(date -Is 2>/dev/null || date)" > /boot/gong-firstrun.status 2>/dev/null
  echo "FAILED missing-installer" > /boot/firmware/gong-firstrun.status 2>/dev/null
  exit 1
fi

if [[ "\$AP" == "1" ]]; then
  GONG_CONFIG_FILE="\$CFG" bash "\$PAYLOAD/installer/install.sh" --with-ap
  rc=\$?
else
  GONG_CONFIG_FILE="\$CFG" bash "\$PAYLOAD/installer/install.sh" --skip-ap
  rc=\$?
fi

if [[ \$rc -eq 0 ]]; then
  mkdir -p /var/lib/gongserver
  date -Is > "\$MARKER" 2>/dev/null || date > "\$MARKER"
  echo "OK install-complete \$(date -Is 2>/dev/null || date)" > /boot/gong-firstrun.status 2>/dev/null
  echo "OK install-complete" > /boot/firmware/gong-firstrun.status 2>/dev/null
  systemctl disable gongserver-firstboot.service 2>/dev/null || true
  if [[ "\${GONG_REBOOT_AFTER_INSTALL:-0}" == "1" ]]; then
    sleep 3
    reboot || true
  fi
  exit 0
fi

echo "FAILED install-rc=\$rc \$(date -Is 2>/dev/null || date)" > /boot/gong-firstrun.status 2>/dev/null
echo "FAILED install-rc=\$rc" > /boot/firmware/gong-firstrun.status 2>/dev/null
exit \$rc
EOF
  chmod 755 "$runner"

  mkdir -p /etc/gongserver
  cat >/etc/gongserver/firstrun-runtime.env <<EOF
GONG_PAYLOAD_INSTALLED=$payload
GONG_INSTALL_CONFIG_RESOLVED=$cfg
GONG_CONFIGURE_AP=$GONG_CONFIGURE_AP
GONG_NETWORK_WAIT=$GONG_NETWORK_WAIT
GONG_REBOOT_AFTER_INSTALL=$GONG_REBOOT_AFTER_INSTALL
EOF
  chmod 600 /etc/gongserver/firstrun-runtime.env

  cat >"$unit" <<'EOF'
[Unit]
Description=Gongserver first-boot LAMP/app install
After=network-online.target
Wants=network-online.target
ConditionPathExists=!/var/lib/gongserver/firstrun.done

[Service]
Type=oneshot
ExecStart=/usr/local/sbin/gongserver-firstboot-install
RemainAfterExit=yes
TimeoutStartSec=0

[Install]
WantedBy=multi-user.target
EOF

  systemctl daemon-reload 2>/dev/null || true
  systemctl enable gongserver-firstboot.service 2>/dev/null || true
  log "Deferred unit enabled — will run after reboot/network"
}

# ---------------------------------------------------------------------------
# Cleanup boot hooks so firstrun does not re-run forever
# ---------------------------------------------------------------------------
cleanup_boot_hooks() {
  log "Cleaning firstrun boot hooks in $BOOT_DIR"
  # Remove ourselves from boot (keep a copy under /var for forensics)
  if [[ -f "$BOOT_DIR/firstrun.sh" ]]; then
    mkdir -p /var/lib/gongserver
    cp -a "$BOOT_DIR/firstrun.sh" /var/lib/gongserver/firstrun.sh.bak 2>/dev/null || true
    rm -f "$BOOT_DIR/firstrun.sh"
  fi
  rm -f /boot/firstrun.sh 2>/dev/null

  for cmd in "$BOOT_DIR/cmdline.txt" /boot/cmdline.txt /boot/firmware/cmdline.txt; do
    if [[ -f "$cmd" ]]; then
      # strip systemd.run=… fragments (Imager style)
      sed -i 's| systemd.run=[^ ]*||g; s| systemd.run_success_action=[^ ]*||g; s| systemd.unit=kernel-command-line.target||g' "$cmd"
      # collapse double spaces
      sed -i 's/  */ /g' "$cmd"
      log "Updated $cmd"
    fi
  done
}

# ===========================================================================
# MAIN
# ===========================================================================
set_hostname "$GONG_HOSTNAME"
enable_ssh
ensure_pi_user
set_locale_tz
set_client_wifi

write_status "stage0-complete looking-for-payload $(date -Is 2>/dev/null || date)"

PAYLOAD="$(find_payload)"
if [[ -z "$PAYLOAD" ]]; then
  err "No gongserver payload found (expected $BOOT_DIR/gongserver with installer/install.sh)"
  write_status "FAILED no-payload stage0-only $(date -Is 2>/dev/null || date)"
  # Still finish stage0 cleanly so device is SSH-able
  cleanup_boot_hooks
  # Leave marker only for stage0 so deferred isn't falsely "done"
  echo "stage0-only $(date -Is 2>/dev/null || date)" >/var/lib/gongserver/firstrun.stage0
  exit 0
fi

log "Found payload at $PAYLOAD"
PAYLOAD="$(install_payload_to_opt "$PAYLOAD")"
log "Payload installed at $PAYLOAD"

MODE="$(echo "$GONG_FIRSTRUN_MODE" | tr '[:upper:]' '[:lower:]')"
case "$MODE" in
  immediate|now|inline)
    write_status "stage1-immediate $(date -Is 2>/dev/null || date)"
    wait_for_network "$GONG_NETWORK_WAIT" || true
    if run_installer "$PAYLOAD"; then
      date -Is >"$MARKER_DONE" 2>/dev/null || date >"$MARKER_DONE"
      write_status "OK complete $(date -Is 2>/dev/null || date)"
    else
      err "Installer failed — enabling deferred retry unit"
      write_status "FAILED immediate-install — scheduling deferred retry"
      install_deferred_unit "$PAYLOAD"
    fi
    ;;
  deferred|systemd|oneshot|*)
    write_status "stage1-deferred-unit $(date -Is 2>/dev/null || date)"
    install_deferred_unit "$PAYLOAD"
    ;;
esac

cleanup_boot_hooks
log "======== gong firstrun finished $(date -Is 2>/dev/null || date) ========"
# Exit 0 so systemd.run_success_action=reboot proceeds
exit 0

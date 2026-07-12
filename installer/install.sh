#!/bin/bash
#
# DhammaGong / Gongserver installer
# Transforms a fresh Raspberry Pi OS (Debian-based) into a working gong + doha LAMP appliance.
#
# Usage:
#   cp config.env.example config.env   # edit secrets
#   sudo ./installer/install.sh
#   sudo ./installer/install.sh --with-ap
#   sudo ./installer/install.sh --skip-ap
#   sudo ./installer/install.sh --help
#
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib/common.sh
source "$SCRIPT_DIR/lib/common.sh"

WITH_AP=""
SKIP_PACKAGES=0
SKIP_DB=0

usage() {
  cat <<'EOF'
Gongserver installer — LAMP + gong/doha scheduler for Raspberry Pi OS

Usage: sudo ./installer/install.sh [options]

Options:
  --with-ap          Configure Wi-Fi Access Point (hostapd + dnsmasq)
  --skip-ap          Do not configure AP (default unless config.env sets GONG_CONFIGURE_AP=1)
  --skip-packages    Skip apt install (re-run deploy only)
  --skip-db          Skip database import
  -c, --config FILE  Config file (default: ./config.env)
  -h, --help         Show this help

Typical first install (ethernet recommended):
  cp config.env.example config.env
  nano config.env
  sudo ./installer/install.sh

Then open: http://<pi-ip>/
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --with-ap) WITH_AP=1; shift ;;
    --skip-ap) WITH_AP=0; shift ;;
    --skip-packages) SKIP_PACKAGES=1; shift ;;
    --skip-db) SKIP_DB=1; shift ;;
    -c|--config) GONG_CONFIG_FILE="$2"; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *) die "Unknown option: $1" ;;
  esac
done

require_root "$@"
load_config

if [[ -n "$WITH_AP" ]]; then
  GONG_CONFIGURE_AP="$WITH_AP"
fi

log "Repo root: $REPO_ROOT"
log "Hostname target: $GONG_HOSTNAME"
log "Configure AP: $GONG_CONFIGURE_AP"

if ! is_raspberry_pi; then
  warn "This does not look like a Raspberry Pi — continuing anyway (Debian-like OS assumed)."
fi

# --------------------------------------------------------------------------
# 1. Packages
# --------------------------------------------------------------------------
install_packages() {
  log "Updating apt and installing packages…"
  apt-get update -y
  apt-get install -y \
    apache2 \
    mariadb-server \
    mariadb-client \
    php \
    php-cli \
    php-mysql \
    php-mbstring \
    libapache2-mod-php \
    alsa-utils \
    mpg123 \
    python3 \
    cron \
    curl \
    rsync \
    logrotate

  # GPIO (package name varies by release)
  apt-get install -y python3-rpi.gpio 2>/dev/null \
    || apt-get install -y python3-rpi-lgpio 2>/dev/null \
    || warn "Could not install RPi.GPIO package — relay control may not work until installed."

  # Optional players
  if [[ "$GONG_AUDIO_PLAYER" == "mpv" ]]; then
    apt-get install -y mpv || warn "mpv install failed"
  fi
  if [[ "$GONG_AUDIO_PLAYER" == "omxplayer" ]]; then
    apt-get install -y omxplayer 2>/dev/null || warn "omxplayer not available on this OS — use mpg123"
    GONG_AUDIO_PLAYER=mpg123
  fi

  if [[ "$GONG_CONFIGURE_AP" == "1" ]]; then
    apt-get install -y hostapd dnsmasq iw wireless-tools || true
    systemctl unmask hostapd 2>/dev/null || true
  fi

  if [[ "$GONG_INSTALL_PHPMYADMIN" == "1" ]]; then
    apt-get install -y phpmyadmin || warn "phpMyAdmin install failed / needs interactive config"
  fi

  # Ensure services enabled
  systemctl enable apache2 mariadb cron
  systemctl start apache2 mariadb cron
}

# --------------------------------------------------------------------------
# 2. Hostname / timezone
# --------------------------------------------------------------------------
configure_identity() {
  log "Setting hostname and timezone…"
  hostnamectl set-hostname "$GONG_HOSTNAME" 2>/dev/null || echo "$GONG_HOSTNAME" > /etc/hostname
  if grep -q "10.0.0.2\|127.0.1.1" /etc/hosts 2>/dev/null; then
    sed -i "s/10.0.0.2.*/10.0.0.2\t${GONG_HOSTNAME}/; s/127.0.1.1.*/127.0.1.1\t${GONG_HOSTNAME}/" /etc/hosts || true
  fi
  if ! grep -q "$GONG_HOSTNAME" /etc/hosts; then
    echo "127.0.1.1	$GONG_HOSTNAME" >> /etc/hosts
  fi
  timedatectl set-timezone "$GONG_TIMEZONE" 2>/dev/null || ln -sf "/usr/share/zoneinfo/$GONG_TIMEZONE" /etc/localtime
}

# --------------------------------------------------------------------------
# 3. Users & app deploy
# --------------------------------------------------------------------------
deploy_app() {
  log "Deploying application to $GONG_APP_HOME …"
  if ! id -u "$GONG_APP_USER" >/dev/null 2>&1; then
    useradd -m -s /bin/bash "$GONG_APP_USER"
  fi

  mkdir -p "$GONG_APP_HOME/doha"
  rsync -a --delete \
    --exclude '.git' \
    "$REPO_ROOT/app/dhamma/" "$GONG_APP_HOME/"

  chown -R "$GONG_APP_USER:$GONG_APP_USER" "$GONG_APP_HOME"
  chmod 755 "$GONG_APP_HOME"
  chmod 755 "$GONG_APP_HOME/check-date" "$GONG_APP_HOME/relay-control"
  chmod 644 "$GONG_APP_HOME"/*.php "$GONG_APP_HOME"/*.inc 2>/dev/null || true
  chmod 644 "$GONG_APP_HOME"/*.mp3 2>/dev/null || true
  chmod 644 "$GONG_APP_HOME/doha"/*.mp3 2>/dev/null || true

  # Web UI
  mkdir -p /var/www/html
  install -m 644 "$REPO_ROOT/app/www/index.php" /var/www/html/index.php
  # Remove default Apache page if present
  rm -f /var/www/html/index.html

  # Log file
  touch /var/log/gong.log
  chown root:adm /var/log/gong.log 2>/dev/null || true
  chmod 664 /var/log/gong.log
  # www-data needs to read log; cron root writes it
  usermod -aG adm www-data 2>/dev/null || true

  # Runtime config for PHP
  mkdir -p /etc/gongserver
  cat > /etc/gongserver/config.inc.php <<EOF
<?php
// Generated by Gongserver installer — $(date -Is)
\$DB_HOST = "localhost";
\$DB_USER = "${GONG_DB_USER}";
\$DB_PASS = "${GONG_DB_PASS}";
\$DB_NAME = "${GONG_DB_NAME}";
\$GONG_HOME = "${GONG_APP_HOME}";
\$GONG_FILE = \$GONG_HOME . "/gong-replaceme.mp3";
\$DOHA_DIR = \$GONG_HOME . "/doha/";
\$RELAY_BIN = \$GONG_HOME . "/relay-control";
\$LOG_FILE = "/var/log/gong.log";
\$AUDIO_PLAYER = "${GONG_AUDIO_PLAYER}";
EOF
  chown root:www-data /etc/gongserver/config.inc.php
  chmod 640 /etc/gongserver/config.inc.php

  # constants.inc defaults still work; override file is preferred
  log "Wrote /etc/gongserver/config.inc.php"
}

# --------------------------------------------------------------------------
# 4. Database
# --------------------------------------------------------------------------
setup_database() {
  log "Configuring MariaDB database '${GONG_DB_NAME}'…"
  systemctl start mariadb

  # Create DB + user (works with unix_socket root on modern MariaDB)
  mysql --protocol=socket -u root <<SQL
CREATE DATABASE IF NOT EXISTS \`${GONG_DB_NAME}\` CHARACTER SET utf8mb4 COLLATE utf8mb4_general_ci;
SQL
  # User create: support older MariaDB without IF NOT EXISTS
  mysql --protocol=socket -u root -e "CREATE USER '${GONG_DB_USER}'@'localhost' IDENTIFIED BY '${GONG_DB_PASS}';" 2>/dev/null \
    || mysql --protocol=socket -u root -e "SET PASSWORD FOR '${GONG_DB_USER}'@'localhost' = PASSWORD('${GONG_DB_PASS}');" 2>/dev/null \
    || mysql --protocol=socket -u root -e "ALTER USER '${GONG_DB_USER}'@'localhost' IDENTIFIED BY '${GONG_DB_PASS}';" 2>/dev/null \
    || warn "Could not create/alter DB user (may already exist with different auth)"
  mysql --protocol=socket -u root <<SQL
GRANT ALL PRIVILEGES ON \`${GONG_DB_NAME}\`.* TO '${GONG_DB_USER}'@'localhost';
FLUSH PRIVILEGES;
SQL

  # Import schema if empty
  local count
  count="$(mysql --protocol=socket -u root -N -e "SELECT COUNT(*) FROM information_schema.tables WHERE table_schema='${GONG_DB_NAME}' AND table_name='settings';" 2>/dev/null || echo 0)"
  if [[ "$count" == "0" ]]; then
    log "Importing schema from db/gong.sql …"
    mysql --protocol=socket -u root "${GONG_DB_NAME}" < "$REPO_ROOT/db/gong.sql"
  else
    log "Database already has settings table — skipping import (use --force-db not implemented; drop DB to reimport)."
  fi

  # Ensure settings row exists and looks sane
  mysql --protocol=socket -u root "${GONG_DB_NAME}" <<SQL
UPDATE settings SET enabled=1, doha_enabled=1, gong_enabled=1 WHERE id=1;
SQL
}

# --------------------------------------------------------------------------
# 5. Apache / PHP
# --------------------------------------------------------------------------
configure_apache() {
  log "Configuring Apache…"
  a2enmod php* 2>/dev/null || a2enmod php8.2 2>/dev/null || a2enmod php8.1 2>/dev/null || a2enmod php7.4 2>/dev/null || true
  install -m 644 "$REPO_ROOT/os/apache/servername.conf" /etc/apache2/conf-available/gong-servername.conf
  a2enconf gong-servername 2>/dev/null || true
  # Allow www-data to read app constants path (already via /etc/gongserver)
  systemctl reload apache2
}

# --------------------------------------------------------------------------
# 6. Cron + sudoers + logrotate
# --------------------------------------------------------------------------
configure_cron_sudo() {
  log "Installing cron.d, sudoers, logrotate…"
  install -m 644 "$REPO_ROOT/os/crontab.gong" /etc/cron.d/gongserver
  # Fix paths if app home differs
  if [[ "$GONG_APP_HOME" != "/home/dhamma" ]]; then
    sed -i "s|/home/dhamma|${GONG_APP_HOME}|g" /etc/cron.d/gongserver
  fi
  install -m 440 "$REPO_ROOT/os/sudoers/020_www-data-gong" /etc/sudoers.d/020_www-data-gong
  # validate sudoers
  visudo -cf /etc/sudoers.d/020_www-data-gong || die "sudoers validation failed"
  install -m 644 "$REPO_ROOT/os/logrotate/gong" /etc/logrotate.d/gong
  systemctl restart cron 2>/dev/null || systemctl restart cron.service 2>/dev/null || true
}

# --------------------------------------------------------------------------
# 7. Optional Access Point
# --------------------------------------------------------------------------
configure_ap() {
  [[ "$GONG_CONFIGURE_AP" == "1" ]] || { log "Skipping AP configuration."; return 0; }

  warn "Configuring Wi-Fi AP — ensure you have ethernet SSH access."
  apt-get install -y hostapd dnsmasq iw || die "Failed to install hostapd/dnsmasq"

  # Stop NetworkManager from managing wlan if present
  if systemctl is-active --quiet NetworkManager 2>/dev/null; then
    warn "NetworkManager detected — creating unmanaged rule for $GONG_WLAN_IFACE"
    mkdir -p /etc/NetworkManager/conf.d
    cat > /etc/NetworkManager/conf.d/99-gong-unmanaged.conf <<EOF
[keyfile]
unmanaged-devices=interface-name:${GONG_WLAN_IFACE}
EOF
    systemctl restart NetworkManager || true
  fi

  # dhcpcd static IP (classic Raspberry Pi OS)
  if [[ -f /etc/dhcpcd.conf ]]; then
    if ! grep -q "Gongserver AP" /etc/dhcpcd.conf; then
      cat >> /etc/dhcpcd.conf <<EOF

# Gongserver AP
interface ${GONG_WLAN_IFACE}
static ip_address=${GONG_AP_ADDRESS}/24
nohook wpa_supplicant
EOF
    fi
    systemctl restart dhcpcd 2>/dev/null || true
  else
    # ip addr fallback until reboot
    ip link set "$GONG_WLAN_IFACE" up || true
    ip addr flush dev "$GONG_WLAN_IFACE" 2>/dev/null || true
    ip addr add "${GONG_AP_ADDRESS}/24" dev "$GONG_WLAN_IFACE" 2>/dev/null || true
  fi

  # hostapd
  local hap_out=/etc/hostapd/hostapd.conf
  sed \
    -e "s/WLAN_IFACE/${GONG_WLAN_IFACE}/g" \
    -e "s/WIFI_SSID/${GONG_WIFI_SSID}/g" \
    -e "s/WIFI_CHANNEL/${GONG_WIFI_CHANNEL}/g" \
    -e "s/WIFI_PASSPHRASE/${GONG_WIFI_PASSPHRASE}/g" \
    -e "s/WIFI_COUNTRY/${GONG_WIFI_COUNTRY}/g" \
    "$REPO_ROOT/os/hostapd/hostapd.conf.template" > "$hap_out"
  chmod 600 "$hap_out"
  if [[ -f /etc/default/hostapd ]]; then
    sed -i 's|^#\?DAEMON_CONF=.*|DAEMON_CONF="/etc/hostapd/hostapd.conf"|' /etc/default/hostapd
  fi
  # Bookworm: hostapd may use systemd drop-in
  mkdir -p /etc/systemd/system/hostapd.service.d
  cat > /etc/systemd/system/hostapd.service.d/override.conf <<EOF
[Service]
ExecStart=
ExecStart=/usr/sbin/hostapd -B -P /run/hostapd.pid /etc/hostapd/hostapd.conf
EOF
  # Prefer stock unit if it already uses DAEMON_CONF — keep both paths
  systemctl daemon-reload

  # dnsmasq
  if [[ -f /etc/dnsmasq.conf ]]; then
    # avoid double-binding: put our config in conf.d and ignore default interface lines if needed
    if ! grep -q "conf-dir=/etc/dnsmasq.d" /etc/dnsmasq.conf; then
      echo "conf-dir=/etc/dnsmasq.d/,*.conf" >> /etc/dnsmasq.conf
    fi
  fi
  sed \
    -e "s/WLAN_IFACE/${GONG_WLAN_IFACE}/g" \
    -e "s/DHCP_START/${GONG_DHCP_START}/g" \
    -e "s/DHCP_END/${GONG_DHCP_END}/g" \
    "$REPO_ROOT/os/dnsmasq/gongserver.conf" > /etc/dnsmasq.d/gongserver.conf

  # rfkill unblock wifi
  rfkill unblock wifi 2>/dev/null || true
  raspi-config nonint do_wifi_country "$GONG_WIFI_COUNTRY" 2>/dev/null || true

  systemctl unmask hostapd
  systemctl enable hostapd dnsmasq
  systemctl restart dhcpcd 2>/dev/null || true
  sleep 1
  systemctl restart hostapd || warn "hostapd failed to start — check journalctl -u hostapd"
  systemctl restart dnsmasq || warn "dnsmasq failed — check journalctl -u dnsmasq"

  log "AP SSID=${GONG_WIFI_SSID} address=${GONG_AP_ADDRESS}"
}

# --------------------------------------------------------------------------
# 8. Audio group / sanity
# --------------------------------------------------------------------------
configure_audio() {
  log "Audio setup…"
  usermod -aG audio root 2>/dev/null || true
  usermod -aG audio "$GONG_APP_USER" 2>/dev/null || true
  usermod -aG gpio "$GONG_APP_USER" 2>/dev/null || true
  # Ensure mpg123 exists
  if ! command -v mpg123 >/dev/null 2>&1; then
    warn "mpg123 missing — install manually: apt install mpg123"
  fi
}

# --------------------------------------------------------------------------
# 9. Smoke tests
# --------------------------------------------------------------------------
smoke_test() {
  log "Running smoke tests…"
  php -r "require '/etc/gongserver/config.inc.php'; echo \"DB user=\$DB_USER player=\$AUDIO_PLAYER\n\";"
  if php -r "
    require '${GONG_APP_HOME}/constants.inc';
    db_connect();
    global \$DB_CONN;
    \$r = mysqli_query(\$DB_CONN, 'SELECT COUNT(*) c FROM schedule');
    \$row = mysqli_fetch_assoc(\$r);
    echo 'schedule_rows=' . \$row['c'] . PHP_EOL;
  "; then
    log "Database connectivity OK"
  else
    warn "DB connectivity test failed — check /etc/gongserver/config.inc.php and mariadb"
  fi

  curl -s -o /dev/null -w "HTTP %{http_code}\n" http://127.0.0.1/ || warn "Apache local HTTP check failed"
  log "Cron file: /etc/cron.d/gongserver"
  systemctl is-active apache2 mariadb cron || true
}

# --------------------------------------------------------------------------
# Main
# --------------------------------------------------------------------------
main() {
  log "=== Gongserver install start ==="
  if [[ "$SKIP_PACKAGES" -eq 0 ]]; then
    install_packages
  else
    log "Skipping package install"
  fi
  configure_identity
  deploy_app
  if [[ "$SKIP_DB" -eq 0 ]]; then
    setup_database
  else
    log "Skipping database setup"
  fi
  configure_apache
  configure_cron_sudo
  configure_audio
  configure_ap
  smoke_test

  cat <<EOF

${GREEN}=== Gongserver install complete ===${NC}

  Admin UI:   http://$(hostname -I 2>/dev/null | awk '{print $1}')/
  App home:   ${GONG_APP_HOME}
  DB:         ${GONG_DB_NAME} (user ${GONG_DB_USER})
  Log:        /var/log/gong.log
  Cron:       /etc/cron.d/gongserver
  Config:     /etc/gongserver/config.inc.php

Next steps:
  1. Set the correct date/time in the web UI (critical for schedules).
  2. Add a course or Set Zero Date.
  3. Ensure Cron is Enabled.
  4. Test audio:  sudo -u root mpg123 ${GONG_APP_HOME}/gong-ting.mp3
  5. Test doha:   sudo GONG_FORCE_DOHA=1 php ${GONG_APP_HOME}/doha.php
  6. Test gong:   wait for a scheduled minute or insert a schedule row for current HHMM.

EOF
  if [[ "$GONG_CONFIGURE_AP" == "1" ]]; then
    echo "  AP SSID: ${GONG_WIFI_SSID}  IP: ${GONG_AP_ADDRESS}"
    echo "  Connect a phone to the SSID and open http://${GONG_AP_ADDRESS}/"
  else
    echo "  AP not configured. Re-run with: sudo ./installer/install.sh --with-ap"
  fi
  echo
}

main

#!/bin/bash
# Gong-NG first-boot — stage 0 (runs via systemd.run on first power-on).
#
# Flash-time layout:
#   /opt/gong-src/              packed ng/ tree + media-src/ (code + seed + MP3s)
#   /boot/firmware/gong-firstboot.toml
#   cmdline: systemd.run=/boot/firstrun.sh
#
# This stage must not depend on the network. It writes identity + Wi-Fi,
# enables the deferred installer, strips the cmdline hook, and exits 0 so
# systemd.run_success_action=reboot can proceed. Apt/pip run after reboot
# from the card-local offline pool (no internet, no network-online wait).
set +e
BOOT=/boot
[ -d /boot/firmware ] && BOOT=/boot/firmware
mkdir -p /var/log /var/lib/gong-ng
LOG=/var/log/gong-firstrun.log
exec >>"$LOG" 2>&1
echo "=== gong-ng firstrun stage0 $(date -Is 2>/dev/null || date) ==="

CONF=""
for c in "$BOOT/gong-firstboot.toml" /boot/firmware/gong-firstboot.toml /boot/gong-firstboot.toml; do
  [ -f "$c" ] && CONF="$c" && break
done
if [ -z "$CONF" ]; then
  echo "WARN: no gong-firstboot.toml — using compiled defaults"
fi

cfg() {
  # cfg key [default]
  python3 -c '
import sys, tomllib, pathlib
key, default = sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else ""
p = pathlib.Path(sys.argv[3]) if len(sys.argv) > 3 else None
d = {}
if p and p.is_file():
    with p.open("rb") as f:
        d = tomllib.load(f)
cur = d
for part in key.split("."):
    if not isinstance(cur, dict) or part not in cur:
        print(default)
        raise SystemExit(0)
    cur = cur[part]
print("true" if cur is True else "false" if cur is False else cur)
' "$1" "${2:-}" "${CONF:-/dev/null}"
}

HOST=$(cfg unit.hostname dhammagong)
TZNAME=$(cfg unit.timezone Asia/Kolkata)
WIFI_MODE=$(cfg wifi.mode station)
SSID=$(cfg wifi.ssid)
PSK=$(cfg wifi.passphrase)
COUNTRY=$(cfg wifi.country IN)

# --- identity ---
CURRENT_HOSTNAME=$(tr -d ' \t\n\r' < /etc/hostname 2>/dev/null)
echo "$HOST" >/etc/hostname
if [ -n "$CURRENT_HOSTNAME" ]; then
  sed -i "s/127.0.1.1.*${CURRENT_HOSTNAME}/127.0.1.1\t${HOST}/g" /etc/hosts
fi
grep -q "^127.0.1.1" /etc/hosts || echo -e "127.0.1.1\t${HOST}" >>/etc/hosts
timedatectl set-timezone "$TZNAME" 2>/dev/null || {
  echo "$TZNAME" >/etc/timezone
  ln -sfn "/usr/share/zoneinfo/$TZNAME" /etc/localtime
}
systemctl enable ssh 2>/dev/null
mkdir -p /etc/ssh/sshd_config.d
echo 'PasswordAuthentication yes' >/etc/ssh/sshd_config.d/99-gong.conf
touch "$BOOT/ssh" /boot/ssh 2>/dev/null

# --- station or AP wifi (NM keyfile; works on next full boot) ---
raspi-config nonint do_wifi_country "$COUNTRY" 2>/dev/null || true
mkdir -p /etc/wpa_supplicant
if [ ! -f /etc/wpa_supplicant/wpa_supplicant.conf ]; then
  printf 'ctrl_interface=DIR=/var/run/wpa_supplicant GROUP=netdev\nupdate_config=1\ncountry=%s\n' "$COUNTRY" \
    >/etc/wpa_supplicant/wpa_supplicant.conf
else
  grep -q '^country=' /etc/wpa_supplicant/wpa_supplicant.conf \
    || echo "country=$COUNTRY" >>/etc/wpa_supplicant/wpa_supplicant.conf
fi

NMDIR=/etc/NetworkManager/system-connections
mkdir -p "$NMDIR"
if [ "$WIFI_MODE" = "ap" ]; then
  CHANNEL=$(cfg wifi.channel 6)
  cat >"$NMDIR/gong-ap.nmconnection" <<EOF
[connection]
id=gong-ap
type=wifi
interface-name=wlan0
autoconnect=true

[wifi]
mode=ap
ssid=$SSID
channel=$CHANNEL
band=bg

[wifi-security]
key-mgmt=wpa-psk
psk=$PSK
proto=rsn
pairwise=ccmp

[ipv4]
method=shared
address1=192.168.5.1/24

[ipv6]
method=ignore
EOF
  chmod 600 "$NMDIR/gong-ap.nmconnection"
else
  cat >"$NMDIR/${SSID}.nmconnection" <<EOF
[connection]
id=$SSID
type=wifi
interface-name=wlan0
autoconnect=true
autoconnect-priority=100

[wifi]
mode=infrastructure
ssid=$SSID

[wifi-security]
key-mgmt=wpa-psk
psk=$PSK

[ipv4]
method=auto

[ipv6]
method=auto
EOF
  chmod 600 "$NMDIR/${SSID}.nmconnection"
fi

# Keep a root-only copy of the toml for the deferred installer
if [ -n "$CONF" ] && [ -f "$CONF" ]; then
  mkdir -p /etc/gong-ng
  cp -a "$CONF" /etc/gong-ng/firstboot.toml
  chmod 600 /etc/gong-ng/firstboot.toml
fi

# --- defer Gong-NG install until the next full boot (local pool, no Wi-Fi) ---
# Do not run the 100MB+ dpkg here: systemd.run can time out and loop the hook.
if [ -x /usr/local/sbin/gong-ng-firstboot-install ]; then
  systemctl enable gong-ng-install.service 2>/dev/null
  echo "Deferred gong-ng-install.service enabled (offline pool)"
else
  echo "WARN: /usr/local/sbin/gong-ng-firstboot-install missing"
fi

# --- strip cmdline hook so we do not loop ---
for cmd in "$BOOT/cmdline.txt" /boot/cmdline.txt /boot/firmware/cmdline.txt; do
  [ -f "$cmd" ] || continue
  sed -i 's| systemd.run=[^ ]*||g; s| systemd.run_success_action=[^ ]*||g; s| systemd.unit=kernel-command-line.target||g' "$cmd"
  sed -i 's/  */ /g' "$cmd"
done
if [ -f "$BOOT/firstrun.sh" ]; then
  mkdir -p /var/lib/gong-ng
  cp -a "$BOOT/firstrun.sh" /var/lib/gong-ng/firstrun.sh.bak 2>/dev/null
  rm -f "$BOOT/firstrun.sh"
fi
rm -f /boot/firstrun.sh

echo "OK stage0 $(date -Is 2>/dev/null || date)" >/var/lib/gong-ng/stage0.done
echo "=== gong-ng firstrun stage0 done — reboot ==="
exit 0

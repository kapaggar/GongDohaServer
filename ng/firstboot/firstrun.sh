#!/bin/bash
# Gong-NG first-boot provisioning for Raspberry Pi OS Bookworm (Lite).
#
# Stage A (done at flashing time, with internet):
#   - Flash Pi OS Lite with the Imager (hostname dhammagong, SSH on).
#   - Copy to the boot partition: this script, gong-firstboot.toml,
#     gong-ng-bundle.tar.gz (deb pool + wheels + code + seed + media).
#   - Append ' systemd.run=/boot/firstrun.sh' to cmdline.txt.
#
# This script (Stage B) must succeed with NO internet. Logs to
# /boot/firstrun.log. Idempotent: safe to re-run.
#
# ⚠ HW-VALIDATE: nmcli AP mode, ALSA device name, and the RTC overlay must be
# confirmed on the target board before field deployment (design §14, M0).

set -euo pipefail
exec > >(tee -a /boot/firstrun.log) 2>&1
echo "=== gong-ng firstrun $(date -Is) ==="

BOOT=/boot
[ -d /boot/firmware ] && BOOT=/boot/firmware   # Bookworm mounts boot here
CONF="$BOOT/gong-firstboot.toml"
BUNDLE="$BOOT/gong-ng-bundle.tar.gz"
[ -f "$CONF" ] || { echo "missing $CONF"; exit 1; }
[ -f "$BUNDLE" ] || { echo "missing $BUNDLE"; exit 1; }

# --- read firstboot config (python3 + tomllib ship with Bookworm) ----------
cp "$CONF" /tmp/gong-firstboot.toml
cfg() {
    python3 -c '
import sys, tomllib
with open("/tmp/gong-firstboot.toml", "rb") as f:
    d = tomllib.load(f)
for k in sys.argv[1].split("."):
    d = d[k]
print("true" if d is True else "false" if d is False else d)
' "$1"
}

TZNAME=$(cfg unit.timezone)
PIN=$(cfg unit.admin_pin)
SSID=$(cfg wifi.ssid)
PSK=$(cfg wifi.passphrase)
COUNTRY=$(cfg wifi.country)
CHANNEL=$(cfg wifi.channel)
RELAY_HW=$(cfg relay.enabled_hw)
RELAY_GPIO=$(cfg relay.gpio)
RELAY_LOW=$(cfg relay.active_low)
RTC=$(cfg rtc.enabled)

# --- unpack bundle ----------------------------------------------------------
WORK=/tmp/gong-bundle
rm -rf "$WORK"; mkdir -p "$WORK"
tar -xzf "$BUNDLE" -C "$WORK"
# bundle layout: pool/*.deb  wheels/*.whl  code/ (the ng tree)  seed/  media/

# --- packages (offline pool; network apt is best-effort only) ---------------
if ls "$WORK"/pool/*.deb >/dev/null 2>&1; then
    apt-get install -y --no-install-recommends "$WORK"/pool/*.deb || \
        dpkg -i "$WORK"/pool/*.deb || true
fi
# ensure the standalone dnsmasq is absent (NetworkManager runs its own)
apt-get purge -y dnsmasq 2>/dev/null || true

# --- user + directories ------------------------------------------------------
id gong >/dev/null 2>&1 || useradd -r -m -d /var/lib/gong -s /usr/sbin/nologin gong
usermod -aG audio,gpio,systemd-journal gong
install -d -o gong -g gong -m 0750 /var/lib/gong
install -d -o gong -g gong /var/lib/gong/media/gongs /var/lib/gong/media/doha \
    /var/lib/gong/media/deshna

# --- code + venv from vendored wheels ---------------------------------------
rm -rf /opt/gong-ng
mkdir -p /opt/gong-ng
cp -r "$WORK"/code/* /opt/gong-ng/
python3 -m venv /opt/gong-ng/venv
/opt/gong-ng/venv/bin/pip install --no-index \
    --find-links "$WORK/wheels" flask waitress gpiozero lgpio
/opt/gong-ng/venv/bin/pip install --no-index --no-deps /opt/gong-ng
chmod +x /opt/gong-ng/bin/*

# --- config ------------------------------------------------------------------
mkdir -p /etc/gong-ng
sed -e "s|^timezone = .*|timezone = \"$TZNAME\"|" \
    -e "s|^enabled_hw = .*|enabled_hw = $RELAY_HW|" \
    -e "s|^gpio = .*|gpio = $RELAY_GPIO|" \
    -e "s|^active_low = .*|active_low = $RELAY_LOW|" \
    /opt/gong-ng/os/config.toml.example > /etc/gong-ng/config.toml

# --- data: seed + media + PIN -------------------------------------------------
mkdir -p /opt/gong-ng/seed
cp "$WORK"/seed/* /opt/gong-ng/seed/
cp "$WORK"/media/gongs/* /var/lib/gong/media/gongs/
cp "$WORK"/media/doha/*  /var/lib/gong/media/doha/
cp "$WORK"/seed/doha-manifest.json /var/lib/gong/media/doha/manifest.json
chown -R gong:gong /var/lib/gong
sudo -u gong GONG_CONFIG=/etc/gong-ng/config.toml \
    /opt/gong-ng/venv/bin/python -m gong_ng.ctl init
sudo -u gong GONG_CONFIG=/etc/gong-ng/config.toml \
    /opt/gong-ng/venv/bin/python -m gong_ng.ctl reset-pin --pin "$PIN" >/dev/null

# --- time --------------------------------------------------------------------
timedatectl set-timezone "$TZNAME"
if [ "$RTC" = "true" ]; then
    grep -q '^dtoverlay=i2c-rtc' "$BOOT/config.txt" || \
        printf 'dtparam=i2c_arm=on\ndtoverlay=i2c-rtc,ds3231\n' >> "$BOOT/config.txt"
    apt-get purge -y fake-hwclock 2>/dev/null || true
fi

# --- network: AP via NetworkManager (Bookworm default stack) ------------------
raspi-config nonint do_wifi_country "$COUNTRY" || true
nmcli con delete gong-ap 2>/dev/null || true
nmcli con add type wifi ifname wlan0 con-name gong-ap autoconnect yes \
    ssid "$SSID" mode ap ipv4.method shared ipv4.addresses 192.168.5.1/24 \
    wifi.band bg wifi.channel "$CHANNEL" \
    wifi-sec.key-mgmt wpa-psk wifi-sec.psk "$PSK" \
    wifi-sec.proto rsn wifi-sec.pairwise ccmp
systemctl enable avahi-daemon 2>/dev/null || true

# --- firewall, sudoers, services ----------------------------------------------
install -m 0644 /opt/gong-ng/os/nftables.conf /etc/nftables.conf
systemctl enable nftables
install -m 0440 /opt/gong-ng/os/sudoers.d-gong /etc/sudoers.d/gong-ng
install -m 0644 /opt/gong-ng/systemd/gongd.service /etc/systemd/system/
install -m 0644 /opt/gong-ng/systemd/gong-firstboot.service /etc/systemd/system/
# USB Deshna media auto-mount (udev event -> templated helper service)
install -m 0644 /opt/gong-ng/systemd/gong-usb-media@.service /etc/systemd/system/
install -m 0644 /opt/gong-ng/systemd/gong-usb-media-detach@.service /etc/systemd/system/
install -m 0644 /opt/gong-ng/os/udev/99-gong-usb-media.rules /etc/udev/rules.d/
udevadm control --reload-rules 2>/dev/null || true
systemctl daemon-reload
systemctl enable gongd gong-firstboot

# --- cleanup + reboot -----------------------------------------------------------
sed -i 's| systemd.run=[^ ]*||' "$BOOT/cmdline.txt"
shred -u /tmp/gong-firstboot.toml "$CONF" 2>/dev/null || rm -f "$CONF"
echo "=== gong-ng firstrun complete, rebooting ==="
reboot

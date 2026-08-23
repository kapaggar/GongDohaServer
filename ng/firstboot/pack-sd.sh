#!/bin/bash
# Pack an *already flashed* Raspberry Pi OS Bookworm Lite card with Gong-NG.
# Run on Linux (Steam Deck, laptop) as a user who can sudo.
#
#   sudo ./ng/firstboot/pack-sd.sh --device /dev/mmcblk0 \
#       --toml /path/to/gong-firstboot.toml
#
# Copies the vendored offline apt pool + wheels onto the card so firstboot
# does not need the internet. Optional: --last-sec N  grow root only to that
# sector (fake/"limbo" cards). Full procedure: docs/GONG-NG-FLASH.md
set -euo pipefail

DEVICE=""
TOML=""
LAST_SEC=""
REPO=""

usage() {
  sed -n '2,12p' "$0"
  exit 2
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --device) DEVICE="$2"; shift 2 ;;
    --toml) TOML="$2"; shift 2 ;;
    --last-sec) LAST_SEC="$2"; shift 2 ;;
    --repo) REPO="$2"; shift 2 ;;
    -h|--help) usage ;;
    *) echo "Unknown option: $1" >&2; usage ;;
  esac
done

if [[ -z "$DEVICE" ]]; then
  echo "ERROR: --device /dev/mmcblk0 (or /dev/sdX) is required" >&2
  exit 2
fi
if [[ ! -b "$DEVICE" ]]; then
  echo "ERROR: $DEVICE is not a block device" >&2
  exit 1
fi
case "$DEVICE" in
  /dev/nvme*|/dev/zram*)
    echo "ERROR: refusing to write $DEVICE" >&2
    exit 1
    ;;
esac

HERE=$(cd "$(dirname "$0")" && pwd)
if [[ -z "$REPO" ]]; then
  REPO=$(cd "$HERE/../.." && pwd)
fi
if [[ ! -f "$REPO/ng/pyproject.toml" || ! -d "$REPO/app/dhamma" ]]; then
  echo "ERROR: $REPO does not look like GongDohaServer (need ng/ and app/dhamma/)" >&2
  exit 1
fi
if [[ ! -f "$REPO/ng/firstboot/offline/Packages" ]] \
   || ! ls "$REPO/ng/firstboot/offline/pool"/*.deb >/dev/null 2>&1 \
   || ! ls "$REPO/ng/firstboot/offline/wheels"/*.whl >/dev/null 2>&1; then
  echo "ERROR: vendored offline pool missing under ng/firstboot/offline/" >&2
  echo "       On an aarch64 Bookworm Pi: sudo ./ng/firstboot/vendor-offline.sh" >&2
  exit 1
fi
if [[ -z "$TOML" ]]; then
  TOML="$HERE/gong-firstboot.toml"
fi
if [[ ! -f "$TOML" ]]; then
  echo "ERROR: $TOML not found. Copy ng/firstboot/gong-firstboot.toml.example" >&2
  echo "       to gong-firstboot.toml and set wifi.ssid / wifi.passphrase." >&2
  exit 1
fi

if [[ "$DEVICE" == /dev/mmcblk* ]]; then
  BOOT_DEV="${DEVICE}p1"
  ROOT_DEV="${DEVICE}p2"
else
  BOOT_DEV="${DEVICE}1"
  ROOT_DEV="${DEVICE}2"
fi

echo "=== safety ==="
udevadm settle || true
if [[ -r /sys/block/${DEVICE#/dev/}/device/type ]]; then
  echo "device type: $(cat /sys/block/${DEVICE#/dev/}/device/type 2>/dev/null || true)"
fi
lsblk -o NAME,SIZE,FSTYPE,LABEL,MOUNTPOINTS "$DEVICE"

echo "=== unmount ==="
umount "$BOOT_DEV" 2>/dev/null || true
umount "$ROOT_DEV" 2>/dev/null || true
sync

echo "=== grow rootfs ==="
if [[ -n "$LAST_SEC" ]]; then
  echo "Resizing partition 2 to sector $LAST_SEC (usable-capacity cap)"
  parted "$DEVICE" ---pretend-input-tty <<EOF || true
unit s
resizepart 2 ${LAST_SEC}s
Yes
quit
EOF
else
  echo "Resizing partition 2 to 100% of $DEVICE"
  parted -s "$DEVICE" resizepart 2 100%
fi
udevadm settle || true
e2fsck -f -y "$ROOT_DEV"
resize2fs "$ROOT_DEV"

BOOT=$(mktemp -d)
ROOT=$(mktemp -d)
cleanup() {
  umount "$BOOT" 2>/dev/null || true
  umount "$ROOT" 2>/dev/null || true
  rmdir "$BOOT" "$ROOT" 2>/dev/null || true
}
trap cleanup EXIT
mount -o rw "$BOOT_DEV" "$BOOT"
mount -o rw "$ROOT_DEV" "$ROOT"

echo "=== pack /opt/gong-src ==="
mkdir -p "$ROOT/opt/gong-src"
rsync -a --delete \
  --exclude '.venv/' --exclude '__pycache__/' --exclude '*.pyc' \
  --exclude 'screenshots/' --exclude 'tests/' --exclude '.gitignore' \
  "$REPO/ng/" "$ROOT/opt/gong-src/"
mkdir -p "$ROOT/opt/gong-src/media-src/doha"
cp -a "$REPO/app/dhamma/gong-"*.mp3 "$ROOT/opt/gong-src/media-src/"
cp -a "$REPO/app/dhamma/doha/." "$ROOT/opt/gong-src/media-src/doha/"

echo "=== firstboot hooks ==="
install -m 0755 "$REPO/ng/firstboot/firstrun.sh" "$ROOT/boot/firstrun.sh"
install -m 0755 "$REPO/ng/firstboot/firstrun.sh" "$BOOT/firstrun.sh"
install -m 0755 "$REPO/ng/firstboot/gong-ng-firstboot-install" \
  "$ROOT/usr/local/sbin/gong-ng-firstboot-install"
install -m 0644 "$REPO/ng/systemd/gong-ng-install.service" \
  "$ROOT/etc/systemd/system/gong-ng-install.service"
mkdir -p "$ROOT/etc/systemd/system/multi-user.target.wants"
ln -sfn /etc/systemd/system/gong-ng-install.service \
  "$ROOT/etc/systemd/system/multi-user.target.wants/gong-ng-install.service"

install -m 0600 "$TOML" "$BOOT/gong-firstboot.toml"
mkdir -p "$ROOT/etc/gong-ng"
install -m 0600 "$TOML" "$ROOT/etc/gong-ng/firstboot.toml"
touch "$BOOT/ssh"

# Pre-write the NM profile so Wi-Fi is up on the first multi-user boot.
python3 - "$TOML" "$ROOT" <<'PY'
import pathlib, sys, tomllib
toml_path, root = pathlib.Path(sys.argv[1]), pathlib.Path(sys.argv[2])
d = tomllib.loads(toml_path.read_text())
wifi = d.get("wifi", {})
ssid = str(wifi.get("ssid", "")).strip()
psk = str(wifi.get("passphrase", ""))
country = str(wifi.get("country", "IN"))
mode = str(wifi.get("mode", "station"))
channel = wifi.get("channel", 6)
if not ssid or psk in ("", "ChangeMe"):
    raise SystemExit("gong-firstboot.toml wifi.ssid/passphrase must be set")
wpas = root / "etc/wpa_supplicant"
wpas.mkdir(parents=True, exist_ok=True)
(wpas / "wpa_supplicant.conf").write_text(
    "ctrl_interface=DIR=/var/run/wpa_supplicant GROUP=netdev\n"
    f"update_config=1\ncountry={country}\n"
)
nmd = root / "etc/NetworkManager/system-connections"
nmd.mkdir(parents=True, exist_ok=True)
if mode == "ap":
    name = "gong-ap.nmconnection"
    body = f"""[connection]
id=gong-ap
type=wifi
interface-name=wlan0
autoconnect=true

[wifi]
mode=ap
ssid={ssid}
channel={channel}
band=bg

[wifi-security]
key-mgmt=wpa-psk
psk={psk}
proto=rsn
pairwise=ccmp

[ipv4]
method=shared
address1=192.168.5.1/24

[ipv6]
method=ignore
"""
else:
    name = f"{ssid}.nmconnection"
    body = f"""[connection]
id={ssid}
type=wifi
interface-name=wlan0
autoconnect=true
autoconnect-priority=100

[wifi]
mode=infrastructure
ssid={ssid}

[wifi-security]
key-mgmt=wpa-psk
psk={psk}

[ipv4]
method=auto

[ipv6]
method=auto
"""
path = nmd / name
path.write_text(body)
path.chmod(0o600)
print(f"wrote {path} mode={mode} ssid={ssid}")
PY

# Strip stock resize (we already grew the partition) and hook firstrun.
CMD="$BOOT/cmdline.txt"
if [[ ! -f "$CMD" ]]; then
  echo "ERROR: $BOOT/cmdline.txt missing — is this Bookworm Lite?" >&2
  exit 1
fi
sed -i \
  -e 's| init=/usr/lib/raspberrypi-sys-mods/firstboot||g' \
  -e 's| init=/usr/lib/raspberrypi-sys-mods/init_resize.sh||g' \
  -e 's| systemd.run=[^ ]*||g' \
  -e 's| systemd.run_success_action=[^ ]*||g' \
  -e 's| systemd.unit=kernel-command-line.target||g' \
  -e 's/  */ /g' \
  "$CMD"
# systemd.run path is the *rootfs* /boot/firstrun.sh (Bookworm mounts FAT at /boot/firmware)
sed -i 's/[[:space:]]*$//' "$CMD"
printf ' systemd.run=/boot/firstrun.sh systemd.run_success_action=reboot systemd.unit=kernel-command-line.target\n' >>"$CMD"
# cmdline.txt must be a single line
tr '\n' ' ' <"$CMD" | sed 's/  */ /g; s/[[:space:]]*$//' >"$CMD.tmp"
echo >>"$CMD.tmp"
mv "$CMD.tmp" "$CMD"

cat >"$BOOT/GONG-README.txt" <<EOF
Gong-NG packed payload is at /opt/gong-src (includes offline apt pool + wheels).
See docs/GONG-NG-FLASH.md in the git repo.
First boot: firstrun installs from the card (no internet), then reboot; gongd
listens on port 80. Wi-Fi from gong-firstboot.toml is for later admin access.
EOF

echo "=== verify ==="
test -f "$ROOT/opt/gong-src/pyproject.toml"
test -f "$ROOT/opt/gong-src/firstboot/offline/Packages"
test -x "$ROOT/usr/local/sbin/gong-ng-firstboot-install"
test -f "$BOOT/gong-firstboot.toml"
echo "cmdline: $(cat "$CMD")"
du -sh "$ROOT/opt/gong-src"
df -h "$BOOT" "$ROOT"
sync
echo "PACK_OK  $DEVICE"
echo "Unmount complete on exit. Eject the card and boot the Pi."

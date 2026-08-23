#!/bin/bash
# Rebuild ng/firstboot/offline/{pool,Packages,wheels} on an aarch64 Bookworm Pi.
# Needs internet. Run from a clone of this repo:
#
#   sudo ./ng/firstboot/vendor-offline.sh
#
# Then commit the refreshed pool/wheels (or copy them onto the pack host).
set -euo pipefail

if [[ "$(id -u)" -ne 0 ]]; then
  echo "ERROR: run as root (sudo $0)" >&2
  exit 2
fi
if [[ "$(uname -m)" != "aarch64" ]]; then
  echo "ERROR: harvest on aarch64 Bookworm (this host is $(uname -m))" >&2
  exit 2
fi

HERE=$(cd "$(dirname "$0")" && pwd)
OFFLINE="$HERE/offline"
export DEBIAN_FRONTEND=noninteractive

PKGS=(
  python3-venv python3.11-venv python3-pip python3-pip-whl
  python3-setuptools-whl python3-distutils
  python3-gpiozero python3-lgpio python3-colorzero liblgpio1
  python3-flask python3-waitress
  mpv alsa-utils avahi-daemon nftables
)

echo "=== apt download $PKGS ==="
apt-get update
apt-get install --download-only --reinstall -y --no-install-recommends "${PKGS[@]}"
# Pull a few venv pieces that --reinstall may skip if already present as deps
cd /var/cache/apt/archives
for p in python3.11-venv python3-pip-whl python3-setuptools-whl python3-distutils python3-colorzero liblgpio1; do
  apt-get download "$p" || true
done

rm -rf "$OFFLINE/pool"
mkdir -p "$OFFLINE/pool" "$OFFLINE/wheels"
python3 - <<PY
import shutil
from pathlib import Path
src = Path("/var/cache/apt/archives")
dest = Path("$OFFLINE/pool")
best = {}
for p in src.glob("*.deb"):
    name = p.name.split("_", 1)[0]
    prev = best.get(name)
    if prev is None or p.stat().st_mtime >= prev.stat().st_mtime:
        best[name] = p
for p in best.values():
    shutil.copy2(p, dest / p.name)
print(f"copied {len(best)} unique debs -> {dest}")
PY

if ! command -v dpkg-scanpackages >/dev/null; then
  apt-get install -y --no-install-recommends dpkg-dev
fi
cd "$OFFLINE"
dpkg-scanpackages pool /dev/null > Packages
gzip -9c Packages > Packages.gz

echo "=== wheels (aarch64 / py3) ==="
PIP=pip3
if [[ -x /opt/gong-ng/venv/bin/pip ]]; then
  PIP=/opt/gong-ng/venv/bin/pip
elif ! command -v pip3 >/dev/null; then
  python3 -m pip --version >/dev/null
  PIP="python3 -m pip"
fi
# shellcheck disable=SC2086
$PIP download -d "$OFFLINE/wheels" flask waitress gpiozero lgpio

echo "=== result ==="
du -sh "$OFFLINE" "$OFFLINE/pool" "$OFFLINE/wheels"
echo "VENDOR_OK  $OFFLINE"

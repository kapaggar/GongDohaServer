# Flash a new SD card for Gong-NG

Repeatable path from a **blank microSD** to a running appliance
(`gongd` + PIN UI on port 80). Target: Raspberry Pi **3 / 4 / 5 / Zero 2 W**,
**Raspberry Pi OS Bookworm Lite 64-bit**.

The clone already vendors Bookworm **arm64** `.deb`s and CPython 3.11 wheels
under `ng/firstboot/offline/`. After you flash Lite and run `pack-sd.sh`,
**firstboot does not use apt or PyPI**. Wi-Fi in the toml is only so you can
reach the UI later — the install itself is from the card.

---

## What you need

| Item | Notes |
|------|--------|
| microSD | 8 GB+ **real** capacity. A “125G” card that is actually ~11G still works if you cap the resize (below). |
| Host | Linux box with the card reader (Steam Deck is fine) and `sudo`. |
| This repo | Branch `gong-ng`, including `ng/firstboot/offline/`. |
| Pi OS image | Bookworm **Lite 64-bit** (legacy/oldstable), not Trixie Desktop. Download **once**; reuse the `.img.xz`. |
| Raspberry Pi Imager | Deck: `~/Applications/rpi-imager.AppImage`. Official: [raspberrypi.com/software](https://www.raspberrypi.com/software/). |
| Wi-Fi (optional at install) | Station SSID + passphrase in `gong-firstboot.toml` so you can open the UI on the LAN. `mode = "ap"` for a centre AP. Never commit the real file. |

---

## 1. Flash Bookworm Lite

Download (example, dates change — use the current *Legacy 64-bit Lite* from the [Imager OS list](https://downloads.raspberrypi.com/os_list_imagingutility_v4.json)):

```text
Raspberry Pi OS (Legacy, 64-bit) Lite   — Debian Bookworm, no desktop
```

Keep the `.img.xz` on the pack host. You do **not** need a network on the Pi
after this.

**Imager GUI** (Desktop Mode on the Deck): hostname `dhammagong`, enable SSH,
create user `pi` with a password you will keep, set locale/timezone if you want
(firstboot also sets `Asia/Kolkata` from the toml). Do **not** skip the user —
Bookworm will not boot headless without one.

**Imager CLI** (headless Deck; `QT_QPA_PLATFORM=offscreen`):

```bash
export QT_QPA_PLATFORM=offscreen LANG=C.UTF-8
sudo --preserve-env=QT_QPA_PLATFORM,LANG \
  ~/Applications/rpi-imager.AppImage --cli \
  --enable-writing-system-drives \
  --disable-eject \
  --first-run-script /dev/null \
  2026-06-18-raspios-bookworm-arm64-lite.img.xz \
  /dev/mmcblk0
```

`--enable-writing-system-drives` is required on the Deck: the SD slot shows
`RM=0`. Confirm `lsblk` that you are writing **`mmcblk0`**, never `nvme0n1`.

After the write, the card has `bootfs` (FAT ~512M) and `rootfs` (ext4 ~2G).
Leave it in the reader for step 3.

---

## 2. Write `gong-firstboot.toml`

```bash
cd /path/to/GongDohaServer
cp ng/firstboot/gong-firstboot.toml.example ng/firstboot/gong-firstboot.toml
# edit: wifi.ssid, wifi.passphrase, unit.admin_pin, timezone
```

`ng/firstboot/gong-firstboot.toml` is gitignored. Typical station (join LAN):

```toml
[unit]
hostname = "dhammagong"
timezone = "Asia/Kolkata"
admin_pin = "4321"

[wifi]
mode = "station"
ssid = "YourWifiSsid"
passphrase = "YourWifiPass"
country = "IN"

[relay]
enabled_hw = true
gpio = 17
active_low = true
```

`mode = "ap"` instead makes SSID a centre AP at `192.168.5.1`.

---

## 3. Pack Gong-NG onto the card

This copies `ng/` (code + **offline pool/wheels**) + gong/doha MP3s to
`/opt/gong-src`, installs firstboot hooks, writes the NetworkManager Wi-Fi
profile, **grows rootfs** (stock 2G image is not enough), and strips the Pi OS
resize hook so it cannot expand into fake flash.

```bash
# Real card — grow to 100% of the device:
sudo ./ng/firstboot/pack-sd.sh \
  --device /dev/mmcblk0 \
  --toml ng/firstboot/gong-firstboot.toml

# Counterfeit / "limbo" card (f3probe usable last sector), e.g. 10.91G:
sudo ./ng/firstboot/pack-sd.sh \
  --device /dev/mmcblk0 \
  --toml ng/firstboot/gong-firstboot.toml \
  --last-sec 22877183
```

Unmount is automatic. Eject the card.

`pack-sd.sh` also `touch`es `/boot/ssh` so SSH is on even if Imager
customization was skipped (you still need a `pi` user from the flash).
It refuses to pack if `ng/firstboot/offline/` is missing.

---

## 4. Boot the Pi

1. **Stage 0** (`firstrun.sh` via `systemd.run`): hostname, SSH, timezone,
   Wi-Fi keyfile, enable `gong-ng-install.service`, reboot. No network.
2. **Stage 1** (after reboot, `local-fs` only): `dpkg`/`pip` from the card
   pool, `gongctl init`, start `gongd`. Still no internet.

Wait a couple of minutes on the second boot while ~180 packages unpack. Then:

```bash
ssh pi@dhammagong.local
# or ssh pi@<dhcp-ip>   (or 192.168.5.1 in AP mode)

systemctl is-active gongd
sudo -u gong GONG_CONFIG=/etc/gong-ng/config.toml \
  /opt/gong-ng/venv/bin/python -m gong_ng.ctl status --check
```

UI: `http://<pi-ip>/` — PIN from the toml (`4321` unless you changed it).

| Log | What |
|-----|------|
| `/var/log/gong-firstrun.log` | Stage 0 |
| `/var/log/gong-firstboot-install.log` | Installer |
| `journalctl -u gong-ng-install.service` | systemd wrapper |
| `journalctl -u gongd` | daemon |

---

## 5. If install failed

Do **not** leave a half-install marked done. The script only writes
`/var/lib/gong-ng/install.done` after the venv imports and `gongctl init`
succeed (`gongd` must also be active, unless it ran inside `systemd.run`).

```bash
sudo rm -f /var/lib/gong-ng/install.done
sudo systemctl start gong-ng-install.service
journalctl -u gong-ng-install.service -n 80
tail -100 /var/log/gong-firstboot-install.log
```

The installer should not need a network. If `ng/firstboot/offline/` was
not on the card (old pack), refresh the clone and re-pack.

---

## 6. After it is healthy

- Change the UI PIN and the `pi` password.
- Plug speakers; dashboard **Test gong** (ALSA device still HW-VALIDATE per Pi model).
- Optional amp relay: BCM 17 / board pin 11, `enabled_hw` in `/etc/gong-ng/config.toml`.
- Deshna library: USB stick with top-level `deshna/`, or the Deshna tab.

Break-glass PIN: `sudo -u gong GONG_CONFIG=/etc/gong-ng/config.toml /opt/gong-ng/venv/bin/python -m gong_ng.ctl reset-pin`

---

## Layout the pack step writes

```text
/opt/gong-src/                          ng/ tree + media-src/{gong-*.mp3,doha/}
/opt/gong-src/firstboot/offline/        Packages + pool/*.deb + wheels/*.whl
/usr/local/sbin/gong-ng-firstboot-install
/etc/systemd/system/gong-ng-install.service
/etc/gong-ng/firstboot.toml             root-only copy of secrets
/boot/firmware/gong-firstboot.toml
/boot/firmware/ssh
/etc/NetworkManager/system-connections/<ssid>.nmconnection
```

After a successful install: `/opt/gong-ng/` (venv + code), `/var/lib/gong/`,
`gongd.service` enabled, FAT toml shredded.

---

## Refreshing the offline pool

On an aarch64 Bookworm Pi with internet (once):

```bash
sudo ./ng/firstboot/vendor-offline.sh
```

That rewrites `ng/firstboot/offline/{pool,Packages,wheels}`. Commit the result
on the pack host if you want every clone to stay offline-capable.

---

## Counterfeit SD cards

`f3probe --destructive /dev/mmcblk0` reports **limbo** cards (advertise 125G,
usable ~11G). Writes past the real end corrupt the filesystem (journal dies
immediately). Always pass `--last-sec` from f3probe. Do not let any tool
“expand to the whole disk.”

---

## Not this flow

| Path | Use |
|------|-----|
| `docs/FIRSTRUN.md` + `installer/install.sh` | Legacy PHP/LAMP Gongserver (`main`) |
| `docker pull kapilgit/gong-ng` | UI demo, **dummy audio**, not a centre unit |

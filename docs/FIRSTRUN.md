# First-boot provisioning (`firstrun.sh`)

Complete first-boot flow for turning a **fresh Raspberry Pi OS image** into a Gongserver.

## Stages

| Stage | When | What |
|-------|------|------|
| **0** | `firstrun.sh` on first boot | Hostname, SSH, `pi` user, timezone, optional client Wi‑Fi |
| **1 (deferred)** | After reboot / `network-online` | `installer/install.sh` → LAMP + app + optional AP |
| **1 (immediate)** | Still inside firstrun | Same install (less reliable if no network yet) |

Default mode is **`deferred`** (recommended).

```text
Power on
  → resize rootfs (stock cmdline init_resize)
  → firstrun.sh (stage 0 + schedule install)
  → reboot (systemd.run_success_action=reboot)
  → multi-user + network
  → gongserver-firstboot.service runs install.sh
  → UI at http://192.168.5.1/ (if AP) or LAN IP
```

## Layout on the boot partition (FAT)

Copy these onto the SD **boot** volume before first power-on:

```text
/boot/   (or /boot/firmware on Bookworm)
├── firstrun.sh                 # from boot/firstrun.sh
├── gong-firstrun.env           # from boot/gong-firstrun.env.example (edit!)
├── cmdline.txt                 # stock + systemd.run=… fragment
└── gongserver/                 # full copy of this git repository
    ├── installer/install.sh
    ├── config.env              # installer secrets (recommended)
    ├── app/
    ├── db/
    └── …
```

### Prepare on a Mac

```bash
# After flashing Pi OS to the SD card, the boot volume mounts (e.g. /Volumes/bootfs)
BOOT=/Volumes/bootfs   # or bootfs / boot — check Finder

cp /Users/wizops/gongserver/boot/firstrun.sh "$BOOT/"
chmod +x "$BOOT/firstrun.sh"

cp /Users/wizops/gongserver/boot/gong-firstrun.env.example "$BOOT/gong-firstrun.env"
# edit hostname, Wi-Fi, password hash, AP settings
nano "$BOOT/gong-firstrun.env"

# Full payload for offline-capable install (needs network for apt unless pre-baked)
rsync -a --exclude .git --exclude docker \
  /Users/wizops/gongserver/ "$BOOT/gongserver/"

# config for installer
cp /Users/wizops/gongserver/config.env.example "$BOOT/gongserver/config.env"
nano "$BOOT/gongserver/config.env"   # set GONG_DB_PASS, AP passphrase

# Append firstrun to cmdline.txt (keep existing root=PARTUUID=…)
# See boot/cmdline.txt.example
```

### `cmdline.txt` fragment

Append (single line, space-separated):

```text
systemd.run=/boot/firstrun.sh systemd.run_success_action=reboot systemd.unit=kernel-command-line.target
```

On Bookworm with firmware mount:

```text
systemd.run=/boot/firmware/firstrun.sh systemd.run_success_action=reboot systemd.unit=kernel-command-line.target
```

## Configuration (`gong-firstrun.env`)

| Variable | Default | Meaning |
|----------|---------|---------|
| `GONG_HOSTNAME` | `DhammaGong` | System hostname |
| `GONG_TIMEZONE` | `Asia/Kolkata` | Timezone |
| `GONG_ENABLE_SSH` | `1` | Enable SSH |
| `GONG_PI_PASSWORD_HASH` | empty | `chpasswd -e` hash; skip if empty |
| `GONG_CLIENT_WIFI_SSID` | empty | Optional station Wi‑Fi (for apt) |
| `GONG_CLIENT_WIFI_PSK` | empty | Passphrase or 64-char hex PSK |
| `GONG_FIRSTRUN_MODE` | `deferred` | `deferred` or `immediate` |
| `GONG_CONFIGURE_AP` | `1` | Centre AP after install |
| `GONG_NETWORK_WAIT` | `180` | Seconds to wait for network |
| `GONG_REBOOT_AFTER_INSTALL` | `0` | Reboot when deferred install ends |

Generate a password hash:

```bash
openssl passwd -5 'YourPassword'    # sha256crypt $5$…
# or
openssl passwd -6 'YourPassword'    # yescrypt/sha512 depending on openssl
```

## Logs & status

| Path | Purpose |
|------|---------|
| `/var/log/gong-firstrun.log` | Stage 0 log |
| `/var/log/gong-firstboot-install.log` | Stage 1 (deferred) log |
| `/boot/gong-firstrun.status` | Short status visible from Mac if you remount boot |
| `/var/lib/gongserver/firstrun.done` | Success marker (prevents re-install) |

```bash
# On the Pi after first boots:
cat /boot/gong-firstrun.status
tail -100 /var/log/gong-firstrun.log
tail -100 /var/log/gong-firstboot-install.log
systemctl status gongserver-firstboot.service
```

## Manual retry

If stage 1 failed (no network, missing packages):

```bash
sudo /usr/local/sbin/gongserver-firstboot-install
# or
cd /opt/gongserver
sudo ./installer/install.sh --with-ap
```

## Safety notes

- `firstrun.sh` uses `set +e` so a failed step still allows boot/reboot.
- Boot hooks are removed after stage 0 so you do not loop forever.
- **Do not commit real passwords** into `gong-firstrun.env` / `config.env` if the repo is shared.
- AP mode (`GONG_CONFIGURE_AP=1`) matches centre use (SSID `DhammaGong`, `192.168.5.1`).

## Relation to old DIPI firstrun

The earlier DIPI script only did hostname/`pi`/SSH/client Wi‑Fi `Searching` and deleted itself.  
This version keeps that stage-0 idea and **adds** payload discovery + full Gongserver install via `installer/install.sh`.

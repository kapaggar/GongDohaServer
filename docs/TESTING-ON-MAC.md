# Testing Gongserver on a Mac (no Raspberry Pi)

You **cannot** fully validate `install.sh` hardware/AP behaviour without a Pi, but you **can** validate almost all application logic with Docker.

## What you can test on Mac

| Layer | How |
|-------|-----|
| Admin UI | Browser → `http://127.0.0.1:8080/` |
| MariaDB schema / schedules | Docker DB + phpMyAdmin-like mysql CLI |
| `poll.php` gong logic | Run inside container; arm a schedule for “now” |
| `doha.php` track selection | `GONG_FORCE_DOHA=1` any hour |
| Audio decode | `mpg123` plays MP3s inside container (may be silent if no ALSA sink — still exits 0) |
| Logs | `/var/log/gong.log` in container |

## What you cannot test on Mac

| Layer | Why |
|-------|-----|
| `sudo ./installer/install.sh` real path | Needs Debian/Raspberry Pi OS packages & systemd |
| hostapd / centre Wi‑Fi AP | Needs Wi‑Fi chipset + hostapd |
| GPIO relay | Needs RPi.GPIO + pin 11 |
| True Pi audio jack / HDMI audio | Container ALSA ≠ Pi hardware |
| omxplayer path | Legacy Pi-only; we use mpg123 |

---

## Fast path (recommended)

Requires [Docker Desktop](https://www.docker.com/products/docker-desktop/) running.

```bash
cd /Users/wizops/gongserver

chmod +x scripts/mac-test.sh
./scripts/mac-test.sh up      # build + start (first time ~1–2 min)
./scripts/mac-test.sh test    # automated smoke tests
```

Open: **http://127.0.0.1:8080/**

### Manual checks in the UI

1. Confirm page shows **DhammaGong** and current date/time  
2. Toggle Gong/Doha/Amplifier → **Save Settings**  
3. **Set Zero Date** to today, course type 10 Day  
4. **Add course** with a future date  
5. Scroll to **Log Entries** after running gong/doha commands below  

### Trigger a gong immediately

```bash
./scripts/mac-test.sh arm-gong   # schedule row for current minute
./scripts/mac-test.sh gong       # run poll.php
./scripts/mac-test.sh logs
```

### Trigger a doha immediately

```bash
./scripts/mac-test.sh doha
```

### Stop

```bash
./scripts/mac-test.sh down
# wipe DB volume too:
./scripts/mac-test.sh destroy
```

---

## Architecture of the Mac test stack

```text
Browser ──► localhost:8080 ──► web (php:8.2-apache)
                                   │
                                   ├── /home/dhamma  (your app, mounted RO)
                                   ├── poll.php / doha.php
                                   └── mysqli ──► db:3306 (MariaDB)
                                         ▲
Mac tools ──► localhost:3307 ────────────┘
```

Compose file: `docker-compose.yml`  
Helper: `scripts/mac-test.sh`

---

## Optional: test PHP syntax without Docker

```bash
cd /Users/wizops/gongserver
php -l app/dhamma/constants.inc
php -l app/dhamma/poll.php
php -l app/dhamma/doha.php
php -l app/www/index.php
```

This only checks syntax, not DB/runtime.

---

## Optional: “almost Pi” with a VM

If you want to exercise **`install.sh`** without buying hardware:

1. Install [UTM](https://mac.getutm.app/) or QEMU  
2. Run **Raspberry Pi OS** (or Debian arm64) VM  
3. Copy the repo into the VM  
4. `sudo ./installer/install.sh --skip-ap`  
5. Still skip real GPIO/AP unless you attach USB Wi‑Fi and accept limited fidelity  

Docker is faster for day-to-day app work; a Pi OS VM is better for installer regression.

---

## When you eventually get a Pi

1. Flash Raspberry Pi OS  
2. Copy repo, `config.env`, `sudo ./installer/install.sh`  
3. Use `docs/DEPLOY.md` checklist  
4. Compare behaviour to Docker tests you already trust  

# DhammaGong / Gongserver

Raspberry Pi **LAMP appliance** that auto-schedules **gong (bell)** and **doha (MP3)** playback for Vipassana courses.

This repository packages:

1. **Application code** (PHP poller, doha player, admin UI, relay script)
2. **Media** (gong + 11 doha tracks)
3. **Database schema** (course types, schedules, settings)
4. **OS config templates** (cron, sudoers, hostapd, dnsmasq, logrotate)
5. **Installer** that turns a **fresh Raspberry Pi OS** into a working Gongserver

Derived from a production image (`hostname: DhammaGong`, Raspbian Buster) with portable fixes for modern Pi OS.

---

## Test on a Mac (no Pi required)

Uses Docker for LAMP + app logic (not hostapd/GPIO/real Pi audio):

```bash
cd /Users/wizops/gongserver   # or your clone path
./scripts/mac-test.sh up
./scripts/mac-test.sh test
# UI → http://127.0.0.1:8080/
```

Details: [docs/TESTING-ON-MAC.md](docs/TESTING-ON-MAC.md)

## Quick start (on a Raspberry Pi)

```bash
# After copying this repo onto the Pi:
cd gongserver
cp config.env.example config.env
# edit GONG_DB_PASS (and AP settings if needed)
sudo ./installer/install.sh
```

Open the admin UI: `http://<pi-ip>/`

Optional centre Wi‑Fi AP (use ethernet while installing):

```bash
sudo ./installer/install.sh --with-ap
```

Full steps: [docs/DEPLOY.md](docs/DEPLOY.md)

---

## Repository layout

```text
gongserver/
├── README.md
├── config.env.example          # copy → config.env (not committed)
├── app/
│   ├── dhamma/                 # → installed to /home/dhamma
│   │   ├── constants.inc
│   │   ├── poll.php            # gong every minute
│   │   ├── doha.php            # doha at 06:37
│   │   ├── set-zero-day.php
│   │   ├── check-date
│   │   ├── relay-control       # GPIO amp relay
│   │   ├── gong-*.mp3
│   │   └── doha/*.mp3
│   └── www/index.php           # → /var/www/html
├── db/gong.sql                 # schema + schedules seed
├── os/                         # config templates applied by installer
├── installer/install.sh        # main entrypoint
└── docs/
    ├── DEPLOY.md
    └── OS-DELTAS.md            # what stock OS gains
```

---

## How it works

```text
cron (root)
  ├─ every minute  → poll.php  → schedule match? → play gong N times
  ├─ 06:37         → doha.php  → pick track for course day → play
  ├─ 08/14/16:00   → set-zero-day.php
  └─ optional      → check-date (NTP)
admin UI (Apache+PHP) → MariaDB `gong` → settings / courses / schedule
optional: hostapd AP 192.168.5.1 + dnsmasq DHCP
```

See also the forensic docs from the original image analysis if present under your `GongRootfsFiles/README/`.

---

## Configuration

| Item | Where |
|------|--------|
| Install secrets / AP | `config.env` (from example) |
| Runtime DB + player | `/etc/gongserver/config.inc.php` (written by installer) |
| Course / enable / volume | Web UI |
| Gong times | MariaDB `schedule` table |

---

## Requirements

| Component | Notes |
|-----------|--------|
| OS | Raspberry Pi OS Bullseye/Bookworm (Debian-based) |
| Packages | apache2, mariadb, php, mpg123, … (installer) |
| Audio | ALSA device working (`mpg123 file.mp3`) |
| Optional | hostapd Wi‑Fi AP, GPIO relay |

**Not** a full SD-card disk image: it configures a live system. For cloning many units, install once then `dd` the card, or re-run the installer on each Pi.

---

## Security

- UI is **unauthenticated** (centre AP threat model).
- Change default DB and Wi‑Fi passwords in `config.env`.
- `config.env` is gitignored — do not commit secrets.
- Media may be centre-sensitive; keep the repo private if needed.

---

## License / media

Source code, configuration, installer, schema, and docs are licensed under the
**MIT License** — see [LICENSE](LICENSE).

**The audio is not MIT-licensed.** The gong and doha MP3s under `app/dhamma/`
remain the property of their original rights holders (Vipassana Research
Institute / the course tradition). Redistribute or reuse the audio only as those
rights holders permit. See the NOTICE section at the bottom of [LICENSE](LICENSE).

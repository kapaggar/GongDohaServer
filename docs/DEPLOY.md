# Deploy guide

## Prerequisites

- Raspberry Pi (2/3/4/5 or Zero 2 recommended)
- Fresh **Raspberry Pi OS** (Bookworm or Bullseye, 32- or 64-bit)
- Network during install (ethernet strongly preferred)
- ~1 GB free disk (media + packages)

## Install

```bash
# On the Pi — copy this repo (USB, scp, or git clone)
cd /home/pi
# scp -r gongserver pi@<ip>:
cd gongserver

cp config.env.example config.env
nano config.env   # set GONG_DB_PASS, Wi‑Fi secrets if using AP

sudo ./installer/install.sh
```

### With centre Wi‑Fi AP (like original image)

Use **ethernet SSH** first, then:

```bash
sudo ./installer/install.sh --with-ap
```

Or set `GONG_CONFIGURE_AP=1` in `config.env`.

After AP is up:

1. Join SSID from `config.env` (`DhammaGong` by default)
2. Open `http://192.168.5.1/`

### Without AP (LAN mode)

```bash
sudo ./installer/install.sh --skip-ap
```

Open `http://<pi-lan-ip>/`.

## Verify

```bash
# Services
systemctl status apache2 mariadb cron

# HTTP
curl -I http://127.0.0.1/

# DB
sudo mysql gong -e 'SELECT * FROM settings\G'

# Manual gong sound
mpg123 /home/dhamma/gong-ting.mp3

# Force doha (ignores hour-of-day for testing)
sudo GONG_FORCE_DOHA=1 php /home/dhamma/doha.php

# Log
tail -f /var/log/gong.log
```

## Re-deploy app only

After editing files in the git repo on the Pi:

```bash
sudo ./installer/install.sh --skip-packages --skip-db
```

## Hardware

| Connection | Notes |
|------------|--------|
| Audio out | 3.5mm or HDMI → PA |
| GPIO BOARD pin 11 | Relay for amplifier (optional) |
| Wi‑Fi | Built-in for AP mode |

## Rollback

There is no automatic uninstall. Rough reverse:

```bash
sudo rm -f /etc/cron.d/gongserver
sudo systemctl disable --now hostapd dnsmasq
sudo rm -rf /home/dhamma /etc/gongserver
# drop database
sudo mysql -e 'DROP DATABASE gong; DROP USER gong@localhost;'
```

## Security notes

- Admin UI has **no login** — only safe on a private AP or trusted LAN.
- Change `GONG_DB_PASS` and Wi‑Fi passphrase before production use.
- Do not expose port 80 to the public internet.

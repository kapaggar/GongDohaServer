# OS deltas vs stock Raspberry Pi OS

This document lists what the **original DhammaGong image** changed relative to a stock Raspbian Buster lite install, and how the **installer** reproduces them.

## Packages added (original)

| Area | Packages |
|------|----------|
| Web | apache2, libapache2-mod-php7.3, php7.3-* |
| DB | mariadb-server 10.3, phpmyadmin |
| Audio | omxplayer, alsa-utils |
| GPIO | python-rpi.gpio / python3 |
| AP | hostapd, dnsmasq |
| Time | ntpdate, fake-hwclock |
| Net | dhcpcd static wlan0 |

**Installer modern equivalent:** apache2, mariadb-server, php + php-mysql, mpg123 (not omxplayer), hostapd/dnsmasq optional, python3-rpi.gpio.

## Files / paths introduced (original)

| Path | Purpose |
|------|---------|
| `/home/dhamma/*` | App + MP3s + relay |
| `/var/www/html/index.php` | Admin UI |
| `/var/lib/mysql/gong/` | Database |
| `/var/log/gong.log` | App log |
| `/etc/crontab` lines | poll / doha / zero-day / check-date |
| `/etc/hostapd/hostapd.conf` | SSID DhammaGong |
| `/etc/network/interfaces.d/dhamma` | wlan0 192.168.5.1 |
| `/etc/dnsmasq.conf` DHCP range | 192.168.5.5–50 |
| `/etc/sudoers.d/020_www-data-nopasswd` | date + hwclock |
| `/etc/timezone` | Asia/Kolkata |
| hostname | DhammaGong |

## Installer mapping

| Original | Installer |
|----------|-----------|
| crontab in `/etc/crontab` | `/etc/cron.d/gongserver` |
| DB root password in PHP | dedicated user `gong` + `/etc/gongserver/config.inc.php` |
| omxplayer | mpg123 (configurable) |
| hostapd always | optional `--with-ap` |
| phpMyAdmin | optional `GONG_INSTALL_PHPMYADMIN=1` |
| hardcoded secrets | `config.env` |

## Behaviour fixes shipped in this repo

- Honour `doha_enabled` / `gong_enabled`
- `check-date` run as shell (not php)
- Prepared statements in UI / workers (where rewritten)
- Disable Cron button in UI
- Load zero_day into form
- Portable audio backend

## Not automated

- Cloning SD card bit-for-bit
- Migrating live `courses` rows from an old device (export SQL manually)
- GPIO wiring (hardware still required)

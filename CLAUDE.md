# CLAUDE.md - Gongserver (DhammaGong)

Context for Claude Code sessions working in this repo. Keep this current when architecture or open items change.

## What this is

Raspberry Pi **LAMP appliance** that auto-schedules **gong (bell)** and **doha (MP3)** playback for Vipassana meditation courses. Derived from a production Raspbian Buster image (`hostname: DhammaGong`) and re-packaged as a deployable repo (installer + Docker test harness) with portable fixes for modern Pi OS.

Not a disk image — the installer configures a live Debian/Raspberry Pi OS system.

## Architecture

```
cron (root)
  ├─ every minute → poll.php        → schedule match for (course_type, day, HHMM)? → play gong N times
  ├─ 06:37        → doha.php         → pick doha track for the course day → play once
  ├─ 08/14/16:00  → set-zero-day.php → check_zero_day(): set settings.zero_day when a course starts
  └─ optional     → check-date       → NTP sync
admin UI (Apache + PHP, app/www/index.php) → MariaDB `gong`
optional: hostapd AP 192.168.5.1 + dnsmasq DHCP (centre Wi-Fi)
optional: GPIO relay (relay-control) powers an amplifier on/off around playback
```

The **zero day** is course day 0 (arrival day). All scheduling is computed as
`current_day = floor((now - zero_day) / 86400)`, then the `schedule` table is
matched by `(type, day_no, start_time)` where `start_time = HHMM` encoded as
`hour*100 + minute` (matches PHP `date("Gi")`).

## Gong-NG rewrite (branch gong-ng)

`ng/` holds the next-gen appliance: one Python 3.11 daemon (`gongd` =
scheduler + player + Flask admin UI threads), SQLite WAL, mpv/dummy audio,
NetworkManager AP. Design: `docs/GONG-NG-DESIGN.md`; dev quickstart and status:
`ng/README.md`. Deployment is fresh-flash + build-time seed (`ng/seed/seed.sql`,
generated from `db/gong.sql` by `ng/tools/convert_legacy_seed.py` — regenerate
after editing either, `tests/test_seed.py` pins them). Tests:
`cd ng && .venv/bin/pytest`. The legacy PHP tree below stays untouched until
the M4 pilot passes.

## Layout (legacy appliance)

- `app/dhamma/` → installed to `/home/dhamma` on the Pi
  - `constants.inc` — shared config + all helpers (`db_connect`, `logit`, `check_zero_day`, `play_mp3`, `kill_players`, `relay_on/off`, `doha_volume_percent`, `show_log`)
  - `poll.php` — gong scheduler (runs every minute)
  - `doha.php` — morning doha player (runs 06:37; requires hour==6 unless `GONG_FORCE_DOHA=1`)
  - `set-zero-day.php` — thin wrapper over `check_zero_day()`
- `app/www/index.php` — admin UI (single page; **unauthenticated by design** — centre-AP threat model)
- `db/gong.sql` — schema + seed (course_types, schedule, one settings row)
- `docker/` — `Dockerfile`, `config.inc.php` (test override), local web image
- `os/` — config templates applied by installer (apache, crontab.gong, dnsmasq, hostapd, logrotate, network, sudoers, sysctl)
- `installer/install.sh` (+ `installer/lib`) — main entrypoint
- `scripts/mac-test.sh`, `scripts/test-audio.sh` — local harness
- `docs/DEPLOY.md`, `docs/OS-DELTAS.md`, `docs/TESTING-ON-MAC.md`

## Config resolution

`constants.inc` defines defaults, then `require_once "/etc/gongserver/config.inc.php"` overrides if present.
- On the Pi, the installer writes `/etc/gongserver/config.inc.php`.
- In Docker, `docker/config.inc.php` is mounted there and reads `GONG_*` env vars; sets `AUDIO_PLAYER=dummy` + `GONG_AUDIO_DUMMY=1` (mpg123 decode-only, no ALSA).

`play_mp3()` supports three players: `mpg123` (default/preferred), `mpv`, `omxplayer` (legacy Buster). Volume is applied via `amixer` (and `--volume`/keypresses for mpv/omxplayer). Dummy mode decodes only.

## DB schema notes (db/gong.sql)

- `settings` — exactly **one row** (id=1). Columns: `zero_day` varchar(10), `course_type`, `repeat_delay`, `enabled`, `relay`, `doha_enabled`, `gong_enabled`, `doha_vol` (0–9), `gong_track` ('ting'|'drum'). All UI `UPDATE settings` statements omit `WHERE` and rely on this single-row invariant.
- `course_types` — `ct_id, ct_name, ct_days, ct_anapana_days`. `ct_days` is the last course day index (e.g. "10 Day" = 11).
- `courses` — `c_id, c_type, c_date` (upcoming course start dates).
- `schedule` — `type, day_no, start_time, total_repeat`. `type=-1, day_no=-1` is the "no course" default schedule. `day_no=2` acts as the generic mid-course fallback (see poll.php).

## Local testing (Mac, no Pi)

```bash
./scripts/mac-test.sh up       # build + start (http://127.0.0.1:8080/)
./scripts/mac-test.sh arm-gong # insert a schedule row for the current minute
./scripts/mac-test.sh gong     # run poll.php in the web container
./scripts/mac-test.sh doha     # run doha.php (GONG_FORCE_DOHA lets it run any hour)
./scripts/mac-test.sh logs     # container + /var/log/gong.log
./scripts/mac-test.sh down
```

`php -l` lints all files clean. There is no PHP unit-test suite.

## Conventions

- All SQL that takes user input uses `mysqli_prepare` + bound params; UI output is `htmlspecialchars`'d; shell args use `escapeshellarg`/`escapeshellcmd`. Preserve this.
- `HHMM` encoding via `date("Gi")` == `hour*100 + minute` — keep schedule `start_time` values consistent with that.
- The UI is intentionally unauthenticated; do not add half-measures — if hardening is wanted, discuss the threat model first.

## Open findings (bug analysis, 2026-07-12) — NOT yet fixed

Full write-up in `NEXT-SESSION.md`. Ranked:

1. **`check_zero_day()` misses courses that don't start "today"** (`constants.inc:53-74`). Only sets `zero_day` when `c_date == today`; if the start-day cron is missed (power off), the running course is invisible (`c_date < today`) and gongs use a stale zero day all course. Fix: match the active course window instead of `== today`.
2. **Disabled cron spams log + exits non-zero every minute** (`poll.php:22-25`). Should be silent `exit(0)` like the `gong_enabled` branch right below it. (`doha.php:36-39` same pattern, once/day.)
3. **"Set Date" regex accepts impossible times** (`index.php:59`) — `[0-9]{2}:[0-9]{2}` allows `99:99`, passed to `sudo date -s` (escaped, so not injection, but corrupts the clock). Tighten to `([01][0-9]|2[0-3]):[0-5][0-9]`.
4. **Day math via fixed 86400s** (`poll.php:42`, `doha.php:62`) — off by one across DST. Low impact on no-DST timezones (e.g. IST).
5. **`$doha[0] => 0` landmine** (`doha.php:9`) — no bounds guard; not triggered today (indices 1–11) but fragile.
6. **Settings row read without null check** (`index.php:121-133`) — relies on the single-row invariant; add `LIMIT 1` + guard to harden.

User has been asked which to fix; none applied yet.

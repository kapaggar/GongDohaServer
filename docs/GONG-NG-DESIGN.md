# Gong-NG — Design Document

Next-generation Gongserver appliance for Vipassana centres.
Target: Raspberry Pi 3 / 4 / Zero 2 W, Raspberry Pi OS **Bookworm** (Lite, 32- or 64-bit), headless.
Replaces the legacy Buster LAMP appliance (this repo's `app/` + cron). Deployment model
is **fresh install**: flash a new SD card, seed from data already in this repo — no
field migration from running units.

Status: **M1+M2 implemented** in `ng/` (core daemon, scheduler, player, seed
conversion, admin UI/API, gongctl, 65-test suite — see `ng/README.md`).
M0 hardware validation and M3 provisioning remain. Sections marked
⚠ HW-VALIDATE must be confirmed on real hardware (`ng/tools/hw-spike.sh`)
before they are treated as decided.

---

## 1. Summary of decisions (the "starting point questions")

| Question | Decision | Why |
|---|---|---|
| One process vs several | **One systemd service** (`gongd`, Python 3.11) containing scheduler + player queue + admin web UI. Audio playback itself is a short-lived `mpv` child process. | One thing to start, stop, log, and watch. No IPC to design. The only crash-prone part (audio decode) is already isolated in a child process. |
| SQLite vs MariaDB | **SQLite (WAL mode)** at `/var/lib/gong/gong.db` | Single writer (gongd), < 1000 rows, zero-admin, no daemon to break at 4 AM, no credentials, backup = one file. MariaDB earns nothing here and costs a service, root-vs-app users, and dump/restore tooling. |
| AP: NetworkManager vs hostapd+dnsmasq | **NetworkManager AP profile** (`nmcli`), which is the Bookworm default stack. NM's `ipv4.method shared` runs its own embedded dnsmasq for DHCP. | Fighting the OS default (masking NM, hand-running hostapd) is exactly the kind of delta that breaks on the next OS release. hostapd+dnsmasq kept as a documented fallback only if a chipset fails under NM (⚠ HW-VALIDATE). |
| Legacy migration | **None in the field.** Units are re-flashed fresh. The valuable legacy data — `course_types` and the ~200-row `schedule` matrix — already lives in this repo (`db/gong.sql`); a build-time script converts it once into the new seed (§7). Settings are 8 values re-entered from the UI in two minutes; `courses` are future dates entered fresh anyway. | Removes an entire class of field tooling (dump parsing, in-place upgrades, mixed-state units). Every deployed unit is a known-good image + seed. |
| Forgotten admin PIN | Break-glass via console/SSH: `sudo gongctl reset-pin` (generates a new random PIN, prints it once). Documented on a laminated card in the unit's case. Physical/SSH access *is* the trust boundary (§10). | No hidden backdoor in the web UI. |

Language/runtime choice: **Python 3.11 + stdlib-heavy** (`sqlite3`, `zoneinfo`,
`threading`, Flask + waitress for HTTP). Boring, pre-installed on Bookworm, editable
in the field with nano over SSH — that last property matters in a remote centre and is
the main reason not to use Go/Rust here. Pinned wheels vendored for offline install (§12).

---

## 2. Architecture

### 2.1 Component diagram

```
┌──────────────────────────────  Raspberry Pi (Bookworm Lite)  ─────────────────────────────┐
│                                                                                           │
│  systemd                                                                                  │
│   ├── gongd.service (User=gong, groups: audio,gpio)  Restart=on-failure                   │
│   │   ┌─────────────────────────── gongd (one Python process) ──────────────────────────┐ │
│   │   │                                                                                 │ │
│   │   │  ┌───────────────┐   play requests    ┌──────────────┐   spawn/kill   ┌──────┐  │ │
│   │   │  │ Scheduler     │ ─────────────────► │ Player queue │ ─────────────► │ mpv  │  │ │
│   │   │  │ (thread)      │   (queue.Queue)    │ (thread)     │  subprocess    └──────┘  │ │
│   │   │  │ next-event    │                    │  relay on →  │                          │ │
│   │   │  │ loop, clock   │                    │  play N× →   │──► GPIO relay (gpiozero) │ │
│   │   │  │ sanity        │                    │  relay off   │                          │ │
│   │   │  └──────┬────────┘                    └──────┬───────┘                          │ │
│   │   │         │            ┌────────────┐          │                                  │ │
│   │   │         └──────────► │  SQLite    │ ◄────────┘  (play_log, state)               │ │
│   │   │                      │ gong.db    │                                             │ │
│   │   │  ┌───────────────┐   └────────────┘                                             │ │
│   │   │  │ Web admin     │ ◄── reads/writes settings, courses, schedule                 │ │
│   │   │  │ Flask+waitress│ ◄── test-gong/test-doha → enqueue on Player queue            │ │
│   │   │  │ :80 (thread)  │                                                              │ │
│   │   │  └───────────────┘                                                              │ │
│   │   └─────────────────────────────────────────────────────────────────────────────────┘ │
│   ├── NetworkManager: wlan0 AP profile "gong-ap" 192.168.5.1/24, ipv4 shared (DHCP)       │
│   ├── avahi-daemon: gong.local                                                            │
│   ├── systemd-timesyncd (opportunistic; useless off-grid, harmless)                       │
│   └── fake-hwclock + optional DS3231 RTC (dtoverlay=i2c-rtc,ds3231)                       │
│                                                                                           │
│  /var/lib/gong/     gong.db, media/{gongs,doha}/, secret_key, last_good_time              │
│  /etc/gong-ng/      config.toml (static, root-owned)                                      │
│  /opt/gong-ng/      code + venv (read-only at runtime)                                    │
└───────────────────────────────────────────────────────────────────────────────────────────┘
        ▲ Wi-Fi AP "DhammaGong" (WPA2)                  ▲ 3.5mm / USB audio → amp (via relay)
        staff phone/laptop → http://192.168.5.1/  or  http://gong.local/
```

Threads, not asyncio: three long-lived threads (scheduler, player, web server) with a
`queue.Queue` between scheduler/web and player. Each thread owns its own SQLite
connection (WAL allows concurrent readers + one writer). This is deliberately the
dumbest concurrency model that satisfies the requirements.

### 2.2 Why not keep cron + PHP

* cron gives minute granularity and *no* catch-up: a 30 s boot delay at 04:00 silently
  skips the wake-up gong. The scheduler thread fires on a second-accurate deadline and
  has an explicit late-fire grace window (§5.3).
* "State in the DB, brain re-derived every minute" made the legacy zero-day bug
  possible (`check_zero_day()` only looked at `c_date == today`). A resident process
  owns the derived state (active course, current day, next events) and recomputes it
  on day rollover, clock change, and any admin edit.
* One journald stream instead of cron mail + `/var/log/gong.log` + Apache logs.

### 2.3 Playback contract

* All playback goes through the **player thread** — gong, doha, and UI test buttons.
  A gong burst still running when the next event fires is stopped, not stacked; doha
  never preempts a running gong, it waits.
* Stopping a play = `SIGTERM` to the mpv child, `SIGKILL` after 2 s. No more
  `pkill -x` sweeps of everything that looks like a player.
* Volume: 0–100 % applied per-play with `mpv --volume=N`; ALSA mixer is set once at
  startup to a calibrated ceiling (config `alsa_mixer_setup`), not touched per play.
  Separate stored volumes for gong and doha.
* Relay (optional): ON → settle delay (default 5 s, config) → play → OFF. Polarity
  configurable (`relay.active_low = true`, the common relay-board default
  ⚠ HW-VALIDATE). Relay is claimed via `gpiozero`/libgpiod (Bookworm has no
  `/sys/class/gpio` sysfs). Default pin **GPIO17** (physical pin 11) ⚠ HW-VALIDATE
  against actual wiring of existing units.
* Audio device: `mpv --audio-device=alsa/<name>` from config. On Bookworm the headphone
  jack is `bcm2835 Headphones`; USB DACs enumerate unpredictably — config takes an ALSA
  name and the status page shows what `mpv --audio-device=help` reports ⚠ HW-VALIDATE.

---

## 3. Data model (SQLite)

```sql
PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;

CREATE TABLE course_types (
  id            INTEGER PRIMARY KEY,          -- keep legacy ct_id values in the seed
  name          TEXT NOT NULL UNIQUE,         -- '10 Day'
  total_days    INTEGER NOT NULL,             -- last day index (legacy ct_days; '10 Day' = 11)
  anapana_days  INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE courses (
  id             INTEGER PRIMARY KEY,
  course_type_id INTEGER NOT NULL REFERENCES course_types(id),
  start_date     TEXT NOT NULL,               -- 'YYYY-MM-DD' local date == zero day
  note           TEXT NOT NULL DEFAULT ''
);

-- One row = "on this pattern-day, at this wall-clock time, strike the gong N times".
CREATE TABLE schedule_events (
  id             INTEGER PRIMARY KEY,
  course_type_id INTEGER REFERENCES course_types(id),  -- NULL = the no-course set (legacy type -1)
  day_no         INTEGER,                     -- NULL = default mid-course pattern (legacy day-2 fallback)
  time_local     TEXT NOT NULL,               -- 'HH:MM' 24h wall-clock local time
  repeats        INTEGER NOT NULL CHECK (repeats BETWEEN 1 AND 32),
  gap_seconds    INTEGER,                     -- NULL = use settings.gong_gap_seconds
  track          TEXT,                        -- NULL = use settings.gong_track
  UNIQUE (course_type_id, day_no, time_local)
);

-- Singleton key/value settings, typed in code. Keys and defaults:
--   enabled='1' gong_enabled='1' doha_enabled='1' relay_enabled='0'
--   gong_track='ting' gong_volume='90' gong_gap_seconds='4'
--   doha_time='06:37' doha_volume='75' doha_strategy='legacy_modular'
--   no_course_doha='random'        (random | off | slot:<n>)
--   active_course_id=''            (empty = derive from calendar, §5.2)
--   admin_pin_hash='...'           (hashlib.scrypt)
--   clock_confirmed_until=''       (§6)
CREATE TABLE settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);

-- Internal daemon state, survives restarts. Includes:
--   fired:<event_id>:<local_date> = ISO timestamp   (double-fire guard, pruned after 2 days)
--   last_good_time = ISO timestamp                  (clock sanity, §6)
--   schema_version = N
CREATE TABLE state (key TEXT PRIMARY KEY, value TEXT NOT NULL);

CREATE TABLE play_log (
  id        INTEGER PRIMARY KEY,
  ts_utc    TEXT NOT NULL,
  kind      TEXT NOT NULL,        -- 'gong' | 'doha' | 'test_gong' | 'test_doha'
  file      TEXT NOT NULL,
  repeats   INTEGER NOT NULL,
  result    TEXT NOT NULL,        -- 'ok' | 'error' | 'skipped_clock' | 'stopped' | 'missed'
  detail    TEXT NOT NULL DEFAULT ''
);
```

Media are files, not DB rows:

```
/var/lib/gong/media/gongs/ting.mp3, drum.mp3, joti.mp3, ...   (track name = filename stem)
/var/lib/gong/media/doha/D01_... .mp3 ... D11_... .mp3
/var/lib/gong/media/doha/manifest.json    -- maps slots 1..11 → filenames (§5.5)
```

### 3.1 Schedule resolution (materialization)

For a given local date, the effective event list is:

1. Determine context: active course + `current_day` (§5.2), or *no course*.
2. No course → all rows where `course_type_id IS NULL`.
3. In course → rows where `course_type_id = CT AND day_no = current_day` if any exist,
   **else** rows where `course_type_id = CT AND day_no IS NULL` (the default pattern).
   This reproduces the legacy "fall back to day 2" behaviour, but explicitly: the seed
   stores legacy day-2 rows as the default pattern (§7).

**Example** — 10 Day course (`total_days=11`), zero day 2026-07-01, today 2026-07-05
(`current_day = 4`; explicit day-4 rows exist in the legacy seed):

| time_local | repeats | source row |
|---|---|---|
| 04:00 | 16 | (type 1, day 4, 0400, 16) |
| 04:20 | 12 | (1, 4, 0420, 12) |
| 06:32 | 3  | (1, 4, 0632, 3) |
| 07:50 | 8  | (1, 4, 0750, 8) |
| 11:00 | 6  | (1, 4, 1100, 6) |
| 12:50 | 8  | (1, 4, 1250, 8) |
| 13:40 | 1  | (1, 4, 1340, 1) |
| 13:50 | 3  | (1, 4, 1350, 3) |
| 17:00 | 6  | (1, 4, 1700, 6) |
| 17:50 | 6  | (1, 4, 1750, 6) |
| 21:00 | 3  | (1, 4, 2100, 3) |

Plus one doha event at `settings.doha_time` (06:37) if `doha_enabled` and inside the
course window (or per the outside-course rule, §5.5).

---

## 4. File layout, units, config

```
/opt/gong-ng/                    # code — read-only in production
  venv/                          # python venv from vendored wheels
  gong_ng/                       # package: scheduler.py player.py web/ db.py ...
  bin/gongctl                    # CLI: status, test-gong, test-doha, backup, restore,
                                 #      reset-pin, wifi, simulate, migrate-db
/etc/gong-ng/config.toml         # static machine config (root:root 0644) — below
/var/lib/gong/                   # ALL mutable state (gong:gong 0750)
  gong.db  gong.db-wal
  media/gongs/  media/doha/
  secret_key                     # session-cookie signing key (0600)
/usr/lib/systemd/system/gongd.service
/usr/lib/systemd/system/gong-firstboot.service   # oneshot smoke check, §12
```

`config.toml` (machine facts that never change from the UI):

```toml
[audio]
player = "mpv"                       # mpv | dummy (CI)
alsa_device = "alsa/plughw:CARD=Headphones"   # ⚠ HW-VALIDATE
alsa_mixer_setup = ["amixer sset Headphone 100%"]

[relay]
enabled_hw = true                    # hardware present at all
gpio = 17
active_low = true                    # ⚠ HW-VALIDATE
settle_seconds = 5

[time]
timezone = "Asia/Kolkata"
fire_grace_seconds = 120             # how late a fire may still happen

[web]
listen = "0.0.0.0:80"
session_hours = 720                  # 30 days; course-length friendly
```

`gongd.service`:

```ini
[Unit]
Description=Gong-NG scheduler and admin UI
After=network.target time-sync.target sound.target

[Service]
User=gong
Group=gong
SupplementaryGroups=audio gpio systemd-journal
ExecStart=/opt/gong-ng/venv/bin/python -m gong_ng
Restart=on-failure
RestartSec=5
AmbientCapabilities=CAP_NET_BIND_SERVICE
ProtectSystem=strict
ReadWritePaths=/var/lib/gong
NoNewPrivileges=yes
ProtectHome=yes
PrivateTmp=yes

[Install]
WantedBy=multi-user.target
```

Time-set from the UI is the one privileged operation; like the legacy system it goes
through a sudoers whitelist, but for a dedicated helper with strict argument
validation, not raw `date -s`:

```
gong ALL=(root) NOPASSWD: /opt/gong-ng/bin/gong-settime
```

`gong-settime` accepts only `YYYY-MM-DD HH:MM` (validated with a real calendar parse,
fixing legacy finding #3), calls `date -s`, then `hwclock -w` if an RTC exists and
`fake-hwclock save`.

Logs: everything to stdout → journald (`journalctl -u gongd`). `play_log` is the
staff-visible history; the UI log page reads it plus the last 100 journal lines
(readable because `gong` is in group `systemd-journal`).

---

## 5. Scheduling — the exact algorithm

Deliberately pedantic; scheduling is where the legacy system hid its bugs.

### 5.1 Clocks and timezones

* All *stored* times are wall-clock local (`HH:MM` strings, `YYYY-MM-DD` dates).
  Correct for this domain: "gong at 04:00" means 04:00 on the wall, always.
* Timezone from `config.toml` via `zoneinfo.ZoneInfo`; OS timezone set to match at
  install. Default `Asia/Kolkata` (no DST — but the code must still be DST-correct
  for centres elsewhere):
  * `current_day` = `(local_date(now) - zero_day).days` — **calendar-date
    subtraction**, never `/86400` (fixes legacy finding #4).
  * Materializing `HH:MM` on date D: if the wall time doesn't exist (spring-forward
    gap), fire at the first valid instant after the gap; if ambiguous (fall-back),
    fire the **first** occurrence only.
* The scheduler sleeps on `threading.Event.wait(timeout)` capped at 30 s and
  recomputes "now" from the wall clock on every wake. Wall-clock jumps (staff set
  time, NTP step) are picked up within 30 s; monotonic time is used only for the gap
  between gong strikes.

### 5.2 Active course derivation (fixes legacy finding #1)

Recomputed at startup, at local-midnight rollover, on any courses/settings change,
and after any clock change > 60 s:

```
candidates = courses where start_date <= today <= start_date + course_type.total_days
if settings.active_course_id points at a candidate → use it
elif exactly one candidate → use it (record as active_course_id)
elif multiple → most recent start_date wins; log warning; banner in UI
else → no course
```

A course that started while the Pi was powered off is found on next boot because the
*window*, not the start day, is matched. The legacy `set-zero-day.php` cron
disappears; `zero_day` is no longer a mutable setting, it *is* `course.start_date`.

### 5.3 Next-event computation and firing

```
def upcoming(now_local):
    events = materialize(today) + materialize(tomorrow)   # §3.1, gong + doha
    return sorted((dt, e) for dt, e in events
                  if dt > now_local - grace
                  and not state.fired(e.id, dt.date()))
```

Loop: compute `upcoming()`, sleep until `min(next_fire, now + 30 s)`, on wake fire
everything with `fire_dt <= now <= fire_dt + grace` (default 120 s), writing
`fired:<event_id>:<date>` to `state` **before** enqueueing to the player.
Consequences, all intentional:

* Restart at 03:59:50 → 04:00 gong still fires.
* Power restored 04:01 → 04:00 gong fires (late but within grace).
* Power restored 04:10 → 04:00 gong is *skipped*, logged as `missed`. Blasting a
  wake-up gong at a random late time is worse than missing it.
* Never fires early; never fires twice for one (event, local date), even across
  restarts or backwards clock nudges — the guard is persisted.

### 5.4 Gong fire — sequence

```
Scheduler                Player thread                 GPIO        mpv            SQLite
    │  enqueue(GongJob:      │                          │           │                │
    │  file,N,gap,vol) ─────►│                          │           │                │
    │                        │ if relay: relay_on ─────►│           │                │
    │                        │ sleep(settle 5s)         │           │                │
    │                        │ for i in 1..N:           │           │                │
    │                        │   stop_current()         │           │                │
    │                        │   spawn mpv --volume ───────────────►│ (blocks)       │
    │                        │   wait exit              │           │                │
    │                        │   if i<N: sleep(gap)     │           │                │
    │                        │ if relay: relay_off ────►│           │                │
    │                        │ INSERT play_log ────────────────────────────────────►│
```

New job mid-burst: gong-vs-gong → current burst aborted (relay stays on if the next
job also uses it), new job starts; doha-vs-gong → doha waits. UI "Stop now" aborts
whatever is playing.

### 5.5 Doha fire — selection and sequence

One synthetic event per day at `settings.doha_time` (default 06:37 — second-accurate
now, so no more "hour must be 6" guard):

```
Scheduler ──► Player: DohaJob(file, vol)      # same relay/settle wrapper as gong
  slot = strategy(current_day, total_days, anapana_days)
  file = doha_dir / manifest[slot]
```

`legacy_modular` strategy — byte-for-byte the legacy algorithm (verified against
`app/dhamma/doha.php:66-83`):

```python
def legacy_modular(day, total, anapana):
    if day <= anapana:              slot = ((day - 1) % 3) + 1      # anapana: 1,2,3 cycle
    elif day == anapana + 1:        slot = 4                        # first vipassana day
    else:                           slot = 3 + ((day - (anapana + 1)) % 6) + 1  # 4..9 cycle
    metta_days = 2 if total >= 30 else 1
    if day == total:                slot = 11                       # homage, last day
    elif day >= total - metta_days: slot = 10                       # metta day(s)
    return slot
```

Outside a course window: `no_course_doha` = `random` (legacy behaviour, slot 1–11) |
`off` | `slot:<n>`. `manifest.json` maps slots to files so centres can swap
recordings without renaming; the seed writes it from the 11 filenames in
`app/dhamma/doha/`. This fixes legacy finding #5 structurally: slot lookup goes
through the manifest with a bounds check and logs+skips on a missing slot.

Doha honours `enabled && doha_enabled`; a disabled master switch logs **once** on
state change, not per occurrence (fixes legacy finding #2).

---

## 6. Time safety (clock-wrong protection)

The Pi has no battery clock by default; fake-hwclock restores the *last shutdown*
time on boot, so after a 3-day power cut the clock is 3 days slow — and the appliance
would gong on the wrong course day. Defence in depth:

1. **last_good_time**: gongd writes `now` to `state.last_good_time` every 5 minutes.
   On startup, if `now < last_good_time - 10 min`, the clock went *backwards* →
   **clock-invalid mode**.
2. Clock-invalid mode: automatic playback suppressed (`play_log` rows recorded as
   `skipped_clock`), UI shows a full-width red banner: "Clock not trusted — confirm
   or set the time". Staff confirming or setting the time clears it. Test buttons
   still work (staff are present to press them).
3. If NTP later syncs (station mode / centre LAN), the step clears the condition
   automatically when new time ≥ last_good_time.
4. **Recommended hardware fix**, documented in DEPLOY: DS3231 RTC module (~₹150) on
   the I²C header, `dtoverlay=i2c-rtc,ds3231`, remove fake-hwclock. With an RTC,
   condition (1) essentially never triggers. ⚠ HW-VALIDATE (I²C address 0x68 clash
   if other HATs present).

Rationale for suppress-rather-than-guess: a wrong 04:00 gong at what is actually
01:00 wakes 100 students; silence gets noticed by staff at dawn and fixed. Silence is
the safe failure.

---

## 7. Seeding (no field migration)

Deployment is always a fresh flash, so there is **no runtime importer and no
in-place upgrade of legacy units**. The legacy data worth keeping is already version-
controlled in this repo:

* `db/gong.sql` → **`seed/seed.sql`**, produced once at build time by
  `tools/convert-legacy-seed.py` (checked in alongside its output so the conversion
  is reviewable). Mapping:

| Legacy (`db/gong.sql`) | New seed | Transform |
|---|---|---|
| `course_types (ct_id, ct_name, ct_days, ct_anapana_days)` | `course_types` | 1:1, ids preserved |
| `schedule (type, day_no, start_time, total_repeat)` | `schedule_events` | `type=-1` → `course_type_id=NULL`; `day_no=2` (and `-1`) → `day_no=NULL` (default pattern); `start_time` int HHMM → `f"{t//100:02d}:{t%100:02d}"` (632→'06:32'); `total_repeat` → `repeats` |
| `courses` | — | not seeded (they're dates; entered fresh per centre) |
| `settings` row | — | not seeded beyond defaults (§3); staff set 8 values from a phone at install |

  Note on the day-2 fallback: legacy fell back to day 2 only when the current day had
  zero rows, and day-2 rows also served as literal day 2. Converting day-2 rows *to*
  the default pattern preserves behaviour exactly (day 2 then resolves to the default
  pattern, same rows). The legacy schema couldn't express "day 2 differs from the
  generic day", so nothing is lost.

* Gong MP3s: repo `gong-ting.mp3` / `gong-drum.mp3` → `media/gongs/{ting,drum}.mp3`.
* Doha MP3s: repo `app/dhamma/doha/D01..D11` → `media/doha/` + generated
  `manifest.json`.

Escape hatch (kept cheap, not built until needed): if some centre turns out to have a
customised schedule living only on its old unit, run `mysqldump gong schedule` there,
feed the file to `tools/convert-legacy-seed.py --merge` on a laptop, and re-flash.
The converter is the same build-time script; it never ships on the appliance.

---

## 8. Admin UI + API

Server-rendered Flask app (Jinja2 + a little vanilla JS + one CSS file; no build
step, no CDN — must render offline on a 2018 Android phone).

### Auth

* 4–8 digit PIN → `hashlib.scrypt` hash in settings. Login sets an HMAC-signed
  session cookie (key = `/var/lib/gong/secret_key`), 30-day expiry.
* 5 failed attempts → 60 s lockout (in-memory), log entry. Good enough against a
  bored course-sitter; the real boundary is the WPA2 passphrase (§10).
* Every mutating route is POST + CSRF token. No phpMyAdmin, no SQL anywhere near HTTP.

### Screens (mobile-first, one column)

```
┌──────────────────────────────┐
│ ⏰ 04:12  Sun 05 Jul   IST   │  ← always-visible header strip
│ ⚠ CLOCK NOT TRUSTED [Fix]    │  ← only in clock-invalid mode
├──────────────────────────────┤
│ 10 Day course — Day 4        │
│ Master  [ON]  Gong [ON]      │
│ Doha [ON]     Relay [OFF]    │
│ Next: 🔔 04:20 ×12 (in 7m)   │
│       🎵 06:37 doha D05      │
│ [Test gong] [Test doha] [⏹] │
├──────────────────────────────┤
│ ▸ Courses      ▸ Schedule    │
│ ▸ Sounds/Vol   ▸ Time        │
│ ▸ Logs         ▸ Backup      │
└──────────────────────────────┘
```

* **Dashboard** `/` — the strip above; four toggles; next 5 events; test buttons.
* **Courses** `/courses` — list upcoming/past; add (type + start date); delete;
  "active now" indicator with derived day number.
* **Schedule** `/schedule?type=&day=` — grid of times per (course type,
  day/default/no-course); add/edit/delete; "copy day to day"; CSV import/export.
* **Sounds & volume** `/sounds` — gong track picker (from `media/gongs/`), gong
  volume, gap seconds, doha volume, doha time, no-course doha mode.
* **Time** `/time` — big current time + tz; set date/time form (strict validation,
  fixes legacy finding #3); "clock looks right" confirm button; RTC presence shown.
* **Logs** `/logs` — last 50 `play_log` rows + last daemon log lines.
* **Backup** `/backup` — download `gong-backup-YYYYMMDD.tar.gz` (DB via
  `sqlite3 .backup` + config.toml + manifest; *not* media — media ships in the
  install bundle); upload/restore with confirm.

### API (JSON, same session auth; the UI uses these; future kiosk/monitor can too)

```
GET  /api/status         → time, tz, clock_ok, course{type,day}, toggles, next[5],
                           disk_free, audio_device_ok, last_play
GET/PUT /api/settings
GET/POST/DELETE /api/courses[/id]
GET/POST/DELETE /api/schedule[/id]      ?type=&day=
POST /api/test/gong  /api/test/doha  /api/stop
POST /api/time           {"datetime": "2026-07-05 04:12"} | {"confirm": true}
GET  /api/logs           ?n=50
GET  /api/backup         (tar.gz)      POST /api/restore
GET  /healthz            → 200 minimal JSON, UNAUTHENTICATED (monitoring only,
                           leaks nothing: {"ok":true,"clock_ok":true,"queue":0})
```

---

## 9. Network

### AP mode (field default)

Provisioned at firstboot via `nmcli` (idempotent script, not hand-edited files):

```
nmcli con add type wifi ifname wlan0 con-name gong-ap autoconnect yes \
  ssid "DhammaGong" mode ap ipv4.method shared ipv4.addresses 192.168.5.1/24 \
  wifi.band bg wifi.channel 6 \
  wifi-sec.key-mgmt wpa-psk wifi-sec.psk "<from firstboot config>" \
  wifi-sec.proto rsn wifi-sec.pairwise ccmp
```

* `ipv4.method shared` → NM runs dnsmasq internally: DHCP + DNS on 192.168.5.0/24.
  (It also inserts a NAT masquerade rule — harmless with no uplink.)
* WPA2-PSK only (RSN/CCMP, no WPA1/TKIP). WPA3/SAE is not reliable across old staff
  phones; not worth it inside this threat model.
* `wifi.country` from firstboot config (default `IN`).
* avahi-daemon → `http://gong.local/`; the sticker on the unit says
  `http://192.168.5.1/` because mDNS is the flaky one.
  ⚠ HW-VALIDATE: brcmfmac AP mode with 5+ associated clients on the exact board
  revisions in use; and that no standalone dnsmasq is installed to fight NM's
  (the installer must ensure it isn't).

### Station mode (maintenance)

`gongctl wifi join <ssid> <psk>` creates a normal NM profile; `gongctl wifi ap`
switches back. Internal Wi-Fi can't do AP+STA concurrently in any way worth
supporting — the switch is explicit and staff-initiated; the UI shows a
"maintenance mode — AP is off" banner while in station mode.

### Not exposed

No forwarding needed; sshd on (break-glass path, §1); nftables: allow
22/80/DHCP/DNS/mDNS on wlan0, drop other inbound.

---

## 10. Threat model (private AP)

Assets: undisturbed course schedule (integrity of gong times), the device itself.
No confidential data exists on the box — gong times are public knowledge.

| Actor | Capability | Mitigation |
|---|---|---|
| Passer-by / neighbour | Sees SSID, tries to join | WPA2-PSK, per-centre passphrase set at provisioning (never a default); 802.11 range ≈ the campus |
| Student who obtained the Wi-Fi password | Can reach :80, :22 | Admin PIN + session on all UI/API; rate-limited PIN; sshd per centre policy; `/healthz` is the only anonymous route and leaks nothing actionable |
| Malicious/curious staff | Has PIN | In scope = trusted to run the course. Audit via `play_log` + journald. No shell escape from the UI: no raw SQL; the only privileged op is the strictly-validated `gong-settime` sudo helper |
| Physical access | SD card removal | Out of scope — physical access is game over by design; it is also the documented PIN-recovery path. No secrets worth encrypting at rest |
| Web-class attacks | CSRF/session replay | CSRF tokens on all POSTs; cookies `SameSite=Lax`; device unreachable from other networks anyway |

Deliberate non-goals: TLS (self-signed certs cause more staff confusion than the
plaintext-over-WPA2 risk), user accounts/roles (one PIN), internet-facing hardening.

---

## 11. Repo skeleton

```
gong-ng/
├── pyproject.toml                  # deps: flask, waitress, gpiozero; dev: pytest, ruff, mypy
├── README.md
├── gong_ng/
│   ├── __main__.py                 # wires threads, signal handling
│   ├── config.py                   # config.toml loader + defaults + validation
│   ├── db.py                       # connection factory, migrations (state.schema_version)
│   ├── model.py                    # typed accessors: Settings, Course, ScheduleEvent
│   ├── clock.py                    # tz, current_day, last_good_time, clock-invalid state
│   ├── scheduler.py                # §5 loop
│   ├── doha.py                     # strategies + manifest
│   ├── player.py                   # queue, mpv child mgmt, relay orchestration
│   ├── relay.py                    # gpiozero wrapper (+ dummy backend for CI)
│   └── web/
│       ├── app.py routes_api.py routes_ui.py auth.py
│       ├── templates/*.html.j2
│       └── static/gong.css gong.js
├── bin/gongctl  bin/gong-settime
├── seed/seed.sql                   # generated by tools/convert-legacy-seed.py, checked in
├── tools/convert-legacy-seed.py    # build-time only; never ships on the appliance
├── systemd/gongd.service  systemd/gong-firstboot.service
├── firstboot/firstrun.sh  firstboot/gong-firstboot.toml.example
├── os/nftables.conf  os/sudoers.d-gong  os/config.txt.snippets
├── media-src/gongs/ doha/          # canonical MP3s (from this repo)
├── tests/
│   ├── test_scheduler.py test_clock.py test_doha.py test_seed.py test_api.py
│   └── fixtures/legacy_gong.sql    # the real dump, pins the seed conversion
└── docs/DESIGN.md DEPLOY.md WIRING.md RUNBOOK.md
```

Hardware wiring (full drawings in WIRING.md):

```
Pi GPIO17 (pin 11) ──► relay IN        Pi 5V (pin 2) ──► relay VCC
Pi GND   (pin 9)  ──► relay GND        relay NO/COM  ──► amp mains switch side
3.5mm jack / USB DAC ──► amp line-in
Optional DS3231 RTC: 3V3(1) SDA(3) SCL(5) GND(9)
```

---

## 12. Install / firstboot (Bookworm, fresh flash every time)

Two stages, building on this repo's proven `firstrun.sh` pattern (`docs/FIRSTRUN.md`):

**Stage A — at a location with internet (before shipping):**
1. Flash Raspberry Pi OS Lite Bookworm with Raspberry Pi Imager (hostname
   `dhammagong`, SSH on, `ops` user).
2. Copy onto the boot partition: `firstrun.sh`, `gong-firstboot.toml` (SSID, WPA2
   psk, country, timezone, initial admin PIN, relay pin/polarity, rtc yes/no), and
   the **offline bundle** `gong-ng-bundle.tar.gz` (apt pool for
   mpv/avahi/nftables/python3-gpiozero pulled with `apt-get download`, Python wheels
   for the target arch, `seed/seed.sql`, media files). Hook via
   ` systemd.run=/boot/firstrun.sh` in `cmdline.txt` (the stock Imager mechanism).
3. First boot may use internet if present (best-effort `apt-get update`) but **must
   succeed from the bundle alone** — the "no cloud" constraint applies to the install
   path too.

**Stage B — firstrun.sh (oneshot, idempotent, logs to /boot/firstrun.log):**
1. Install debs from the bundle pool.
2. Create `gong` user (groups audio, gpio, systemd-journal); lay out `/opt/gong-ng`
   (venv from vendored wheels), `/var/lib/gong`, `/etc/gong-ng/config.toml` from the
   firstboot toml.
3. Initialize DB: schema + `seed/seed.sql`; copy media; write `manifest.json`; set
   initial PIN hash.
4. Network: `nmcli` AP profile (§9), avahi, nftables, Wi-Fi country.
5. Time: timezone; enable I²C + RTC overlay if `rtc = true`.
6. sudoers drop-in, enable `gongd.service`, remove the `systemd.run` hook from
   cmdline.txt, reboot.
7. Post-reboot: `gong-firstboot.service` (oneshot) runs `gongctl status --check`
   (DB ok, audio device present, AP up) and blinks the ACT LED in an SOS pattern on
   failure — the only "display" a headless field unit has.

Upgrades = re-flash with the new bundle + restore the backup tarball (§8). Because
`/var/lib/gong` state is one small tarball, "reinstall fresh" is also the repair
procedure for SD-card corruption — one documented path instead of two.

---

## 13. Test plan

### Unit (pytest, runs on the Mac / CI, no hardware — `player=dummy`, fake relay, fake clock)

* `clock.py`: current_day across month/year boundaries; DST spring-forward at a
  scheduled time (Europe/London fixture) fires at first valid instant; fall-back
  fires once; Asia/Kolkata unaffected.
* `scheduler.py`: fires within grace; skips beyond grace and logs `missed`; never
  double-fires across simulated restart (persisted state); day-pattern fallback
  (explicit day → default → no-course); disabled flags log once on state change.
* `doha.py`: golden table for `legacy_modular` over every seeded course type —
  10 Day: days 1–3 → slots 1,2,3; day 4 → 4; days 5–9 → 5..9; day 10 → 10;
  day 11 → 11; plus 30/45-day `metta_days=2` branch, STP (8/2), Teen (8/2).
* `test_seed.py`: run the converter against `fixtures/legacy_gong.sql` (the real
  dump); assert row counts, HHMM spot checks (632→'06:32', 2100→'21:00'),
  day-2→default move, type -1→NULL. Fails the build if `seed/seed.sql` drifts from
  the converter output.
* `web`: PIN auth, lockout, CSRF; settings round-trip; time-set rejects `99:99`
  and `2026-02-30`.
* `player.py`: ordering relay-on → settle → N plays with gaps → relay-off;
  preemption rules (gong replaces gong; doha waits).

### On-device checklist (per unit, before deployment)

1. `gongctl status --check` green: DB, audio device, GPIO claim, AP profile.
2. Audible test gong ×3 through the actual amp; relay click, 5 s settle, no power-on
   pop during the settle window ⚠ HW-VALIDATE.
3. Doha test button plays the mapped file at doha volume.
4. Join AP from Android + iPhone; open `192.168.5.1` and `gong.local`; log in.
5. Pull power mid-gong-burst → reboots → service up < 60 s → **relay not stuck on**
   (GPIO must default OFF through kernel boot; if the chosen pin glitches high at
   boot, move pins and document in WIRING.md ⚠ HW-VALIDATE).
6. Set clock 3 days back via UI → clock-invalid banner, auto-play suppressed;
   confirm → clears.
7. Backup download; restore onto a second unit; verify schedule identical.

### 10-day course dry run (bench)

`gongctl simulate --course "10 Day" --start <date>`: scheduler runs on a warped clock
(1 simulated day ≈ 10 real minutes, plays the first 2 s of each file at low volume)
and writes a full `play_log`. Assert the log against a golden materialized schedule
for all days 0–11, including the doha slot per day. Then one **real-time** soak: arm
a course with zero day = tomorrow, run 48 h on the bench with the amp; verify day-0
18:00 ×6, day-1 04:00 ×16, day-1 doha 06:37 slot 1, and journald shows zero restarts.

---

## 14. Phased implementation plan

**M0 — hardware spike (kill the unknowns; ~2 days on-device)**
mpv on Bookworm to 3.5 mm + USB DAC; ALSA device names per Pi model; gpiozero relay
incl. boot-glitch check; `nmcli` AP with 5 clients; DS3231 overlay.
*Exit: every ⚠ HW-VALIDATE item in this doc resolved or has a workaround.*

**M1 — core daemon (the appliance works headless)**
`db.py` + schema; seed converter + checked-in `seed.sql`; `clock.py`, `scheduler.py`,
`player.py`, `doha.py`; `gongctl` (status/test/simulate); `gongd.service`. Full unit
suite. *Exit: simulated 10-day golden run passes; a bench Pi gongs a real day
correctly from the seed, driven only by CLI.*

**M2 — admin UI + API**
PIN auth, dashboard, courses, schedule editor, sounds, time (sudo helper), logs,
backup/restore, `/healthz`. *Exit: on-device checklist 3–7 pass; a non-technical
tester can set up next month's course from a phone unaided.*

**M3 — provisioning + network**
Offline bundle build script; `firstrun.sh`; AP/station switching; nftables; avahi;
RTC path. *Exit: stock Bookworm Lite → working appliance with zero keyboard input and
zero internet; provisioning a second card takes < 20 min.*

**M4 — hardening + field pilot**
48 h soak; power-cut torture (pull the plug 20×, incl. mid-play); clock drills;
RUNBOOK.md (laminated one-pager: PIN reset, time fix, backup). Pilot at one centre
for one real 10-day course **with the legacy unit still installed as backup**,
comparing `play_log` against the legacy `/var/log/gong.log` daily.
*Exit: pilot completes with zero missed/extra gongs; legacy unit decommissioned.*

Dependencies: M0 → M1 → M2 → {M3 ∥ M4 prep}; the pilot needs M3.

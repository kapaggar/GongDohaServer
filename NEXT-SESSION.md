# Session handoff — for the next Fable session

**Date:** 2026-07-12
**Task this session:** "Scan the repo and find bugs in the PHP files; analyze first."
**Status:** Analysis complete. **No code changed.** User was asked which bugs to fix; awaiting direction (last question offered: "#1 and #2, or all six?").

Project context/architecture lives in `CLAUDE.md` (auto-loaded). This file is the running log of the bug work so you can pick up where it left off.

## Scope reviewed

All PHP in the repo (excluding vendor/git):
- `app/www/index.php` (admin UI)
- `app/dhamma/poll.php` (gong scheduler, every minute)
- `app/dhamma/doha.php` (morning doha, 06:37)
- `app/dhamma/set-zero-day.php` (wrapper)
- `app/dhamma/constants.inc` (shared helpers)
- `docker/config.inc.php` (test override)

Cross-checked against `db/gong.sql` (schema/seed) and `scripts/mac-test.sh` (harness).
`php -l` is clean on every file — no syntax errors. Code is otherwise solid: prepared statements throughout, `htmlspecialchars` on output, `escapeshellarg`/`escapeshellcmd` on shell calls.

## Findings (ranked, none fixed)

### 1. `check_zero_day()` misses any course not starting "today" — HIGH
`app/dhamma/constants.inc:53-74`
```php
$q = "SELECT * FROM courses WHERE c_date >= ? ORDER BY c_date LIMIT 1";
...
if ($zero_day == $today) { /* only updates when a course starts exactly today */ }
```
Driven by cron (`set-zero-day.php` at 08/14/16). If the appliance is off or the cron
misses on the course's start day, then every following day the query returns the *next*
course — the running one (`c_date < today`) is invisible — so `settings.zero_day` stays
stale and gong/doha day numbers are wrong for the whole course.
**Fix:** select the active course, e.g. `WHERE c_date <= today AND today <= c_date + INTERVAL ct_days DAY` (join course_types for ct_days), instead of `c_date == today`.

### 2. Disabled cron logs + exits non-zero every minute — MEDIUM
`app/dhamma/poll.php:22-25`
```php
if (!$enabled) { logit("Cron Disabled, exiting"); exit(1); }
```
Runs every minute → one log line/minute in `/var/log/gong.log` + exit 1 (cron error mail
every minute). The `gong_enabled` branch right below deliberately does the opposite
(`// silent exit — no log spam every minute`, `exit(0)`). Make the disabled branch silent
`exit(0)` too. `doha.php:36-39` has the same pattern (only once/day, so minor).

### 3. "Set Date" regex accepts impossible times — MEDIUM
`app/www/index.php:59` — time part is `[0-9]{2}:[0-9]{2}`, accepts `99:99`. It's
`escapeshellarg`'d (no injection) but passed to `sudo /bin/date -s`, so bad input corrupts
the system clock (feeds day math + `hwclock -w`). Tighten to `([01][0-9]|2[0-3]):[0-5][0-9]`.

### 4. Course-day math via fixed 86400s → DST off-by-one — LOW
`app/dhamma/poll.php:42`, `app/dhamma/doha.php:62`
`(int)floor($datediff / (60*60*24))` assumes 24h days; off by one for the day after a DST
change. Low impact if the centre runs a no-DST timezone (IST). Compute from calendar dates
to be safe.

### 5. `$doha[0] => 0` landmine — LOW
`app/dhamma/doha.php:9` maps index 0 to integer `0`, not a filename. Not hit today
(`pick_doha_index` returns 1–11, fallback `rand(1,11)`), but no bounds guard before
`$DOHA_DIR . $doha[$a]`. Drop the `0 => 0` entry or validate `$a`.

### 6. Settings row read without existence check — LOW
`app/www/index.php:121-133` dereferences `$e_r["..."]` with no null guard; every
`UPDATE settings` also omits `WHERE`. Both rely on the one-row invariant. Add `LIMIT 1`
+ a null guard to harden.

## Suggested next step

Fix **#1** and **#2** first (real operational impact, clear fixes), then #3. #4–#6 are
hardening. When editing:
- Keep the prepared-statement / escaping conventions.
- After changes, re-lint (`php -l`) and exercise via `./scripts/mac-test.sh up` +
  `arm-gong` + `gong` / `doha`, checking `/var/log/gong.log`.
- Do NOT overwrite `README.md` (project readme) — it's user-facing.

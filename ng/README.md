# Gong-NG

Next-generation Gongserver: one Python daemon (`gongd`) that schedules gong
and doha playback second-accurately, drives the amplifier relay, and serves a
PIN-protected mobile admin UI. SQLite storage, fresh-install deployment, no
internet ever required. Full design: [`../docs/GONG-NG-DESIGN.md`](../docs/GONG-NG-DESIGN.md).

## Status

- **Done (M1+M2):** core daemon, scheduler, player, doha selection, seed
  conversion from the legacy dump, admin UI + JSON API, `gongctl`, unit tests.
- **Not yet validated on hardware (M0):** ALSA device name, relay boot-glitch,
  NetworkManager AP mode, DS3231. Run `tools/hw-spike.sh` on a Pi first.
- **Not built yet (M3):** the offline install bundle builder; `firstboot/firstrun.sh`
  documents the target flow but has not run on a real card.

## Screenshots

Admin UI running against the Docker demo (dummy audio, 10 Day course active).

| | |
|---|---|
| **Dashboard** — course day, toggles, next events, test buttons<br><img src="screenshots/dashboard.png" width="400"> | **Courses** — the seeded Dhamma Sudha calendar<br><img src="screenshots/courses.png" width="400"> |
| **Schedule editor** — per-day gong times<br><img src="screenshots/schedule-editor.png" width="400"> | **Day picker** — explicit days override the default pattern<br><img src="screenshots/schedule-day-picker.png" width="400"> |
| **Sounds & volume** — track, volumes, doha time and outside-course mode<br><img src="screenshots/sounds-volume.png" width="400"> | **Time** — set clock, RTC status<br><img src="screenshots/time-set-clock.png" width="400"> |
| **Play history** — every fire logged with result<br><img src="screenshots/logs-play-history.png" width="400"> | **Missed events** — late fires are skipped, never blasted late<br><img src="screenshots/logs-missed-events.png" width="400"> |
| **Backup & restore** — one-file DB download<br><img src="screenshots/backup-restore.png" width="400"> | |

## Develop on a Mac/PC (no hardware)

```bash
cd ng
python3 -m venv .venv && .venv/bin/pip install -e '.[dev]'
.venv/bin/pytest                          # 65 tests

export GONG_DATA_DIR=/tmp/gongdata GONG_CONFIG=/nonexistent
bin/gongctl init                          # schema + seed + media from ../app
bin/gongctl reset-pin --pin 4321
bin/gongctl simulate --course "10 Day" --start 2026-08-01
bin/gongctl status --check

# run the daemon with dummy audio on http://127.0.0.1:8090/
printf '[audio]\nplayer="dummy"\n[web]\nlisten="127.0.0.1:8090"\n' > /tmp/dev.toml
GONG_CONFIG=/tmp/dev.toml .venv/bin/python -m gong_ng
```

## Layout

```
gong_ng/            the daemon: scheduler.py player.py clock.py doha.py
gong_ng/web/        Flask admin UI + API (design §8)
bin/                gongctl, gong-settime (sudo helper), gong-smoke-check
seed/               seed.sql + doha-manifest.json — GENERATED, do not edit
tools/              convert_legacy_seed.py (build-time), hw-spike.sh (M0)
systemd/ os/        units, sudoers, nftables, config.toml.example
firstboot/          firstrun.sh + gong-firstboot.toml.example (M3)
tests/              pytest suite; test_seed.py pins seed.sql to db/gong.sql
```

## Deshna responder (fetch.php compat)

gongd also answers for the legacy **Deshna** appliance — the course-audio
jukebox queried by the Deshna Android app (dhamma.org.deshna). The contract
was reconstructed from the decompiled app (dn3.1) since the original
fetch.php is lost:

```
GET /fetch.php?a=<track_id>|<course_lang_code>|<ip_hash>|<selected_lang>
  -> 200 audio/mpeg (the file), 404 unknown id / missing media
```

The legacy ip-hash token is accepted but **not validated** — the endpoint
serves any client on the network; the AP's WPA2 passphrase is the boundary.

- `seed/deshna-seed.sql` — 30 courses + 3,716 schedule rows, the union of the
  Deshna Pi's MySQL dump and the app's bundled DB (app revision wins on
  conflicts; ids are the contract with the app — never renumber). Regenerate:
  `tools/convert_deshna_seed.py --dump deshna.sql --apk-db assets/deshna.db`.
- Reconstruction caveat: for `multiple`-language tracks, `selected_lang`
  picks the sibling row with that lang code — behaviour for the common
  (single-language) case is exact, this branch is best-effort.
- Point the app's server setting at the gong Pi (legacy default 10.10.0.100).

### Media library layout

The audio lives under `/var/lib/gong/media/deshna/`, one folder per course
type (the `folder` value from the schedule) plus two shared folders. Filenames
must match `deshna_schedule.filename` byte-for-byte — that is exactly what the
app requests. The endpoint 404s harmlessly until media is present.

```
/var/lib/gong/media/deshna/
├── 10-day/  10day-spl/  10day-exec/     Hi-En/  Discourses/Hindi|English/
├── 20-day/  30-day/  60-day/            Hi-En/  Discourses/Hindi/
├── 45-day-10a/  45-day-15a/  45-day-tri/   Hi-En/  Discourses/Hindi/
├── 1-day/  2-day/  3-day/  3-day-full/   Hi-En/  Discourses/
├── stp/  STP/                           Satipatthana — BOTH spellings appear
├── teenager/  gratitude/  group-sittings/   Hi-En/  Discourses/
├── cc1d/  cc2d/  cc3d/                   Hi-En/   (Children's courses)
├── children-1-day-english/  En/         *.mp4
├── children-1-day-hindi/    Hi/         *.mp4
├── children-3-day-hindi/    Hi/         *.mp4 + *.mp3
├── common-general/                      shared chants/suttas, *.mp3 flat
└── common-lang/             Hi-En/      shared welcome/closing tracks
```

Naming inside a language folder:
`D<day>_<HHMM>_<Track>_<Lang>_<Course>.mp3`, e.g.
`10-day/Hi-En/D01_0800_GS_Hi-En_10d.mp3`. 3,281 files are `.mp3`; the 55
`.mp4` files are all under the three `children-*` folders. `common-general/`
and `common-lang/` are not course folders — they are shared prefixes and must
sit as siblings. **`stp/` and `STP/` both appear as literal path prefixes; on
case-sensitive ext4 keep both (or `ln -s stp STP`) or one course 404s.**

### Getting media onto the appliance

Two paths, both driven from the **Deshna tab** in the admin UI:

- **USB auto-mount.** Plug in a stick whose root has a `deshna/` folder: a
  udev rule (`os/udev/99-gong-usb-media.rules`) starts
  `gong-usb-media@<dev>.service`, which bind-mounts `deshna/` live over the
  media dir — tracks are served straight off the stick until it is ejected.
- **Copy onto the Pi.** The tab's *Copy onto the Pi* button (or
  `sudo gong-usb-media copy`) rsyncs the stick into the SD card's media dir,
  overwriting changed files and adding new ones without deleting extras, so the
  update survives removal. *Eject* unbinds and unmounts cleanly.

`bin/gong-usb-media` is the helper (attach/detach are root-only via systemd;
`copy`/`eject`/`status` are sudo-whitelisted for the `gong` user, take no
paths, and regex-validate the device name). By hand over SSH it is just
`rsync -av /media/usb/deshna/ /var/lib/gong/media/deshna/` then
`sudo chown -R gong:gong /var/lib/gong/media/deshna`.

The **Deshna tab** shows the IP to enter in the app, a media-status counter
(files on disk vs schedule), attached-USB status with Copy/Eject buttons, a
one-click fetch test + copyable curl, the directory layout, install steps, and
a troubleshooting checklist.

Manual validation plan (endpoint, tab, USB auto-mount/copy):
[`../docs/DESHNA-QA.md`](../docs/DESHNA-QA.md).

## Key invariants (enforced by tests)

- Doha selection is byte-for-byte the legacy algorithm (`test_doha.py`).
- `seed/seed.sql` must equal the converter output for `../db/gong.sql`
  (`test_seed.py`); re-run `tools/convert_legacy_seed.py` after any change.
- The scheduler never fires early, never double-fires across restarts, fires
  ≤ `fire_grace_seconds` late, and logs `missed` beyond that.
- A clock that went backwards suppresses all automatic playback until staff
  confirm the time (red banner in the UI).

## Break-glass

Forgot the PIN: SSH in, `sudo /opt/gong-ng/bin/gongctl reset-pin`.

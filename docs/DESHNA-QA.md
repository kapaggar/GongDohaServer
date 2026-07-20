# Deshna QA — manual validation

Manual test plan for the Deshna responder, the admin **Deshna** tab, and the
USB media auto-mount/copy mechanism. Split by what can be checked on a
laptop/Docker versus what needs the real Pi + a USB stick.

⚠ Cases in section B could not be exercised on the Mac (no real block device),
so they are the HW-VALIDATE items — run them once on the target board before
field deployment.

Prereqs for A: the Docker demo running on `http://localhost:8090`, admin PIN
`4321` (`docker build -f ng/docker/Dockerfile -t gong-ng . && docker run -d
--name gong-ng-demo -p 8090:80 -e GONG_PIN=4321 gong-ng`).

## A · UI + endpoint (Docker or Pi, no USB needed)

1. **Deshna tab loads.** Log in → **Deshna** in the nav. Expect 7 cards:
   server IP, media status, USB, test responder, media layout, install steps,
   troubleshooting. Media status shows "0 of 3716" on an empty library.

2. **Layout reference present.** The "media library layout" card lists
   `10-day/`, `common-general/`, `common-lang/`, and the `stp/` vs `STP/`
   case-sensitivity note.

3. **fetch.php serves a file.** Place a test MP3 where track 1 expects it:
   ```
   docker exec gong-ng-demo mkdir -p /var/lib/gong/media/deshna/10-day/Hi-En
   docker cp any.mp3 gong-ng-demo:/var/lib/gong/media/deshna/10-day/Hi-En/D00_2000_Anapana_Hi-En_10d.mp3
   curl -v "http://127.0.0.1:8090/fetch.php?a=1" -o out.mp3
   ```
   Expect `200`, `Content-Type: audio/mpeg`, bytes match. Reload the tab →
   status "1 of 3716" and a **▶ Fetch track 1** button appears.

4. **fetch.php is open (no hash gate).**
   ```
   curl -s -o /dev/null -w "%{http_code}\n" "http://127.0.0.1:8090/fetch.php?a=1|hin-eng|deadbeef|"   # 200
   curl -s -o /dev/null -w "%{http_code}\n" "http://127.0.0.1:8090/fetch.php?a=1"                       # 200
   curl -s -o /dev/null -w "%{http_code}\n" "http://127.0.0.1:8090/fetch.php?a=999999"                  # 404
   ```

5. **USB card empty state.** With no USB status file the card reads
   "No Deshna USB detected."

## B · USB mechanism on the real Pi (HW-VALIDATE)

Run on the Pi after a firstboot install, with a USB stick whose root has a
`deshna/` folder holding a couple of real tracks, e.g.
`deshna/10-day/Hi-En/D00_2000_Anapana_Hi-En_10d.mp3`.

6. **Auto-mount on insert.** Plug in the stick; within a few seconds:
   ```
   findmnt /var/lib/gong/media/deshna     # shows the USB bind-mount
   systemctl status 'gong-usb-media@*'    # active (exited), "bind-mounted N files"
   cat /run/gong/usb-media.json           # attached=sdX1, bound=true, mode=mounted
   ```
   Deshna tab → USB card shows "USB sdX1 … served **live from the stick**".

7. **Serve live off the stick.**
   `curl -v "http://<pi-ip>/fetch.php?a=1" -o out.mp3` → `200`, bytes match the
   file on the USB. Media-status counter reflects the stick's files.

8. **Copy onto the Pi.** Tab → **⬇ Copy onto the Pi** (or
   `sudo gong-usb-media copy`). Expect flash "copy complete: N files now in …".
   ```
   findmnt /var/lib/gong/media/deshna                  # NO longer a mount (unbound)
   ls -l /var/lib/gong/media/deshna/10-day/Hi-En/      # files on the SD, owned gong:gong
   ```

9. **Update semantics (overwrite + keep extras).** Before copying, create a
   file only on the SD (`sudo -u gong touch /var/lib/gong/media/deshna/KEEP.txt`)
   and change a file on the USB. Copy again → changed file updated, `KEEP.txt`
   still present, nothing deleted.

10. **Eject.** Tab → **⏏ Eject** (or `sudo gong-usb-media eject`), then unplug.
    Bind and staging mounts gone (`findmnt` clean), `/run/gong/usb-media.json`
    cleared, fetches now serve from the SD copy.

11. **Unplug without eject.** Pull the stick while bound → the detach service
    unmounts it; `findmnt /var/lib/gong/media/deshna` clean, tab returns to
    "No Deshna USB detected" (`journalctl -u 'gong-usb-media-detach@*'`).

12. **Non-Deshna USB ignored.** Plug a stick with no `deshna/` folder → it is
    NOT bind-mounted over the media dir; the media dir keeps showing the SD
    copy.

13. **Security spot-check.** As the `gong` user:
    ```
    sudo -n /opt/gong-ng/bin/gong-usb-media attach sda1     # REFUSED (not whitelisted)
    sudo -n /opt/gong-ng/bin/gong-usb-media copy ../../etc  # fails device-name regex
    ```

## C · Deshna Android app end-to-end (real tablet)

14. **Point + play.** Join the DhammaGong Wi-Fi, set the Deshna app's server to
    the Pi's IP (shown on the tab; port 80, no port number). Pick a course/day
    with media present and play — audio streams. A missing file fails
    gracefully; the Logs page records each failed fetch with its filename.

15. **`multiple`-language track (best-effort branch).** For a course with
    `multiple`-language discourses, switch the app's language and confirm the
    right sibling file plays. This is the least-certain part of the
    reconstruction (original fetch.php is lost), so it is the one to watch on a
    real device.

#!/bin/bash
# M0 hardware spike — run ON THE PI (Bookworm Lite) to resolve every
# ⚠ HW-VALIDATE item in docs/GONG-NG-DESIGN.md before field deployment.
# Needs: an amp/speaker on the 3.5mm jack, the relay wired to GPIO17,
# any MP3 at /tmp/test.mp3. Run each section and note the results.
set -u

echo "=== 1. ALSA device names (expect 'Headphones' card) ==="
aplay -l
command -v mpv >/dev/null && mpv --audio-device=help | sed -n '1,15p'

echo; echo "=== 2. Audible playback through mpv on the jack ==="
echo "   (should hear sound; note the exact --audio-device that works)"
mpv --really-quiet --no-video \
    --audio-device=alsa/plughw:CARD=Headphones /tmp/test.mp3

echo; echo "=== 3. Relay claim + click (GPIO17 active-low) ==="
python3 - <<'EOF'
from gpiozero import DigitalOutputDevice
import time
r = DigitalOutputDevice(17, active_high=False, initial_value=False)
print("relay ON for 2s — listen for the click, check the amp powers up")
r.on(); time.sleep(2); r.off()
print("relay OFF — done")
EOF
echo "   Now REBOOT and watch the relay during kernel boot:"
echo "   if it clicks/glitches ON at any point, GPIO17 fails HW-VALIDATE."

echo; echo "=== 4. AP mode via NetworkManager (WILL drop wlan SSH!) ==="
cat <<'CMD'
  nmcli con add type wifi ifname wlan0 con-name spike-ap autoconnect no \
    ssid GongSpike mode ap ipv4.method shared ipv4.addresses 192.168.5.1/24 \
    wifi.band bg wifi.channel 6 wifi-sec.key-mgmt wpa-psk wifi-sec.psk spike12345
  nmcli con up spike-ap
  # then: join from 5 phones, check DHCP leases + http reachability,
  # leave associated 30 min, watch: journalctl -f -u NetworkManager
  # cleanup: nmcli con delete spike-ap
CMD

echo; echo "=== 5. RTC (only if DS3231 fitted) ==="
echo "  add to config.txt: dtparam=i2c_arm=on + dtoverlay=i2c-rtc,ds3231"
echo "  after reboot: ls /dev/rtc0 && sudo hwclock -r"

#!/bin/sh
# Demo entrypoint: seed the appliance, set a known PIN, optionally arm a
# demo course + near-future gong events, then run gongd in the foreground.
set -e

python -m gong_ng.ctl init
python -m gong_ng.ctl reset-pin --pin "${GONG_PIN:-4321}"

if [ "${GONG_DEMO:-1}" = "1" ]; then
    python /opt/gong-ng/docker/demo_seed.py
fi

exec python -m gong_ng

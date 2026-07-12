#!/bin/bash
# Quick audio + relay smoke test on a deployed Gongserver
set -euo pipefail
HOME_DIR="${GONG_APP_HOME:-/home/dhamma}"
echo "Playing gong-ting…"
mpg123 -q "$HOME_DIR/gong-ting.mp3" || omxplayer --no-keys "$HOME_DIR/gong-ting.mp3"
echo "Done."
if [[ -x "$HOME_DIR/relay-control" ]]; then
  echo "Relay on/off cycle…"
  "$HOME_DIR/relay-control" on || true
  sleep 1
  "$HOME_DIR/relay-control" off || true
fi

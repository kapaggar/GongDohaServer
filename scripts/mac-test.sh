#!/usr/bin/env bash
# Mac/local test harness for Gongserver (Docker).
# Usage:
#   ./scripts/mac-test.sh up
#   ./scripts/mac-test.sh test
#   ./scripts/mac-test.sh gong
#   ./scripts/mac-test.sh doha
#   ./scripts/mac-test.sh logs
#   ./scripts/mac-test.sh down

set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

COMPOSE=(docker compose)
if ! docker compose version >/dev/null 2>&1; then
  COMPOSE=(docker-compose)
fi

cmd="${1:-help}"

case "$cmd" in
  up)
    echo "==> Building and starting stack (http://127.0.0.1:8080/)"
    "${COMPOSE[@]}" up -d --build
    echo "==> Waiting for web…"
    for i in $(seq 1 40); do
      code=$(curl -s -o /dev/null -w "%{http_code}" http://127.0.0.1:8080/ || true)
      if [[ "$code" == "200" ]]; then
        echo "UI is up: http://127.0.0.1:8080/  (HTTP $code)"
        exit 0
      fi
      sleep 2
    done
    echo "Timed out waiting for UI. Try: ./scripts/mac-test.sh logs"
    exit 1
    ;;

  down)
    "${COMPOSE[@]}" down
    ;;

  destroy)
    "${COMPOSE[@]}" down -v
    ;;

  logs)
    "${COMPOSE[@]}" logs --tail=80
    echo "---- gong.log ----"
    "${COMPOSE[@]}" exec -T web cat /var/log/gong.log 2>/dev/null || true
    ;;

  shell)
    "${COMPOSE[@]}" exec web bash
    ;;

  db)
    # mysql client in db container
    "${COMPOSE[@]}" exec db mariadb -ugong -pgongpass gong
    ;;

  # Insert a schedule row for *this* minute so poll.php will fire
  arm-gong)
    hhmm=$(date +%-H%M 2>/dev/null || date +%H%M | sed 's/^0//')
    # portable: strip leading zeros carefully
    hhmm=$(date +%H%M)
    # PHP date("Gi") drops leading zero on hour — e.g. 09:05 -> 905
    stime=$(php -r 'echo date("Gi");')
    echo "Arming No-Course schedule for start_time=$stime (date Gi)"
    "${COMPOSE[@]}" exec -T db mariadb -ugong -pgongpass gong -e \
      "DELETE FROM schedule WHERE day_no=-1 AND start_time=$stime;
       INSERT INTO schedule (type, day_no, start_time, total_repeat) VALUES (-1, -1, $stime, 2);
       UPDATE settings SET enabled=1, gong_enabled=1, doha_enabled=1, relay=0;"
    echo "Now run: ./scripts/mac-test.sh gong"
    ;;

  gong)
    echo "==> Running poll.php inside web container"
    "${COMPOSE[@]}" exec -T web php /home/dhamma/poll.php
    echo "---- last log lines ----"
    "${COMPOSE[@]}" exec -T web tail -n 15 /var/log/gong.log
    ;;

  doha)
    echo "==> Running doha.php (forced, any hour)"
    "${COMPOSE[@]}" exec -T -e GONG_FORCE_DOHA=1 web php /home/dhamma/doha.php
    echo "---- last log lines ----"
    "${COMPOSE[@]}" exec -T web tail -n 15 /var/log/gong.log
    ;;

  test)
    echo "==> Smoke tests"
    code=$(curl -s -o /dev/null -w "%{http_code}" http://127.0.0.1:8080/)
    echo "HTTP UI: $code"
    [[ "$code" == "200" ]] || { echo "FAIL: UI not 200"; exit 1; }

    body=$(curl -s http://127.0.0.1:8080/)
    echo "$body" | grep -q "DhammaGong\|Cron" && echo "UI body: OK" || echo "WARN: unexpected UI body"

    rows=$("${COMPOSE[@]}" exec -T db mariadb -N -ugong -pgongpass gong -e "SELECT COUNT(*) FROM schedule;")
    echo "schedule rows: $rows"
    [[ "$rows" -gt 100 ]] || { echo "FAIL: schedule not imported"; exit 1; }

    # arm + poll
    stime=$(php -r 'echo date("Gi");')
    "${COMPOSE[@]}" exec -T db mariadb -ugong -pgongpass gong -e \
      "DELETE FROM schedule WHERE day_no=-1 AND start_time=$stime;
       INSERT INTO schedule (type, day_no, start_time, total_repeat) VALUES (-1, -1, $stime, 1);
       UPDATE settings SET enabled=1, gong_enabled=1, relay=0;"
    "${COMPOSE[@]}" exec -T web php /home/dhamma/poll.php
    "${COMPOSE[@]}" exec -T web grep -q "Playing" /var/log/gong.log && echo "poll.php: OK (logged play)" || {
      echo "FAIL: no play log"; "${COMPOSE[@]}" exec -T web cat /var/log/gong.log; exit 1;
    }

    "${COMPOSE[@]}" exec -T -e GONG_FORCE_DOHA=1 web php /home/dhamma/doha.php
    "${COMPOSE[@]}" exec -T web grep -q "Doha" /var/log/gong.log && echo "doha.php: OK" || echo "WARN: doha log missing"

    echo ""
    echo "All core smoke tests passed."
    echo "Open UI: http://127.0.0.1:8080/"
    ;;

  help|*)
    cat <<EOF
Gongserver Mac test (Docker)

  ./scripts/mac-test.sh up        Start MariaDB + Apache/PHP on :8080
  ./scripts/mac-test.sh test      Automated smoke tests
  ./scripts/mac-test.sh arm-gong  Insert schedule for current minute
  ./scripts/mac-test.sh gong      Run poll.php once
  ./scripts/mac-test.sh doha      Run doha.php once (forced)
  ./scripts/mac-test.sh logs      Container + gong.log
  ./scripts/mac-test.sh db        MySQL shell
  ./scripts/mac-test.sh shell     bash in web container
  ./scripts/mac-test.sh down      Stop containers
  ./scripts/mac-test.sh destroy   Stop + wipe DB volume

UI:  http://127.0.0.1:8080/
DB:  127.0.0.1:3307  user/pass gong/gongpass  db gong

What this does NOT test:
  - installer/install.sh apt path on real Pi OS
  - hostapd Wi-Fi AP
  - GPIO amplifier relay
  - real Pi audio hardware path
EOF
    ;;
esac

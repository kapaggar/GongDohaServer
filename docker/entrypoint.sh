#!/bin/bash
set -euo pipefail

# Ensure log exists and is writable by cron/php/apache
touch /var/log/gong.log
chmod 666 /var/log/gong.log

# Wait for DB (extra safety)
for i in $(seq 1 30); do
  if php -r '
    $h=getenv("GONG_DB_HOST")?: "db";
    $u=getenv("GONG_DB_USER")?: "gong";
    $p=getenv("GONG_DB_PASS")?: "gongpass";
    $d=getenv("GONG_DB_NAME")?: "gong";
    $c=@mysqli_connect($h,$u,$p,$d);
    exit($c?0:1);
  '; then
    break
  fi
  echo "waiting for db..."
  sleep 2
done

# Enable cron jobs inside container for optional long-running tests
if [[ "${GONG_ENABLE_CRON:-0}" == "1" ]]; then
  cat >/etc/cron.d/gongserver <<'EOF'
SHELL=/bin/sh
PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
* * * * * root /usr/local/bin/php /home/dhamma/poll.php >/dev/null 2>&1
37 6 * * * root /usr/local/bin/php /home/dhamma/doha.php >/dev/null 2>&1
EOF
  chmod 644 /etc/cron.d/gongserver
  service cron start || true
fi

exec "$@"

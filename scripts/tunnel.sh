#!/bin/bash
# Публічний тунель до стенду зарплати (127.0.0.1:$ODOO_PORT) через localhost.run.
# Поточну адресу публікує у Worker посилання (odoo-demo.botpartners.workers.dev, POST /set).
# Адреса тунелю змінюється при перепідключенні; Worker ховає це за сталим посиланням. launchd: com.kit.odoo-payroll-tunnel.
set -u
ROOT="$(cd "$(dirname "$0")/.." && pwd)"; LOG="$ROOT/demo-out/tunnel.log"; mkdir -p "$ROOT/demo-out"
LINK="https://odoo-demo.botpartners.workers.dev"
envval(){ grep "^$1=" "$ROOT/.env" 2>/dev/null | cut -d= -f2-; }
PORT="$(envval ODOO_PORT)"; PORT="${PORT:-8110}"
log(){ printf '%s %s\n' "$(date -u +%FT%TZ)" "$*" >> "$LOG"; }
publish(){ for i in 1 2 3 4 5 6; do
  out=$(curl -s -m 20 -X POST "$LINK/set" -H "Authorization: Bearer $(envval ODOO_DEMO_LINK_TOKEN)" --data-urlencode "url=$1" 2>&1)
  [ "$out" = "ok" ] && { log "published $1"; return 0; }
  log "publish retry $i ($out)"; sleep 15; done; return 1; }
until curl -s -o /dev/null -m 5 "http://127.0.0.1:$PORT/web/login"; do log "waiting for local odoo :$PORT"; sleep 15; done
log "starting localhost.run tunnel -> :$PORT"
# watchdog: якщо тунель не відповідає двічі поспіль, вбиваємо ssh; launchd перезапускає скрипт і публікує нову адресу
( fails=0; while sleep 120; do u=$(cat "$ROOT/demo-out/current_url" 2>/dev/null); [ -z "$u" ] && continue
    code=$(curl -s -o /dev/null -w '%{http_code}' -m 20 "$u/web/login"); case "$code" in 200|303|302) fails=0;; *) fails=$((fails+1)); log "watchdog: $u -> $code ($fails)";; esac
    [ "$fails" -ge 2 ] && { log "watchdog: tunnel dead, restarting ssh"; pkill -f "nokey@localhost.run"; fails=0; }
  done ) & WD_PID=$!
trap 'kill $WD_PID 2>/dev/null' EXIT
ssh -o StrictHostKeyChecking=accept-new -o ServerAliveInterval=30 -o ServerAliveCountMax=3 \
    -o ExitOnForwardFailure=yes -o ConnectTimeout=25 -T \
    -R "80:127.0.0.1:$PORT" nokey@localhost.run 2>&1 | while IFS= read -r line; do
  clean=$(printf '%s' "$line" | sed 's/\x1b\[[0-9;]*m//g')
  [ -n "${clean// /}" ] && log "ssh: ${clean:0:180}"
  if [[ "$clean" =~ (https://[a-z0-9]+\.lhr\.life) ]]; then
    url="${BASH_REMATCH[1]}"; echo "$url" > "$ROOT/demo-out/current_url"; publish "$url" &
    ( while sleep 300; do [ "$(cat "$ROOT/demo-out/current_url" 2>/dev/null)" = "$url" ] || exit 0; publish "$url" >/dev/null; done ) &
  fi
done
log "localhost.run exited; launchd restarts"; rm -f "$ROOT/demo-out/current_url"; sleep 10

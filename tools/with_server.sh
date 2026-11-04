#!/usr/bin/env bash
# with_server.sh [--port P] -- CMD... -- run CMD against a server of its own.
#
# Starts the Elysium server on a free port (or P) with a temporary state
# directory and the fixture deployment (deployment/etc copied in), waits for
# /api/v2/health/ready (/api/health while the v2 route does not exist), runs
# CMD with ELYSIUM_URL set, stops the server and exits with CMD's status.
# The server is `elysium server run` when the CLI has it, else
# `uvicorn elysium.api.app:app`. Nothing of the owner's server is touched.
#
# Exit: CMD's status; 2 usage; 3 the server did not start or never got ready.
# WITH_SERVER_WAIT sets the seconds to wait for readiness (default 60).
set -uo pipefail

port=
while [ "$#" -gt 0 ]; do
    case "$1" in
        --port) port=${2:-}; shift 2 || { echo "with_server: --port needs a value" >&2; exit 2; } ;;
        --) shift; break ;;
        *) echo "usage: tools/with_server.sh [--port P] -- CMD..." >&2; exit 2 ;;
    esac
done
if [ "$#" -eq 0 ]; then
    echo "usage: tools/with_server.sh [--port P] -- CMD..." >&2
    exit 2
fi

root=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
if [ -z "$port" ]; then
    port=$(python - <<'PY'
import socket
with socket.socket() as s:
    s.bind(("127.0.0.1", 0))
    print(s.getsockname()[1])
PY
)
fi

state=$(mktemp -d "${TMPDIR:-/tmp}/elysium-with-server.XXXXXX")
mkdir -p "$state/etc" "$state/data" "$state/log"
cp -r "$root/deployment/etc/." "$state/etc/"
export ELYSIUM_CONFIG_DIR=$state/etc ELYSIUM_DATA_DIR=$state/data ELYSIUM_LOG_DIR=$state/log
log=$state/server.log

pid=
stop() {
    if [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null; then
        kill "$pid" 2>/dev/null
        for _ in 1 2 3 4 5 6 7 8 9 10; do kill -0 "$pid" 2>/dev/null || break; sleep 0.5; done
        kill -9 "$pid" 2>/dev/null
        wait "$pid" 2>/dev/null
    fi
    rm -rf "$state"
}
trap stop EXIT

cd "$root" || exit 3
if python -m elysium.cli server run --help >/dev/null 2>&1; then
    python -m elysium.cli server run --port "$port" >"$log" 2>&1 &
else
    python -m uvicorn elysium.api.app:app --host 127.0.0.1 --port "$port" >"$log" 2>&1 &
fi
pid=$!

url=http://127.0.0.1:$port
deadline=$((SECONDS + ${WITH_SERVER_WAIT:-60}))
ready=0
while [ "$SECONDS" -lt "$deadline" ]; do
    if ! kill -0 "$pid" 2>/dev/null; then break; fi
    if curl -fsS -o /dev/null "$url/api/v2/health/ready" 2>/dev/null \
        || curl -fsS -o /dev/null "$url/api/health" 2>/dev/null; then
        ready=1
        break
    fi
    sleep 0.3
done
if [ "$ready" -ne 1 ]; then
    echo "with_server: the server did not become ready on port $port; its log:" >&2
    tail -n 30 "$log" >&2
    exit 3
fi

ELYSIUM_URL=$url "$@"
status=$?
exit "$status"

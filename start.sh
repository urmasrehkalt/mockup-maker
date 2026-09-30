#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"

# PORT tuleb keskkonnast, siis .env failist, vaikimisi 8010
if [ -z "${PORT:-}" ] && [ -f .env ]; then
    PORT=$(sed -n 's/^PORT=//p' .env | tail -1)
fi
PORT="${PORT:-8010}"
PYTHON="${PYTHON:-python3.12}"
VENV_DIR=".venv"
PID_FILE=".uvicorn.pid"
LOG_FILE=".uvicorn.log"

cmd="${1:-start}"

is_running() {
    [ -f "$PID_FILE" ] || return 1
    local pid
    pid=$(cat "$PID_FILE" 2>/dev/null || true)
    [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null
}

stop_server() {
    if is_running; then
        local pid
        pid=$(cat "$PID_FILE")
        echo "→ Peatan serveri (PID $pid)…"
        kill "$pid" 2>/dev/null || true
        # Oota kuni 5s graceful shutdown
        for _ in 1 2 3 4 5; do
            kill -0 "$pid" 2>/dev/null || break
            sleep 1
        done
        kill -9 "$pid" 2>/dev/null || true
        rm -f "$PID_FILE"
    fi
    # Tagavaraks: tapa selle pordi uvicorn (sama masina teisi rakendusi ei puuduta)
    pkill -f "uvicorn app.main:app --port $PORT" 2>/dev/null || true
}

status_server() {
    if is_running; then
        local pid port
        pid=$(cat "$PID_FILE")
        port=$(lsof -nP -iTCP -sTCP:LISTEN -a -p "$pid" 2>/dev/null | awk 'NR==2 {print $9}' | sed 's/.*://')
        echo "✓ Server jookseb (PID $pid${port:+, pordil $port})"
        exit 0
    else
        echo "✗ Server ei jookse"
        exit 1
    fi
}

start_server() {
    # Kui server juba jookseb, peata ja restardi
    if is_running; then
        echo "→ Server juba jookseb (PID $(cat "$PID_FILE")), restardin"
        stop_server
    fi

    # Setup venv kui puudub
    if [ ! -d "$VENV_DIR" ]; then
        echo "→ Loon virtuaalkeskkonna ($VENV_DIR)…"
        "$PYTHON" -m venv "$VENV_DIR"
    fi

    # shellcheck disable=SC1091
    source "$VENV_DIR/bin/activate"

    if ! python -c "import fastapi" 2>/dev/null; then
        echo "→ Installin sõltuvused…"
        pip install --quiet --upgrade pip
        pip install --quiet -r requirements.txt
    fi

    echo "→ Käivitan uvicorn taustal pordil $PORT (logid: $LOG_FILE)"
    nohup "$VENV_DIR/bin/uvicorn" app.main:app --port "$PORT" >"$LOG_FILE" 2>&1 &
    local pid=$!
    echo "$pid" >"$PID_FILE"

    # Oota kuni server vastab healthcheckile (max 10s)
    for _ in 1 2 3 4 5 6 7 8 9 10; do
        if curl -sf "http://localhost:$PORT/api/health" >/dev/null 2>&1; then
            echo "✓ Server valmis (PID $pid): http://localhost:$PORT"
            exit 0
        fi
        kill -0 "$pid" 2>/dev/null || {
            echo "✗ Server suri käivitumise ajal. Vaata $LOG_FILE:"
            tail -20 "$LOG_FILE"
            exit 1
        }
        sleep 1
    done
    echo "⚠ Server pole 10s jooksul vastanud, vaata logi:"
    tail -10 "$LOG_FILE"
}

case "$cmd" in
    start|restart) start_server ;;
    stop) stop_server; echo "✓ Peatatud" ;;
    status) status_server ;;
    *) echo "Kasutus: $0 [start|stop|restart|status]" >&2; exit 1 ;;
esac

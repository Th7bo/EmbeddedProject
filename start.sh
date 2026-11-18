#!/usr/bin/env bash
# Starts a game on this PC with one command: Mosquitto broker + rules controller + dashboard.
#
#   ./start.sh            real game
#   ./start.sh --sim      also accept the simulator's fake tags (testing)
#   NO_BROWSER=1 ./start.sh   don't open the dashboard
#
# Any extra arguments go to the controller (see: cd controller && uv run python -m snl --help).
# Ctrl+C stops everything this script started.
set -euo pipefail
cd "$(dirname "$0")"

die() { echo "error: $*" >&2; exit 1; }
command -v mosquitto >/dev/null || die "mosquitto not installed (Fedora: sudo dnf install mosquitto)"
command -v uv >/dev/null || die "uv not installed (https://docs.astral.sh/uv/)"

# --- broker: start our own unless one already listens on 1883
broker_pid=""
if ss -ltn 2>/dev/null | grep -q ':1883 '; then
  echo "broker: already running on port 1883, using it"
else
  mosquitto -c controller/mosquitto.conf >/tmp/snl-mosquitto.log 2>&1 &
  broker_pid=$!
  sleep 0.5
  kill -0 "$broker_pid" 2>/dev/null || die "mosquitto did not start, see /tmp/snl-mosquitto.log"
  echo "broker: mosquitto started (log: /tmp/snl-mosquitto.log)"
fi
cleanup() { [ -n "$broker_pid" ] && kill "$broker_pid" 2>/dev/null && echo "broker: stopped"; }
trap cleanup EXIT

# --- the ESPs connect to MQTT_HOST from firmware/include/secrets.h: warn if this PC has another IP
ip=$(ip -4 route get 1.1.1.1 2>/dev/null | sed -n 's/.* src \([0-9.]*\).*/\1/p')
want=$(sed -n 's/^#define MQTT_HOST "\([^"]*\)".*/\1/p' firmware/include/secrets.h 2>/dev/null || true)
echo "network: this PC is ${ip:-offline}"
if [ -n "$want" ] && [ "$want" != "$ip" ]; then
  echo "WARNING: the ESPs look for the broker at $want (firmware/include/secrets.h)."
  echo "         Join the right Wi-Fi, or change MQTT_HOST and reflash the base + meeples."
fi

# --- dashboard in the browser once the controller is up
if [ -z "${NO_BROWSER:-}" ] && command -v xdg-open >/dev/null; then
  (sleep 2; xdg-open http://localhost:8080 >/dev/null 2>&1 || true) &
fi

echo "dashboard: http://localhost:8080   (Ctrl+C to stop)"
(cd controller && uv run python -u -m snl "$@")  # not exec: the trap must stop the broker afterwards

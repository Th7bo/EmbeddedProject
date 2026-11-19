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

# --- Wi-Fi hotspot on this laptop for the ESPs (SSID + password from firmware/include/secrets.h).
# A phone hotspot drops devices at ~5 clients, so the laptop is the access point (10.42.0.1).
# Its Wi-Fi card is then busy: for internet use USB tethering or ethernet.
# NO_HOTSPOT=1 ./start.sh skips this (e.g. when everything is on another network).
secrets=firmware/include/secrets.h
def() { sed -n "s/^#define $1 \"\([^\"]*\)\".*/\1/p" "$secrets" 2>/dev/null || true; }
ssid=$(def WIFI_SSID); pass=$(def WIFI_PASS); want=$(def MQTT_HOST)
hs=snl-hotspot
if [ -z "${NO_HOTSPOT:-}" ]; then
  [ -n "$ssid" ] && [ -n "$pass" ] || die "WIFI_SSID / WIFI_PASS missing in $secrets"
  ifname=${HOTSPOT_IF:-$(nmcli -t -f DEVICE,TYPE dev | sed -n 's/^\([^:]*\):wifi$/\1/p' | head -1)}
  [ -n "$ifname" ] || die "no Wi-Fi interface found (set HOTSPOT_IF)"
  # (re)create the profile so it always matches secrets.h; 2.4 GHz WPA2, the ESP-01 can't do more
  nmcli con delete "$hs" >/dev/null 2>&1 || true
  nmcli con add type wifi ifname "$ifname" con-name "$hs" autoconnect no ssid "$ssid" \
    802-11-wireless.mode ap 802-11-wireless.band bg 802-11-wireless.channel 6 \
    wifi-sec.key-mgmt wpa-psk wifi-sec.proto rsn wifi-sec.pairwise ccmp wifi-sec.group ccmp \
    wifi-sec.psk "$pass" ipv4.method shared ipv4.addresses 10.42.0.1/24 ipv6.method disabled \
    >/dev/null || die "could not create the hotspot profile"
  nmcli con up "$hs" >/dev/null || die "hotspot did not start (nmcli con up $hs)"
  echo "hotspot: '$ssid' on $ifname, laptop is 10.42.0.1"
  # Fedora firewall: the hotspot zone (nm-shared) only lets DHCP/DNS in, the ESPs need MQTT
  if command -v firewall-cmd >/dev/null && firewall-cmd --state >/dev/null 2>&1 \
     && ! firewall-cmd --zone=nm-shared --query-port=1883/tcp >/dev/null 2>&1; then
    echo "firewall: opening MQTT port 1883 on the hotspot (one time, needs sudo)"
    sudo firewall-cmd --permanent --zone=nm-shared --add-port=1883/tcp >/dev/null \
      && sudo firewall-cmd --reload >/dev/null || echo "WARNING: port 1883 still closed, ESPs can't reach the broker"
  fi
  stop_hotspot() { nmcli con down "$hs" >/dev/null 2>&1 && echo "hotspot: stopped"; }
else
  stop_hotspot() { :; }
fi
trap 'cleanup; stop_hotspot' EXIT

# --- the ESPs connect to MQTT_HOST from secrets.h: warn if this PC doesn't have that IP
echo "network: this PC is $(ip -4 -o addr show scope global | awk '{print $4}' | cut -d/ -f1 | grep -v '^172\.1[78]\.' | paste -sd' ')"
if [ -n "$want" ] && ! ip -4 -o addr show | grep -q "inet $want/"; then
  echo "WARNING: the ESPs look for the broker at $want ($secrets), this PC doesn't have that IP."
  echo "         Join the right Wi-Fi, or change MQTT_HOST and reflash the base + meeples."
fi

# --- dashboard in the browser once the controller is up
if [ -z "${NO_BROWSER:-}" ] && command -v xdg-open >/dev/null; then
  (sleep 2; xdg-open http://localhost:8080 >/dev/null 2>&1 || true) &
fi

echo "dashboard: http://localhost:8080   (Ctrl+C to stop)"
(cd controller && uv run python -u -m snl "$@")  # not exec: the trap must stop the broker afterwards

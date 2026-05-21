#!/usr/bin/env bash
set -euo pipefail

PORT=5555
CONNECT_TIMEOUT=10
RETRY_LIMIT=3

# ── helpers ──────────────────────────────────────────────────────────────────
log()  { echo "[$(date +%H:%M:%S)] $*"; }
err()  { echo "[$(date +%H:%M:%S)] ERROR: $*" >&2; }
die()  { err "$*"; exit 1; }

# ── 1. verify adb is available ───────────────────────────────────────────────
command -v adb &>/dev/null || die "adb not found in PATH"
log "adb found: $(adb version | head -1)"

# ── 2. reset adb server ───────────────────────────────────────────────────────
log "Resetting ADB server..."
# Kill any running emulators first — they bind localhost:5555 and poison adb connect
for EMU in $(adb devices 2>/dev/null | awk '/^emulator-/{print $1}'); do
  log "Killing emulator $EMU..."
  adb -s "$EMU" emu kill 2>/dev/null || true
done
adb kill-server 2>/dev/null; sleep 2
adb start-server 2>/dev/null; sleep 1
log "ADB server restarted."

# ── 3. find a USB-connected device (non-wireless) ────────────────────────────
log "Scanning for USB-connected device..."
USB_DEVICE=$(adb devices | awk 'NR>1 && /device$/ && !/:[0-9]+[[:space:]]/' | awk '{print $1}' | head -1)
[[ -z "$USB_DEVICE" ]] && die "No USB device found. Plug in device and enable USB debugging."
log "Found USB device: $USB_DEVICE"

# ── 4. enable tcpip mode ─────────────────────────────────────────────────────
log "Enabling TCP/IP on port $PORT..."
adb -s "$USB_DEVICE" tcpip "$PORT" 2>&1 | grep -v '^$' || die "Failed to set tcpip mode"
sleep 5   # device needs a moment to re-bind; 2 s is often too short

# ── 5. get device IP via wlan0 ───────────────────────────────────────────────
log "Fetching device IP address..."
DEVICE_IP=""
for i in $(seq 1 $RETRY_LIMIT); do
  DEVICE_IP=$(adb -s "$USB_DEVICE" shell ip route 2>/dev/null \
    | awk '/wlan0/ && /src/ {print $NF}' | tr -d '[:space:]')
  [[ -n "$DEVICE_IP" ]] && break
  log "  Attempt $i/$RETRY_LIMIT: IP not found yet, retrying..."
  sleep 2
done
[[ -z "$DEVICE_IP" ]] && die "Could not determine device IP. Is Wi-Fi connected?"
log "Device IP: $DEVICE_IP"

# ── 6. connect wirelessly ─────────────────────────────────────────────────────
TARGET="$DEVICE_IP:$PORT"
log "Connecting to $TARGET..."
for i in $(seq 1 6); do
  RESULT=$(adb connect "$TARGET" 2>&1)
  if echo "$RESULT" | grep -qE "connected to|already connected"; then
    log "Connected: $RESULT"
    break
  fi
  log "  Attempt $i/6 failed: $RESULT"
  sleep 4
  [[ $i -eq 6 ]] && die "Failed to connect after 6 attempts."
done

# ── 7. verify ────────────────────────────────────────────────────────────────
log "Verifying connection..."
WIRELESS_CHECK=$(adb devices | grep "$TARGET" | awk '{print $2}')
[[ "$WIRELESS_CHECK" == "device" ]] || die "Verification failed — $TARGET not in device list."

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo " ✓  ADB wireless ready: $TARGET"
echo "    You can now unplug the USB cable."
echo "    Reconnect anytime with:"
echo "      adb connect $TARGET"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

#!/usr/bin/env bash
set -euo pipefail

STATE_DIR="${GYM_ANYTHING_RT_STATE_DIR:-/tmp/gym_anything_rt}"
PORT="${GYM_ANYTHING_RT_PORT:-8787}"
TIME_MODE="${GYM_ANYTHING_RT_TIME_MODE:-live}"
START_PAUSED="${GYM_ANYTHING_RT_START_PAUSED:-0}"
TIME_SCALE="${GYM_ANYTHING_RT_TIME_SCALE:-1}"
WINDOW_ATTEMPTS="${GYM_ANYTHING_RT_WINDOW_ATTEMPTS:-60}"
WINDOW_POLL_SECONDS="${GYM_ANYTHING_RT_WINDOW_POLL_SECONDS:-0.5}"
GEOMETRY_ATTEMPTS="${GYM_ANYTHING_RT_GEOMETRY_ATTEMPTS:-40}"
GEOMETRY_POLL_SECONDS="${GYM_ANYTHING_RT_GEOMETRY_POLL_SECONDS:-0.25}"
LOCK_ATTEMPTS="${GYM_ANYTHING_RT_BROWSER_LOCK_ATTEMPTS:-600}"
LOCK_POLL_SECONDS="${GYM_ANYTHING_RT_BROWSER_LOCK_POLL_SECONDS:-0.1}"
if [ "$TIME_MODE" != "live" ] && [ "$TIME_MODE" != "paused" ]; then
  echo "GYM_ANYTHING_RT_TIME_MODE must be live or paused" >&2
  exit 2
fi
URL="http://127.0.0.1:${PORT}/?task=$(date +%s)&time_mode=${TIME_MODE}&start_paused=${START_PAUSED}&time_control=1&time_scale=${TIME_SCALE}"

mkdir -p "$STATE_DIR"

browser_cmd="${GYM_ANYTHING_RT_BROWSER_COMMAND:-}"
if [ -z "$browser_cmd" ]; then
  for candidate in google-chrome-stable google-chrome chromium chromium-browser firefox /snap/bin/firefox; do
    if command -v "$candidate" >/dev/null 2>&1 || [ -x "$candidate" ]; then
      browser_cmd="$candidate"
      break
    fi
  done
fi

if [ -z "$browser_cmd" ]; then
  echo "No browser command found for Gym-Anything-RT." | tee -a /tmp/gym_anything_rt_browser.log
  exit 0
fi

launch_as_user="${GYM_ANYTHING_RT_BROWSER_USER:-}"
home_dir="${GYM_ANYTHING_RT_BROWSER_HOME:-}"
if [ -z "$launch_as_user" ]; then
  launch_as_user="root"
  home_dir="/root"
  if id ga >/dev/null 2>&1; then
    launch_as_user="ga"
    home_dir="/home/ga"
  fi
elif [ -z "$home_dir" ]; then
  home_dir="$(getent passwd "$launch_as_user" | cut -d: -f6)"
  if [ -z "$home_dir" ]; then
    echo "Cannot determine home directory for $launch_as_user." >&2
    exit 1
  fi
fi

xauth=""
for candidate in "$home_dir/.Xauthority" "/run/user/1000/gdm/Xauthority"; do
  if [ -f "$candidate" ]; then
    xauth="$candidate"
    break
  fi
done

# Snap-confined Firefox cannot open arbitrary hidden profile directories under
# $HOME.  A non-hidden path works for both Firefox and Chromium.
profile_dir="$home_dir/gym-anything-rt-profile"
mkdir -p "$profile_dir"
cat > "$profile_dir/user.js" <<'EOF'
// The evaluation viewport must contain only the task.  A fresh Firefox
// profile otherwise displays its data-reporting notice above the page and
// shifts every screenshot and pointer coordinate by the notice height.
user_pref("datareporting.policy.dataSubmissionEnabled", false);
user_pref("datareporting.healthreport.uploadEnabled", false);
user_pref("datareporting.policy.dataSubmissionPolicyBypassNotification", true);
user_pref("toolkit.telemetry.reportingpolicy.firstRun", false);
user_pref("browser.aboutwelcome.enabled", false);
user_pref("browser.startup.homepage_override.mstone", "ignore");
user_pref("browser.shell.checkDefaultBrowser", false);
// Reverse Identity explicitly creates browser tabs.  Firefox may otherwise
// promote script-opened targets to separate kiosk windows, where Ctrl+number
// cannot reach the master tab through the standard keyboard action surface.
user_pref("browser.link.open_newwindow", 3);
user_pref("browser.link.open_newwindow.restriction", 0);
EOF
chown -R "$launch_as_user:$launch_as_user" "$profile_dir" 2>/dev/null || true

if command -v xhost >/dev/null 2>&1; then
  DISPLAY=:1 xhost +SI:localuser:"$launch_as_user" >/dev/null 2>&1 || true
fi

env_prefix="DISPLAY=:1 HOME=$home_dir"
if [ -n "$xauth" ]; then
  env_prefix="$env_prefix XAUTHORITY=$xauth"
fi

if [[ "$browser_cmd" == *firefox ]]; then
  launch="$env_prefix $browser_cmd --new-instance --kiosk --profile '$profile_dir' '$URL'"
else
  # Multi-tab puzzles retain live task state in their opener. Prevent Chromium
  # from discarding and later reloading that background tab during a long
  # interaction; a reload would issue a second /state request and invalidate
  # the still-open authored child tabs.
  launch="$env_prefix $browser_cmd --kiosk '$URL' --force-device-scale-factor=1 --no-first-run --no-default-browser-check --disable-background-networking --disable-sync --disable-infobars --disable-session-crashed-bubble --hide-crash-restore-bubble --disable-backgrounding-occluded-windows --disable-renderer-backgrounding --disable-features=AutomaticTabDiscarding,MemorySaverMode --no-sandbox --disable-dev-shm-usage --user-data-dir='$profile_dir'"
fi

find_puzzle_window() {
  DISPLAY=:1 wmctrl -lx 2>/dev/null | awk 'tolower($0) ~ /gym-anything-rt/ {print $1; exit}' || true
}

verify_puzzle_window() {
  local window_id="$1"
  local display_size display_width display_height geometry
  local window_x window_y window_width window_height

  DISPLAY=:1 wmctrl -i -r "$window_id" -b add,fullscreen,maximized_vert,maximized_horz 2>/dev/null || true
  DISPLAY=:1 wmctrl -i -a "$window_id" 2>/dev/null || true
  display_size="$(
    DISPLAY=:1 xdpyinfo 2>/dev/null |
      awk '/dimensions:/ && !found {print $2; found=1} END {if (!found) exit 1}' || true
  )"
  display_width="${display_size%x*}"
  display_height="${display_size#*x}"
  if ! [[ "$display_width" =~ ^[0-9]+$ && "$display_height" =~ ^[0-9]+$ ]]; then
    echo "Puzzle browser fullscreen verification failed: display geometry unavailable." >> /tmp/gym_anything_rt_browser.log
    return 1
  fi

  for _ in $(seq 1 "$GEOMETRY_ATTEMPTS"); do
    geometry="$(DISPLAY=:1 wmctrl -lG 2>/dev/null | awk -v id="$window_id" '$1 == id {print $3, $4, $5, $6; exit}' || true)"
    read -r window_x window_y window_width window_height <<< "$geometry"
    if [ "$window_x" = "0" ] && [ "$window_y" = "0" ] && \
       [ "$window_width" = "$display_width" ] && [ "$window_height" = "$display_height" ]; then
      echo "Puzzle browser fullscreen verified at ${window_width}x${window_height}+${window_x}+${window_y}." >> /tmp/gym_anything_rt_browser.log
      return 0
    fi
    sleep "$GEOMETRY_POLL_SECONDS"
  done

  echo "Puzzle browser fullscreen verification failed: display=${display_width}x${display_height} window=${geometry:-missing}." >> /tmp/gym_anything_rt_browser.log
  return 1
}

# Serialize the discovery and launch path. Two concurrent hook invocations must
# not both miss the window and start Firefox with the same profile.
lock_dir="$STATE_DIR/browser-launch.lock"
lock_acquired=0
release_launch_lock() {
  if [ "$lock_acquired" = "1" ]; then
    rm -f "$lock_dir/owner"
    rmdir "$lock_dir" 2>/dev/null || true
  fi
}
trap release_launch_lock EXIT

for _ in $(seq 1 "$LOCK_ATTEMPTS"); do
  if mkdir "$lock_dir" 2>/dev/null; then
    lock_acquired=1
    printf '%s\n' "$$" > "$lock_dir/owner"
    break
  fi
  owner_pid="$(cat "$lock_dir/owner" 2>/dev/null || true)"
  if [[ "$owner_pid" =~ ^[0-9]+$ ]] && ! kill -0 "$owner_pid" 2>/dev/null; then
    rm -f "$lock_dir/owner"
    rmdir "$lock_dir" 2>/dev/null || true
    continue
  fi
  sleep "$LOCK_POLL_SECONDS"
done
if [ "$lock_acquired" != "1" ]; then
  echo "Puzzle browser launch lock timed out." >> /tmp/gym_anything_rt_browser.log
  exit 1
fi

# Gym Anything can invoke the task hook twice during one reset. Once the first
# call has opened the task, the next call reuses that exact puzzle window.
existing_window_id="$(find_puzzle_window)"
if [ -n "$existing_window_id" ]; then
  echo "Reusing existing puzzle browser window $existing_window_id." >> /tmp/gym_anything_rt_browser.log
  verify_puzzle_window "$existing_window_id"
  exit $?
fi

echo "Launching puzzle browser as $launch_as_user via $browser_cmd -> $URL" >> /tmp/gym_anything_rt_browser.log
if [ "$launch_as_user" = "root" ]; then
  nohup bash -lc "$launch" >> /tmp/gym_anything_rt_browser.log 2>&1 &
else
  nohup sudo -u "$launch_as_user" bash -lc "$launch" >> /tmp/gym_anything_rt_browser.log 2>&1 &
fi

for _ in $(seq 1 "$WINDOW_ATTEMPTS"); do
  window_id="$(find_puzzle_window)"
  if [ -n "$window_id" ]; then
    verify_puzzle_window "$window_id"
    exit $?
  fi
  sleep "$WINDOW_POLL_SECONDS"
done

echo "Puzzle browser window was not detected before timeout." >> /tmp/gym_anything_rt_browser.log
DISPLAY=:1 wmctrl -l >> /tmp/gym_anything_rt_browser.log 2>&1 || true
exit 1

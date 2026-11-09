#!/bin/bash
# devbench-cli.sh -- talk to a RUNNING Skyrim via alandtse's DevBench SKSE plugin.
#
# DevBench (Nexus SE 181326) runs a localhost REST+MCP server inside the live game, so agents can
# inspect state, run console commands AND READ THEIR OUTPUT, call Papyrus functions, and drive
# scripted scenarios -- instead of you hand-testing and reporting back.
#
# NOT bundled: install DevBench yourself from Nexus (GPL-3.0). This wrapper just drives its REST API.
#
# The game must be running with DevBench loaded. Discovery, input and menu tools can work
# at the Main Menu; world inspection and Papyrus calls require a loaded game.
#
# Usage:
#   bash tools/devbench-cli.sh ping                       # server self-test (NOT proof of liveness)
#   bash tools/devbench-cli.sh alive                      # is the GAME running / paused / hung?
#   bash tools/devbench-cli.sh health                     # raw off-thread liveness+identity probe
#   bash tools/devbench-cli.sh state                      # {plugin,version,vr,playerLoaded,frame,pid,port,exe}
#   bash tools/devbench-cli.sh inspect vm                 # kinds: state health vm scene mods player
#                                                         #        inventory quests effects refs
#   bash tools/devbench-cli.sh exec "player.getav health" # console exec + capture + read output
#   bash tools/devbench-cli.sh call Utility GetCurrentGameTime
#   bash tools/devbench-cli.sh call Actor IsInCombat '[]' '{"form":"0x14"}'
#   bash tools/devbench-cli.sh tools                      # discover installed tools and schemas
#   bash tools/devbench-cli.sh gfx '{"op":"get","menu":"Dialogue Menu","path":"_root"}'
#   bash tools/devbench-cli.sh dialogue '{"action":"inspect"}'
#   bash tools/devbench-cli.sh tool menu '{"action":"accept"}'   # raw escape hatch: any tool, any JSON
#
# Port: read from Data/SKSE/Plugins/devbench/runtime.json when present, else the per-runtime default
# (VR 8921, SE/AE 8920). Override with DEVBENCH_PORT=nnnn.

set -u
# Every command here pipes the HTTP helper into a formatter; without pipefail a dead server (-> 1)
# would be masked by the formatter's 0 and the caller would think the call succeeded.
set -o pipefail

GAME_DIR="${GAME_DIR:-$(pwd)}"
# Explicit path also supports a CrossOver bottle or MO2 overwrite directory.
RUNTIME_JSON="${DEVBENCH_RUNTIME_JSON:-$GAME_DIR/Data/SKSE/Plugins/devbench/runtime.json}"
TIMEOUT="${DEVBENCH_TIMEOUT:-15}"

command -v curl >/dev/null 2>&1 || { echo "ERROR: curl not found." >&2; exit 1; }
HAVE_JQ=0; command -v jq >/dev/null 2>&1 && HAVE_JQ=1

# --- Resolve the port -------------------------------------------------------
resolve_port() {
    if [ -n "${DEVBENCH_PORT:-}" ]; then echo "$DEVBENCH_PORT"; return; fi
    # DevBench writes the port it actually bound here (it iterates if the default was taken).
    if [ -f "$RUNTIME_JSON" ]; then
        p=$(sed -n 's/.*"port"[[:space:]]*:[[:space:]]*\([0-9][0-9]*\).*/\1/p' "$RUNTIME_JSON" | head -1)
        if [ "${p:-0}" -ge 1 ] 2>/dev/null && [ "${p:-0}" -le 65535 ] 2>/dev/null; then
            echo "$p"; return
        fi
    fi
    # Server.cpp mirrors runtime.json outside the mod manager's virtual filesystem.
    if [ -z "${DEVBENCH_RUNTIME_JSON:-}" ] && [ -n "${LOCALAPPDATA:-}" ]; then
        local runtime=se
        [ -f "$GAME_DIR/SkyrimVR.exe" ] && runtime=vr
        local external="$LOCALAPPDATA/devbench/$runtime/runtime.json"
        if [ -f "$external" ] && [ "$external" != "$RUNTIME_JSON" ]; then
            RUNTIME_JSON="$external"
            DEVBENCH_RUNTIME_JSON="$external"
            resolve_port; return
        fi
    fi
    # Fall back to the deterministic per-runtime default.
    [ -f "$GAME_DIR/SkyrimVR.exe" ] && { echo 8921; return; }
    echo 8920
}
PORT="$(resolve_port)"
BASE="http://127.0.0.1:$PORT"

pretty() { if [ "$HAVE_JQ" -eq 1 ]; then jq . 2>/dev/null || cat; else cat; fi; }

dead_port() {
    echo "ERROR: no response from DevBench on port $PORT." >&2
    echo "  The game must be running with DevBench loaded. If it is, check the bound port in" >&2
    echo "  Data/SKSE/Plugins/devbench/runtime.json or set DEVBENCH_PORT." >&2
}

# --- HTTP ------------------------------------------------------------------
# Status-aware, because DevBench's failure modes are NOT all "port dead":
#   504 = the main thread didn't run the task in time (busy load / stalled). The server is fine.
#   400 = bad arguments (since 1.11.0 arg-type errors are 400, not 500).
# Treating those as success -- or as a dead port -- sends you debugging the wrong thing.
json_string() {
    local value="$1"
    value=${value//\\/\\\\}
    value=${value//\"/\\\"}
    value=${value//$'\n'/\\n}
    value=${value//$'\r'/\\r}
    value=${value//$'\t'/\\t}
    printf '\"%s\"' "$value"
}

HTTP_STATUS=""
http() { # $1=METHOD  $2=path  $3=json body (POST only)  -> body on stdout
    local out rc body
    body="${3:-}"; [ -n "$body" ] || body='{}'
    if [ "$1" = "GET" ]; then
        out=$(curl -s -w $'\n%{http_code}' --max-time "$TIMEOUT" "$BASE$2" 2>/dev/null); rc=$?
    else
        out=$(curl -s -w $'\n%{http_code}' --max-time "$TIMEOUT" -X POST "$BASE$2" \
                  -H "Content-Type: application/json" -d "$body" 2>/dev/null); rc=$?
    fi
    if [ $rc -ne 0 ]; then HTTP_STATUS=""; dead_port; return 1; fi
    HTTP_STATUS="${out##*$'\n'}"
    printf '%s' "${out%$'\n'*}"
    case "$HTTP_STATUS" in
        2*) return 0 ;;
        504) echo "ERROR: 504 -- the game's MAIN THREAD did not run the task in time." >&2
             echo "  The server is alive; the game is busy (loading/shader compile) or hung." >&2
             echo "  Run 'devbench-cli.sh alive' -- it probes OFF the main thread and still answers." >&2
             return 3 ;;
        400) echo "ERROR: 400 -- DevBench rejected the arguments (bad type/shape)." >&2; return 4 ;;
        404) return 5 ;;
        *)   echo "ERROR: HTTP $HTTP_STATUS from DevBench." >&2; return 6 ;;
    esac
}
post() { http POST "/api/tool/$1" "${2:-}"; }

jget() { # $1 = jq-style path (.frame). Works without jq, best-effort: numbers, strings, bools.
    # `$1 // empty` would swallow a legitimate `false` (vr on an SE install) -- test null explicitly.
    if [ "$HAVE_JQ" -eq 1 ]; then jq -r "if $1 == null then empty else $1 end" 2>/dev/null; return; fi
    local k="${1##*.}"
    sed -n "s/.*\"$k\"[[:space:]]*:[[:space:]]*\"\{0,1\}\([^,\"}]*\)\"\{0,1\}.*/\1/p" | head -1
}

# Pre-1.11.0 DevBench has no /api/health. Fall back to the old (worse) main-thread frame diff:
# it cannot distinguish "hung" from "server down", because the probe itself blocks on the very
# thread that is hung -- which is exactly why /api/health exists. Upgrade if you land here.
legacy_alive() {
    echo "NOTE: this DevBench predates /api/health (1.11.0+). Falling back to the main-thread" >&2
    echo "  frame diff, which cannot tell a hang from a dead port. Consider updating DevBench." >&2
    local f1 f2
    f1=$(post inspect '{"kind":"state"}' | jget '.frame') || return 1
    sleep 1
    f2=$(post inspect '{"kind":"state"}' | jget '.frame') || return 1
    if [ -z "$f1" ] || [ -z "$f2" ]; then
        echo "UNKNOWN: could not read frame counter (is a save loaded?)"; return 1
    fi
    if [ "$f1" != "$f2" ]; then echo "RUNNING  (frame $f1 -> $f2)"; return 0; fi
    echo "NOT ADVANCING (frame stuck at $f1) -- game is paused (menu) or hung."
    return 2
}

CMD="${1:-}"; shift 2>/dev/null || true

case "$CMD" in
  ping)
      # Self-test of the HTTP layer only. It answers from a hung game -- use `alive` for liveness.
      post ping '{}' | pretty ;;

  health)
      http GET /api/health | pretty ;;

  alive)
      # HARD-WON: `ping` proves only that the HTTP thread is alive -- it runs on a SEPARATE thread
      # from the game, so a deadlocked game still answers it.
      #
      # DevBench 1.11.0+ answers `GET /api/health` OFF the main thread (no RunAndWait), so unlike
      # every tool call it keeps replying while the main thread is stuck -- which is precisely when
      # you need an answer. It returns liveness (frame, lastTaskFrame, pendingTasks) AND instance
      # identity (pid, port, exe, vr) in one shot, so a client pinned to the wrong port of two
      # running instances sees the misattach here rather than debugging phantom results for an hour.
      # NB: http() runs in a command substitution (a subshell), so HTTP_STATUS does NOT propagate
      # back here -- the RETURN CODE is the contract. 5 = 404 = this DevBench predates /api/health.
      h1=$(http GET /api/health); rc=$?
      [ $rc -eq 5 ] && { legacy_alive; exit $?; }
      [ $rc -eq 0 ] || exit 1
      sleep 1
      h2=$(http GET /api/health) || exit 1

      f1=$(printf '%s' "$h1" | jget '.frame')
      f2=$(printf '%s' "$h2" | jget '.frame')
      t1=$(printf '%s' "$h1" | jget '.lastTaskFrame')
      t2=$(printf '%s' "$h2" | jget '.lastTaskFrame')
      pend=$(printf '%s' "$h2" | jget '.pendingTasks')
      pid=$(printf '%s' "$h2" | jget '.pid')
      exe=$(printf '%s' "$h2" | jget '.exe')
      isvr=$(printf '%s' "$h2" | jget '.vr')
      echo "instance: pid=${pid:-?}  exe=${exe:-?}  vr=${isvr:-?}  port=$PORT"

      if [ -z "$f2" ]; then
          echo "UNKNOWN: /api/health answered but carried no frame counter."; exit 1
      fi
      # frame < 0 = the counter is unresolved: the server is up but the game is not in-game yet
      # (main menu / still loading). Nothing is wrong -- there is just nothing to drive yet.
      case "$f2" in -*)
          echo "NOT IN GAME (frame $f2) -- server is up, but no save is loaded yet."
          echo "  Menu/input tools may work here; load a save for world/Papyrus operations."
          exit 3 ;;
      esac

      if [ "$f1" != "$f2" ]; then
          echo "RUNNING  (frame $f1 -> $f2, pendingTasks ${pend:-0})"
          exit 0
      fi

      # Frozen frame alone is NOT proof of a hang -- paused, console open, and loading all freeze it.
      # The discriminator is the main-thread TASK QUEUE: work queued but lastTaskFrame not advancing
      # means tasks aren't completing, i.e. genuinely starved.
      if [ "${pend:-0}" -gt 0 ] 2>/dev/null && [ "$t1" = "$t2" ]; then
          echo "HUNG/STARVED (frame stuck at $f1; pendingTasks $pend, lastTaskFrame stuck at $t1)"
          echo "  Main-thread tasks are queued but not completing. Tool calls will 504."
          echo "  Check window focus and loading first; an unfocused game can stop servicing tasks."
          exit 2
      fi
      echo "NOT ADVANCING (frame stuck at $f1, pendingTasks ${pend:-0}) -- paused (menu/console open)"
      echo "  or mid-load. This is NOT proof of a hang; the task queue is draining normally."
      echo "  While paused, console 'exec' only QUEUES and Papyrus OnUpdate does not fire."
      echo "  Read tools (inspect) still work paused; write/act tools do not."
      exit 2 ;;

  state)
      post inspect '{"kind":"state"}' | pretty ;;

  inspect)
      kind="${1:-state}"
      post inspect "{\"kind\":$(json_string "$kind")}" | pretty ;;

  exec)
      # Current servers return the fenced capture in the exec response.
      [ $# -ge 1 ] || { echo "usage: devbench-cli.sh exec \"<console command>\"" >&2; exit 1; }
      cmd="$*"
      payload="{\"action\":\"exec\",\"command\":$(json_string "$cmd"),\"capture\":true}"
      result=$(post console "$payload"); rc=$?
      [ "$rc" -eq 0 ] || { printf '%s\n' "$result" | pretty; exit "$rc"; }
      completed=$(printf '%s' "$result" | jget '.completed')
      if [ -n "$completed" ]; then
          printf '%s\n' "$result" | pretty
          # Do not read a shared capture buffer after this request's capture timed out.
          [ "$completed" = true ] || exit 3
      else
          # Compatibility with older servers that only queued capture.
          sleep 1
          post console '{"action":"read"}' | pretty
      fi
      ;;

  call)
      # papyrus call: globals/native omit `self`; member functions pass it.
      [ $# -ge 2 ] || { echo "usage: devbench-cli.sh call <Script> <Function> [argsJson] [selfJson]" >&2; exit 1; }
      script="$1"; func="$2"; args="${3:-[]}"; slf="${4:-}"
      if [ -n "$slf" ]; then
          payload="{\"action\":\"call\",\"script\":$(json_string "$script"),\"function\":$(json_string "$func"),\"args\":$args,\"self\":$slf}"
      else
          payload="{\"action\":\"call\",\"script\":$(json_string "$script"),\"function\":$(json_string "$func"),\"args\":$args}"
      fi
      post papyrus "$payload" | pretty
      # NOTE: omitted TRAILING optional params are padded with neutral defaults (None/0/false/"").
      # For reference ops (MoveTo/Disable/Kill) a short arg list silently no-ops -- pass them explicitly.
      ;;

  describe)
      [ $# -ge 1 ] || { echo "usage: devbench-cli.sh describe <Script>" >&2; exit 1; }
      post papyrus "{\"action\":\"describe\",\"script\":$(json_string "$1")}" | pretty ;;

  notify)
      # HUD narration -- the user cannot see this chat while in the headset. Narrate live tests
      # in-game so the whole sequence is self-explaining.
      [ $# -ge 1 ] || { echo "usage: devbench-cli.sh notify \"text\"" >&2; exit 1; }
      payload="{\"action\":\"call\",\"script\":\"Debug\",\"function\":\"Notification\",\"args\":[$(json_string "$*")]}"
      post papyrus "$payload" | pretty ;;

  gfx|dialogue)
      # Forward JSON unchanged; the installed server validates its own schema.
      post "$CMD" "${1:-}" | pretty ;;

  tool)
      [ $# -ge 1 ] || { echo "usage: devbench-cli.sh tool <name> [json]" >&2; exit 1; }
      post "$1" "${2:-}" | pretty ;;

  tools)
      http GET /api/tools | pretty ;;

  port)
      echo "$PORT" ;;

  ""|-h|--help|help)
      sed -n '2,/^set -u/{ /^set -u/d; p; }' "$0" | sed 's/^# \{0,1\}//' ;;

  *)
      echo "Unknown command: $CMD" >&2
      echo "Try: ping | alive | health | state | inspect <kind> | exec | call | describe | notify | tool | gfx | dialogue | tools | port" >&2
      exit 1 ;;
esac

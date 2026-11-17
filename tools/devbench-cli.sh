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
#   bash tools/devbench-cli.sh wait [seconds] [--ingame]  # poll until the game answers (default 300 s); --ingame also waits for a loaded save
#   bash tools/devbench-cli.sh alive                      # is the GAME running / paused / hung?
#   bash tools/devbench-cli.sh wait [secs=300] [--ingame] # poll /api/health every 3 s until it answers
#                                                         #   (--ingame: also a loaded player); 0 ready, 3 timeout
#   bash tools/devbench-cli.sh health                     # raw off-thread liveness+identity probe
#   bash tools/devbench-cli.sh state                      # {plugin,version,vr,playerLoaded,frame,pid,port,exe}
#   bash tools/devbench-cli.sh fps [secs=5] [--gpu]       # fps from the health frame counter; warns if a mod menu
#                                                         #   is open (game idle behind it); --gpu: macOS GPU %
#   bash tools/devbench-cli.sh inspect vm                 # kinds: state health vm scene mods player
#                                                         #        inventory quests effects refs
#   bash tools/devbench-cli.sh inspect refs formType=Actor radius=800 --grep dragon
#                                                         # extra args: key=value or a JSON object, merged into the
#                                                         #   request; --grep = client-side case-insensitive filter
#                                                         #   over refs (formType name editorId model base); needs jq
#   bash tools/devbench-cli.sh exec "player.getav health" # console exec + capture + read output
#   bash tools/devbench-cli.sh exec "player.getav health" --lines   # only the captured lines, one per line
#   bash tools/devbench-cli.sh call Utility GetCurrentGameTime
#   bash tools/devbench-cli.sh call Actor IsInCombat '[]' '{"form":"0x14"}'
#   bash tools/devbench-cli.sh call ObjectReference SetAngle '[0,0,90]' '{"form":"0x14"}' --value
#                                                         # JSON numbers are coerced to the declared Float/Int
#                                                         #   (via describe; unchanged if describe fails); --value
#                                                         #   prints only `returned`, compact JSON
#                                                         # any {"form": ...} in args/self may be <Plugin>:<id>
#                                                         #   ("BSHeartland.esm:0012F7"): resolved from the load
#                                                         #   order, also for refs in unloaded cells
#   bash tools/devbench-cli.sh form BSHeartland.esm:0012F7               # print the runtime FormID
#   bash tools/devbench-cli.sh waitcall Actor HasSpell '[{"form":"0x313A9AF6"}]' '{"form":"0x14"}' --equals true
#                                                         # repeat the call until it returns --equals (compact
#                                                         #   JSON); --timeout 15 --every 1; 0 matched, 3 timeout
#   bash tools/devbench-cli.sh coc CYRBrumaChapel [--timeout 120]        # coc, then wait until the load is over
#                                                         #   and the player is in the cell; 4 = cell rejected
#   bash tools/devbench-cli.sh goto BSHeartland.esm:0012F7 [--dist 150] [--z 20] [--if-unloaded]
#                                                         # player BESIDE the ref, facing it (moveto onto a ref
#                                                         #   traps the player in its collision); 4 = not in memory
#   bash tools/devbench-cli.sh msgbox [--wait 5] [--answer Pray|0]       # read / answer the open message box
#                                                         #   by button label or index; 3 none, 4 no such button
#   bash tools/devbench-cli.sh logmark [--name X]         # record the size of Logs/Script/Papyrus.0.log
#   bash tools/devbench-cli.sh logdiff [--name X] [--errors] [--grep ERE] [--ref <0xID|Plugin:id>]
#                                                         # what the Papyrus log gained since the mark, as whole
#                                                         #   entries (line + stack); named marks never collide
#                                                         #   (DEVBENCH_PAPYRUS_LOG=<file> overrides the path)
#   bash tools/devbench-cli.sh quest 0x1607CADF           # IsRunning / IsCompleted / current stage of a quest, by FormID
#   bash tools/devbench-cli.sh tools                      # discover installed tools and schemas
#   bash tools/devbench-cli.sh gfx '{"op":"get","menu":"Dialogue Menu","path":"_root"}'
#   bash tools/devbench-cli.sh dialogue '{"action":"inspect"}'
#   bash tools/devbench-cli.sh tool menu '{"action":"accept"}'   # raw escape hatch: any tool, any JSON
#
# blockedBy: every reply lists open menus as `blockedBy`. Always-open HUD menus (BTPS Menu, BTPS Ovelay Menu,
# CastingBar_Center/Left/Right, SkyParkour, TrueHUD, oxygenMeter2, HUD Menu) are stripped from the printed
# JSON; any other blocker stays and is also named on stderr as one NOTE line. DEVBENCH_HUD_MENUS="A,B,C"
# replaces that list; DEVBENCH_RAW=1 or --raw (any command) prints replies untouched. Needs jq.
#
# Port: read from Data/SKSE/Plugins/devbench/runtime.json when present, else the per-runtime default
# (VR 8921, SE/AE 8920). Override with DEVBENCH_PORT=nnnn. Under Mod Organizer 2 the file lands in
# <overwrite>/SKSE/Plugins/devbench/runtime.json; the wrapper finds it through SKYRIM_MO2_OVERWRITE in
# skyrim-paths.env (override the env file with DEVBENCH_PATHS_ENV).
# Host: 127.0.0.1 unless DEVBENCH_HOST is set (a game in a VM or bottle with its own network address).

set -u
# Every command here pipes the HTTP helper into a formatter; without pipefail a dead server (-> 1)
# would be masked by the formatter's 0 and the caller would think the call succeeded.
set -o pipefail

# This script lives in <game root>/tools, so where you run it from cannot pick the wrong game (it used to pick port 8920).
GAME_DIR="${GAME_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
# Explicit path also supports a CrossOver bottle or MO2 overwrite directory.
RUNTIME_JSON="${DEVBENCH_RUNTIME_JSON:-$GAME_DIR/Data/SKSE/Plugins/devbench/runtime.json}"
TIMEOUT="${DEVBENCH_TIMEOUT:-15}"

command -v curl >/dev/null 2>&1 || { echo "ERROR: curl not found." >&2; exit 1; }
HAVE_JQ=0; command -v jq >/dev/null 2>&1 && HAVE_JQ=1

# --- Resolve the port -------------------------------------------------------
PATHS_ENV="${DEVBENCH_PATHS_ENV:-$GAME_DIR/skyrim-paths.env}"
paths_env_value() { # $1 = KEY from skyrim-paths.env (written by setup.sh); prints the unquoted value, or nothing
    [ -f "$PATHS_ENV" ] || return 0
    sed -n "s/^$1=//p" "$PATHS_ENV" | head -1 | sed "s/^['\"]//; s/['\"]\$//"
}

resolve_port() {
    if [ -n "${DEVBENCH_PORT:-}" ]; then echo "$DEVBENCH_PORT"; return; fi
    # DevBench writes the port it actually bound here (it iterates if the default was taken).
    if [ -f "$RUNTIME_JSON" ]; then
        p=$(sed -n 's/.*"port"[[:space:]]*:[[:space:]]*\([0-9][0-9]*\).*/\1/p' "$RUNTIME_JSON" | head -1)
        if [ "${p:-0}" -ge 1 ] 2>/dev/null && [ "${p:-0}" -le 65535 ] 2>/dev/null; then
            echo "$p"; return
        fi
    fi
    # Mod Organizer 2: files a plugin writes during a session land in overwrite/, not in Data/.
    if [ -z "${DEVBENCH_RUNTIME_JSON:-}" ]; then
        local ow
        ow="$(paths_env_value SKYRIM_MO2_OVERWRITE)"
        if [ -n "$ow" ] && [ -f "$ow/SKSE/Plugins/devbench/runtime.json" ]; then
            RUNTIME_JSON="$ow/SKSE/Plugins/devbench/runtime.json"
            DEVBENCH_RUNTIME_JSON="$RUNTIME_JSON"
            resolve_port; return
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
HOST="${DEVBENCH_HOST:-127.0.0.1}"
BASE="http://$HOST:$PORT"

# --- Output shaping ---------------------------------------------------------
# Every reply carries `blockedBy` ([{name,hint}]) for open menus, and the always-open HUD menus make it
# permanent noise. They are stripped from printed JSON; a non-HUD blocker stays and is named on stderr.
# DEVBENCH_HUD_MENUS (comma list) replaces the list; DEVBENCH_RAW=1 or --raw prints replies untouched.
HUD_DEFAULT='BTPS Menu,BTPS Ovelay Menu,CastingBar_Center,CastingBar_Left,CastingBar_Right,SkyParkour,TrueHUD,oxygenMeter2,HUD Menu'
RAW=0; [ "${DEVBENCH_RAW:-}" = 1 ] && RAW=1
hud_names() { printf '%s' "${DEVBENCH_HUD_MENUS-$HUD_DEFAULT}"; }
JQ_NM='def nm: if type=="string" then . elif type=="object" then (.name // .menu // .id // "") else tostring end;'
JQ_HUD='($hud|ascii_downcase|split(",")|map(gsub("^\\s+|\\s+$";""))|map(select(length>0))) as $h'
JQ_STRIP="$JQ_NM $JQ_HUD"'
  | if type=="object" and (.blockedBy|type)=="array"
    then .blockedBy |= map(select((nm|ascii_downcase) as $n | any($h[]; . == $n) | not))
         | if (.blockedBy|length)==0 then del(.blockedBy) else . end
    else . end'

hud_strip() { # $1 = JSON text -> filtered JSON on stdout; a remaining (non-HUD) blocker is named on stderr
    local f note
    if [ "$RAW" = 1 ] || [ "$HAVE_JQ" -ne 1 ]; then printf '%s' "$1"; return 0; fi
    if f=$(printf '%s' "$1" | jq -c --arg hud "$(hud_names)" "$JQ_STRIP" 2>/dev/null) && [ -n "$f" ]; then
        note=$(printf '%s' "$f" | jq -r "$JQ_NM"' (.blockedBy? // []) | if type=="array" then map(nm) | join(", ") else "" end' 2>/dev/null)
        if [ -n "$note" ]; then echo "NOTE: blocked by non-HUD menu: $note" >&2; fi
        printf '%s' "$f"
    else
        printf '%s' "$1"
    fi
}

pretty() {
    local in out
    in=$(cat)
    [ -n "$in" ] || return 0
    if [ "$HAVE_JQ" -eq 1 ]; then
        in=$(hud_strip "$in")
        if out=$(printf '%s' "$in" | jq . 2>/dev/null); then printf '%s\n' "$out"; return 0; fi
    fi
    printf '%s\n' "$in"
}

emit_lines() { # console reply -> only the captured lines, one per line
    local in
    in=$(cat)
    hud_strip "$in" >/dev/null   # surfaces a non-HUD blocker on stderr
    printf '%s' "$in" | jq -r '(.lines // []) | if type=="array" then .[] else . end | if type=="string" then . else tojson end' 2>/dev/null
}

emit_value() { # papyrus call reply -> only `returned`, compact JSON; anything without it (an error body) as-is
    local in
    in=$(cat)
    hud_strip "$in" >/dev/null
    printf '%s' "$in" | jq -c 'if type=="object" and has("returned") then .returned else . end' 2>/dev/null
}

need_jq() { [ "$HAVE_JQ" -eq 1 ] || { echo "ERROR: $1 needs jq (not found on PATH)." >&2; exit 1; }; }

now_ms() {
    local t
    t=$(perl -MTime::HiRes=time -e 'printf "%d", time()*1000' 2>/dev/null)
    if [ -n "$t" ]; then echo "$t"; else echo $(( $(date +%s) * 1000 )); fi
}

file_age_min() { # minutes since a file was last written; nothing if unknown
    local m now
    m=$(stat -f %m "$1" 2>/dev/null || stat -c %Y "$1" 2>/dev/null) || return 0
    now=$(date +%s); echo $(( (now - m) / 60 ))
}

dead_port() {
    echo "ERROR: no response from DevBench at $HOST:$PORT." >&2
    # Say WHY, so a closed game is told apart from a wrong port or host without guessing.
    local src log age
    if [ -n "${DEVBENCH_PORT:-}" ]; then src="DEVBENCH_PORT"
    elif [ -n "${DEVBENCH_RUNTIME_JSON:-}" ] && [ -f "$DEVBENCH_RUNTIME_JSON" ]; then src="$DEVBENCH_RUNTIME_JSON"
    elif [ -f "$RUNTIME_JSON" ]; then src="$RUNTIME_JSON"
    elif [ -f "$(paths_env_value SKYRIM_MO2_OVERWRITE)/SKSE/Plugins/devbench/runtime.json" ]; then
        src="$(paths_env_value SKYRIM_MO2_OVERWRITE)/SKSE/Plugins/devbench/runtime.json"
    else src="per-runtime default (no runtime.json found)"; fi
    echo "  port $PORT came from: $src" >&2
    if command -v pgrep >/dev/null 2>&1; then
        if pgrep -f 'SkyrimSE|SkyrimVR|SkyrimSELauncher|skse64_loader' >/dev/null 2>&1; then
            echo "  a Skyrim process IS running on this machine: check the port above, or DEVBENCH_HOST" >&2
        else
            echo "  no Skyrim process on this machine (a game in a VM or on another machine needs DEVBENCH_HOST)" >&2
        fi
    fi
    log="${DEVBENCH_SKSE_LOG:-}"
    if [ -z "$log" ]; then
        local docs; docs="$(paths_env_value SKYRIM_DOCUMENTS_DIR)"
        [ -n "$docs" ] && for f in "$docs/SKSE/skse64.log" "$docs/SKSE/sksevr.log"; do
            [ -f "$f" ] && { log="$f"; break; }
        done
    fi
    if [ -n "$log" ] && [ -f "$log" ]; then
        age="$(file_age_min "$log")"
        if grep -qi 'devbench.*loaded correctly' "$log" 2>/dev/null; then
            echo "  SKSE log ($log): DevBench loaded; log last written ${age:-?} min ago" >&2
        else
            echo "  SKSE log ($log): no 'DevBench loaded correctly' line; the plugin did not load" >&2
        fi
    fi
    echo "  The game must be RUNNING (a save loaded for world/Papyrus work). 'devbench-cli.sh wait'" >&2
    echo "  polls until it answers; VR can run headless through tools/vr-headless.sh." >&2
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

http_error_text() { # the server's own `error` text, plainly, on stderr
    local e
    e=$(printf '%s' "$1" | jget '.error')
    [ -n "$e" ] && echo "  server: $e" >&2
    return 0
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
        400) echo "ERROR: 400 -- DevBench rejected the arguments (bad type/shape)." >&2
             http_error_text "${out%$'\n'*}"; return 4 ;;
        404) return 5 ;;
        *)   echo "ERROR: HTTP $HTTP_STATUS from DevBench." >&2
             http_error_text "${out%$'\n'*}"; return 6 ;;
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

while [ "${1:-}" = "--raw" ]; do RAW=1; shift; done   # --raw is global: accepted before the command too
CMD="${1:-}"; shift 2>/dev/null || true

# --- wait / fps helpers -----------------------------------------------------
PH_CODE=""; PH_BODY=""
probe_health() { # off-thread /api/health, no error chatter -> PH_CODE (empty = no answer), PH_BODY
    local out
    out=$(curl -s -w $'\n%{http_code}' --max-time 3 "$BASE/api/health" 2>/dev/null); local rc=$?
    if [ $rc -ne 0 ]; then PH_CODE=""; PH_BODY=""; return 1; fi
    PH_CODE="${out##*$'\n'}"; PH_BODY="${out%$'\n'*}"
}
probe_state() { # main-thread inspect state, short timeout, silent -> body (empty when unavailable)
    curl -s --max-time 5 -X POST "$BASE/api/tool/inspect" -H "Content-Type: application/json" \
         -d '{"kind":"state"}' 2>/dev/null
}

nonhud_menus() { # open menus that are not always-open HUD menus, one per line (needs jq)
    local m
    m=$(post menu '{"action":"list"}' 2>/dev/null) || return 1
    printf '%s' "$m" | jq -r --arg hud "$(hud_names)" "$JQ_HUD"'
        | (.openMenus // [])[] | . as $n
        | select(($n|ascii_downcase) as $l | any($h[]; . == $l) | not)' 2>/dev/null
}

# --- call argument coercion -------------------------------------------------
# Papyrus `call` answers 400 "bad type/shape" for an int where the function declares a Float (SetAngle, MoveTo).
# Ask describe for the declared parameter types and rewrite JSON numbers to match. Any failure -> args unchanged.
coerce_args() { # $1 script  $2 function  $3 args JSON  $4 self JSON (may be empty) -> args JSON on stdout
    local script="$1" func="$2" args="$3" slf="${4:-}" need cur="$1" depth=0 d types res count
    [ "$HAVE_JQ" -eq 1 ] || { printf '%s' "$args"; return 0; }
    need=$(printf '%s' "$args" | jq -r 'if type=="array" and any(.[]; type=="number") then "y" else "n" end' 2>/dev/null)
    [ "$need" = y ] || { printf '%s' "$args"; return 0; }
    types=""
    while [ "$depth" -lt 6 ] && [ -n "$cur" ]; do
        d=$(post papyrus "{\"action\":\"describe\",\"script\":$(json_string "$cur")}" 2>/dev/null) || break
        types=$(printf '%s' "$d" | jq -r --arg f "$func" --arg m "$([ -n "$slf" ] && echo 1 || echo 0)" '
            (if $m == "1" then (.memberFunctions // []) + (.globalFunctions // [])
                          else (.globalFunctions // []) + (.memberFunctions // []) end)
            | map(select((.name // "" | ascii_downcase) == ($f | ascii_downcase))) | first
            | if . == null then empty else "T:" + ((.params // []) | map(.type // "" | ascii_downcase) | join(",")) end' 2>/dev/null)
        [ -n "$types" ] && break
        cur=$(printf '%s' "$d" | jq -r '.parent // empty' 2>/dev/null)
        depth=$((depth + 1))
    done
    [ -n "$types" ] || { printf '%s' "$args"; return 0; }
    res=$(printf '%s' "$args" | jq -r --arg t "${types#T:}" '
        ($t | split(",")) as $ty
        | to_entries
        | map(.key as $i | .value as $v | ($ty[$i] // "") as $p
              | if ($v|type) == "number" and $p == "float" then
                    ($v|tostring) as $s | if ($s|test("[.eE]")) then {t:$s, c:0} else {t:($s + ".0"), c:1} end
                elif ($v|type) == "number" and $p == "int" and ($v|floor) == $v and (($v|tostring)|test("[.eE]")) then
                    {t:($v|floor|tostring), c:1}
                else {t:($v|tojson), c:0} end)
        | (map(.c) | add // 0 | tostring), ("[" + (map(.t) | join(",")) + "]")' 2>/dev/null) || { printf '%s' "$args"; return 0; }
    count=$(printf '%s\n' "$res" | sed -n 1p)
    if [ "${count:-0}" -gt 0 ] 2>/dev/null; then
        echo "NOTE: coerced $count call argument(s) to the declared Papyrus types (${types#T:})" >&2
        printf '%s\n' "$res" | sed -n 2p | tr -d '\n'
    else
        printf '%s' "$args"
    fi
}

# --- Papyrus log mark/diff --------------------------------------------------
DIAG_DIR="${DEVBENCH_DIAG_DIR:-$GAME_DIR/.claude/diag/devbench}"
PAPYRUS_MARK="$DIAG_DIR/papyrus-mark"
papyrus_log_path() { # DEVBENCH_PAPYRUS_LOG, else the way tools/papyrus-triage.py finds it (skyrim_paths)
    local py dir
    if [ -n "${DEVBENCH_PAPYRUS_LOG:-}" ]; then printf '%s' "$DEVBENCH_PAPYRUS_LOG"; return 0; fi
    if [ -n "${PAPYRUS_LOG_DIR:-}" ]; then
        dir="$PAPYRUS_LOG_DIR"
    else
        py=""
        for c in python3 python; do command -v "$c" >/dev/null 2>&1 && { py="$c"; break; }; done
        [ -n "$py" ] || { echo "ERROR: python not found; set DEVBENCH_PAPYRUS_LOG=<Papyrus.0.log>." >&2; return 1; }
        dir=$("$py" -I -c 'import sys; sys.path.insert(0, sys.argv[1]); import skyrim_paths; print(skyrim_paths.resolve_dir("PAPYRUS_LOG_DIR", "Logs/Script")[0])' "$GAME_DIR/tools") \
            || { echo "ERROR: could not resolve the Papyrus log folder; set DEVBENCH_PAPYRUS_LOG=<Papyrus.0.log>." >&2; return 1; }
    fi
    printf '%s/Papyrus.0.log' "$dir"
}
file_size() { wc -c < "$1" | tr -d ' '; }
file_head_sum() { # $1 file  $2 byte count -> checksum of the first $2 bytes (the mark stores the count, so a log that was
    head -c "$2" "$1" | cksum | cut -d' ' -f1   # short when marked can still be compared after it grows)
}
mark_field() { sed -n "s/^$1=//p" "$PAPYRUS_MARK" | head -1; }

# --- Plugin-relative forms ----------------------------------------------------
# "BSHeartland.esm:0012F7" or "0012F7:BSHeartland.esm" -> the runtime FormID, from `inspect mods`: a full plugin
# gives (index << 24) | low 24 bits, a light plugin 0xFE000000 | (light index << 12) | low 12 bits. Works for a
# temporary reference in an unloaded cell, where Game.GetFormFromFile returns None.
MODS_JSON=""
JQ_FORMS='
def spec: first((capture("^(?<id>(0[xX])?[0-9A-Fa-f]{1,8}):(?<p>.+\\.(esm|esp|esl|ESM|ESP|ESL))$"),
                 capture("^(?<p>.+\\.(esm|esp|esl|ESM|ESP|ESL)):(?<id>(0[xX])?[0-9A-Fa-f]{1,8})$")));
def isspec: type == "string" and ([spec] | length) > 0;
def hex2n: ascii_downcase | ltrimstr("0x") | explode
           | reduce .[] as $c (0; . * 16 + (if $c >= 97 then $c - 87 else $c - 48 end));
def hex8: . as $n | [range(7; -1; -1) as $i | (($n / pow(16; $i)) | floor) % 16]
          | map("0123456789ABCDEF"[.:. + 1]) | "0x" + join("");
def res($m): spec as $s | ($s.p | ascii_downcase) as $p | ($s.id | hex2n) as $low
    | ([($m.plugins // [])[] | select((.name | ascii_downcase) == $p)] | first) as $full
    | ([($m.lightPlugins // [])[] | select((.name | ascii_downcase) == $p)] | first) as $light
    | if $full != null then ($full.index * 16777216 + ($low % 16777216)) | hex8
      elif $light != null then (4261412864 + $light.index * 4096 + ($low % 4096)) | hex8
      else error("plugin not loaded: " + $s.p) end;
def resolve_forms($m): walk(if type == "object" then
        with_entries(if (.key == "form" or .key == "formId") and (.value | isspec) then .value |= res($m) else . end)
      else . end);'

load_mods() { # fills MODS_JSON once per run
    [ -n "$MODS_JSON" ] && return 0
    MODS_JSON=$(post inspect '{"kind":"mods"}') || {
        echo "ERROR: could not read the load order (inspect mods) to resolve a plugin-relative form." >&2; return 1; }
}

resolve_json() { # $1 = JSON text; every {"form"|"formId": "<Plugin>:<id>"} becomes the runtime FormID
    local in="$1" out
    case "$in" in *.[eE][sS][mMpPlL]*) ;; *) printf '%s' "$in"; return 0 ;; esac
    need_jq "a plugin-relative form"
    load_mods || return 1
    out=$(printf '%s' "$in" | jq -c --argjson m "$MODS_JSON" "$JQ_FORMS"' resolve_forms($m)' 2>&1) || {
        echo "ERROR: ${out#jq: error (at <stdin>:*): }" >&2; return 1; }
    printf '%s' "$out"
}

resolve_form() { # $1 = 0xFORMID | <Plugin>:<id> | <id>:<Plugin> -> 0xFORMID on stdout
    local r
    case "$1" in 0x*|0X*) printf '%s' "$1"; return 0 ;; esac
    r=$(resolve_json "{\"form\":$(json_string "$1")}") || return 1
    r=$(printf '%s' "$r" | jq -r '.form')
    case "$r" in 0x*) printf '%s' "$r" ;; *) echo "ERROR: not a FormID or <Plugin>:<id>: $1" >&2; return 1 ;; esac
}

pcall() { # $1 script $2 function $3 args JSON $4 self JSON (may be empty) -> compact `returned` on stdout; http() rc
    local payload body rc
    payload="{\"action\":\"call\",\"script\":$(json_string "$1"),\"function\":$(json_string "$2"),\"args\":$3"
    [ -n "${4:-}" ] && payload="$payload,\"self\":$4"
    body=$(post papyrus "$payload}"); rc=$?
    [ "$rc" -eq 0 ] || return "$rc"
    printf '%s' "$body" | jq -c '.returned'
}

player_cell() { # editorId (or formId) of the player's cell; empty while the main thread cannot answer
    curl -s --max-time 5 -X POST "$BASE/api/tool/inspect" -H "Content-Type: application/json" -d '{"kind":"scene"}' 2>/dev/null \
        | jq -r '.cell | if . == null then empty else (.editorId // .formId // empty) end' 2>/dev/null
}

# Papyrus log entries: a timestamped line plus its indented continuation (stack) lines. Keeps whole entries that
# pass every filter given: errors (error|warning in the entry's first line), grep (case-insensitive ERE anywhere in
# the entry), ref (the 8-digit FormID anywhere in the entry, as Papyrus prints it: "(3B015490)").
filter_entries() { # $1 errors 0|1  $2 grep ERE  $3 ref hex (8 digits, upper case)  < log text
    awk -v errs="$1" -v g="$(printf '%s' "$2" | tr '[:upper:]' '[:lower:]')" -v ref="$3" '
        function flush() {
            if (buf == "") return
            ok = 1
            if (errs == 1 && tolower(head) !~ /error|warning/) ok = 0
            if (ok && g != "" && tolower(buf) !~ g) ok = 0
            if (ok && ref != "" && toupper(buf) !~ ref) ok = 0
            if (ok) printf "%s", buf
            buf = ""
        }
        /^\[[0-9][0-9]\/[0-9][0-9]\/[0-9][0-9][0-9][0-9] - / { flush(); head = $0 }
        { buf = buf $0 "\n" }
        END { flush() }'
}

# --- Flags (stripped only for the command they belong to, so a console command or JSON that happens to
# contain one is never altered) ----------------------------------------------------------------------------
F_LINES=0; F_VALUE=0; F_GPU=0; F_INGAME=0; F_ERRORS=0; GREP=""; HAVE_GREP=0
MARK_NAME=""; F_REF=""; F_EQUALS=""; HAVE_EQUALS=0; F_TIMEOUT=""; F_EVERY=1; F_WAIT=0; F_ANSWER=""; HAVE_ANSWER=0
F_DIST=150; F_Z=20; F_IFUNLOADED=0
_flagval() { [ $# -ge 2 ] || { echo "ERROR: $CMD $1 needs a value." >&2; exit 1; }; }
_num() { case "$2" in ''|*[!0-9.-]*) echo "ERROR: $CMD $1 needs a number, got '$2'." >&2; exit 1 ;; esac; }
_args=()
while [ $# -gt 0 ]; do
    case "$1" in
        --raw) RAW=1 ;;
        --lines)  if [ "$CMD" = exec ];    then F_LINES=1;  else _args+=("$1"); fi ;;
        --value)  if [ "$CMD" = call ];    then F_VALUE=1;  else _args+=("$1"); fi ;;
        --gpu)    if [ "$CMD" = fps ];     then F_GPU=1;    else _args+=("$1"); fi ;;
        --ingame) if [ "$CMD" = wait ];    then F_INGAME=1; else _args+=("$1"); fi ;;
        --errors) if [ "$CMD" = logdiff ]; then F_ERRORS=1; else _args+=("$1"); fi ;;
        --grep)   if [ "$CMD" = inspect ] || [ "$CMD" = logdiff ]; then
                      [ $# -ge 2 ] || { echo "usage: devbench-cli.sh $CMD ... --grep <text>" >&2; exit 1; }
                      shift; GREP="$1"; HAVE_GREP=1
                  else _args+=("$1"); fi ;;
        --name)   if [ "$CMD" = logmark ] || [ "$CMD" = logdiff ]; then _flagval "$@"; shift; MARK_NAME="$1"
                  else _args+=("$1"); fi ;;
        --ref)    if [ "$CMD" = logdiff ]; then _flagval "$@"; shift; F_REF="$1"; else _args+=("$1"); fi ;;
        --equals) if [ "$CMD" = waitcall ]; then _flagval "$@"; shift; F_EQUALS="$1"; HAVE_EQUALS=1
                  else _args+=("$1"); fi ;;
        --timeout) if [ "$CMD" = waitcall ] || [ "$CMD" = coc ] || [ "$CMD" = goto ]; then
                      _flagval "$@"; _num "$1" "$2"; shift; F_TIMEOUT="$1"; else _args+=("$1"); fi ;;
        --every)  if [ "$CMD" = waitcall ]; then _flagval "$@"; _num "$1" "$2"; shift; F_EVERY="$1"; else _args+=("$1"); fi ;;
        --wait)   if [ "$CMD" = msgbox ]; then _flagval "$@"; _num "$1" "$2"; shift; F_WAIT="$1"; else _args+=("$1"); fi ;;
        --answer) if [ "$CMD" = msgbox ]; then _flagval "$@"; shift; F_ANSWER="$1"; HAVE_ANSWER=1; else _args+=("$1"); fi ;;
        --dist)   if [ "$CMD" = goto ]; then _flagval "$@"; _num "$1" "$2"; shift; F_DIST="$1"; else _args+=("$1"); fi ;;
        --z)      if [ "$CMD" = goto ]; then _flagval "$@"; _num "$1" "$2"; shift; F_Z="$1"; else _args+=("$1"); fi ;;
        --if-unloaded) if [ "$CMD" = goto ]; then F_IFUNLOADED=1; else _args+=("$1"); fi ;;
        *) _args+=("$1") ;;
    esac
    shift
done
if [ ${#_args[@]} -gt 0 ]; then set -- "${_args[@]}"; else set --; fi

# Named log marks: `logmark --name X` / `logdiff --name X`, so two testers (or an agent and a listener) never
# overwrite each other's mark. The unnamed mark keeps its old file.
if [ -n "$MARK_NAME" ]; then
    case "$MARK_NAME" in *[!A-Za-z0-9_.-]*|.*) echo "ERROR: mark name may use letters, digits, '_', '-', '.': $MARK_NAME" >&2; exit 1 ;; esac
    PAPYRUS_MARK="$DIAG_DIR/papyrus-mark.$MARK_NAME"
fi


case "$CMD" in
  ping)
      # Self-test of the HTTP layer only. It answers from a hung game -- use `alive` for liveness.
      post ping '{}' | pretty ;;

  health)
      http GET /api/health | pretty ;;

  wait)
      # Poll /api/health (answered off the main thread) until the server replies, so a session can
      # start the moment the user launches the game instead of guessing. Quiet while waiting.
      secs=300; ingame=0
      for a in "$@"; do
          case "$a" in
              --ingame) ingame=1 ;;
              ''|*[!0-9]*) echo "usage: devbench-cli.sh wait [seconds] [--ingame]" >&2; exit 1 ;;
              *) secs="$a" ;;
          esac
      done
      start=$(date +%s)
      while :; do
          h=$(curl -s --max-time 5 -w $'\n%{http_code}' "$BASE/api/health" 2>/dev/null) || h=""
          code="${h##*$'\n'}"
          case "$code" in
              2*)
                  body="${h%$'\n'*}"
                  f=$(printf '%s' "$body" | jget '.frame')
                  now=$(date +%s)
                  if [ "$ingame" -eq 1 ]; then
                      case "${f:--1}" in -*) f="" ;; esac
                  fi
                  if [ "$ingame" -eq 0 ] || [ -n "$f" ]; then
                      echo "READY after $(( now - start )) s at $HOST:$PORT (frame ${f:-unresolved: no save loaded yet})"
                      exit 0
                  fi ;;
          esac
          if [ $(( $(date +%s) - start )) -ge "$secs" ]; then
              if [ "$ingame" -eq 1 ]; then w=" (in game)"; else w=""; fi
              echo "TIMEOUT after ${secs} s waiting for DevBench${w}." >&2
              dead_port
              exit 1
          fi
          sleep 3
      done ;;

  quest)
      # IsRunning / IsCompleted / current stage of one quest. Quests are forms: pass the FormID
      # (load-order prefixed, as `sqv` and the CK show it); editor IDs are not resolved here.
      [ $# -eq 1 ] || { echo "usage: devbench-cli.sh quest <FormID, e.g. 0x1607CADF>" >&2; exit 1; }
      qid="${1#0x}"; qid="${qid#0X}"
      case "$qid" in ''|*[!0-9A-Fa-f]*) echo "ERROR: '$1' is not a hex FormID." >&2; exit 1 ;; esac
      for fn in IsRunning IsCompleted GetCurrentStageID; do
          printf '%s: ' "$fn"
          post papyrus "{\"action\":\"call\",\"script\":\"Quest\",\"function\":\"$fn\",\"args\":[],\"self\":{\"form\":\"0x$qid\"}}" | pretty || exit $?
      done ;;

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

  wait)
      # Poll the OFF-THREAD health probe until DevBench answers; --ingame also needs a loaded player.
      # 0 = ready, 3 = timeout (could not check). One status line, no JSON.
      secs=300
      for a in "$@"; do
          case "$a" in
              ''|*[!0-9]*) echo "usage: devbench-cli.sh wait [seconds=300] [--ingame]" >&2; exit 1 ;;
              *) secs="$a" ;;
          esac
      done
      start=$(date +%s); last="no response on port $PORT"
      while :; do
          ready=0
          if probe_health && [ -n "$PH_CODE" ]; then
              case "$PH_CODE" in
                  2*)
                      f=$(printf '%s' "$PH_BODY" | jget '.frame')
                      if [ "$F_INGAME" -eq 0 ]; then ready=1
                      elif [ -z "$f" ]; then last="server up, health carried no frame counter"
                      else
                          case "$f" in
                              -*) last="server up, not in game (frame $f)" ;;
                              *)  pl=$(probe_state | jget '.playerLoaded')
                                  if [ "$pl" = false ]; then
                                      case "$PH_BODY" in
                                          *'"Main Menu"'*) last="at the Main Menu: no save loaded yet" ;;
                                          *'"Loading Menu"'*) last="loading a save" ;;
                                          *) last="frame $f, player not loaded yet" ;;
                                      esac
                                  else ready=1; fi ;;
                          esac
                      fi ;;
                  404)  # pre-1.11.0: no /api/health; the main-thread state is the only evidence
                      if [ "$F_INGAME" -eq 0 ]; then ready=1
                      else
                          st=$(probe_state); pl=$(printf '%s' "$st" | jget '.playerLoaded')
                          if [ "$pl" = true ]; then ready=1; else last="legacy DevBench: player not loaded (playerLoaded=${pl:-unknown})"; fi
                      fi ;;
                  *) last="HTTP $PH_CODE from /api/health" ;;
              esac
          fi
          elapsed=$(( $(date +%s) - start ))
          if [ "$ready" -eq 1 ]; then
              what="answering"; [ "$F_INGAME" -eq 1 ] && what="in game"
              pid=$(printf '%s' "$PH_BODY" | jget '.pid')
              echo "READY: DevBench $what on port $PORT (pid ${pid:-?}, frame ${f:-?}) after ${elapsed}s"
              exit 0
          fi
          if [ "$elapsed" -ge "$secs" ]; then
              echo "TIMEOUT: DevBench not ready after ${elapsed}s (limit ${secs}s): $last"
              exit 3
          fi
          # One progress line every 15 s on stderr, so a long wait never looks hung.
          if [ "$elapsed" -ge "${next_note:-15}" ]; then
              echo "waiting ${elapsed}s of ${secs}s: $last" >&2
              next_note=$(( elapsed + 15 ))
          fi
          left=$(( secs - elapsed )); nap=3; [ "$left" -lt "$nap" ] && nap="$left"
          sleep "$nap"
      done ;;

  fps)
      # fps = delta of the off-thread health frame counter over a window. A menu open in front of the game
      # (Community Shaders' menu, a mod menu) can leave it idle, and the reading then says nothing about gameplay.
      secs=5
      for a in "$@"; do
          case "$a" in
              ''|*[!0-9]*) echo "usage: devbench-cli.sh fps [seconds=5] [--gpu]" >&2; exit 1 ;;
              *) secs="$a" ;;
          esac
      done
      [ "$secs" -ge 1 ] || secs=1
      menus=""
      if [ "$HAVE_JQ" -eq 1 ]; then
          menus=$(nonhud_menus | tr '\n' ',' | sed 's/,$//; s/,/, /g')
      else
          echo "NOTE: jq not found; open menus were not checked." >&2
      fi
      h1=$(http GET /api/health) || exit 1
      f1=$(printf '%s' "$h1" | jget '.frame'); t1=$(now_ms)
      case "${f1:-x}" in x|-*) echo "NOT IN GAME (frame ${f1:-unknown}) -- no frame counter to sample."; exit 3 ;; esac
      sleep "$secs"
      h2=$(http GET /api/health) || exit 1
      f2=$(printf '%s' "$h2" | jget '.frame'); t2=$(now_ms)
      case "${f2:-x}" in x|-*) echo "NOT IN GAME (frame ${f2:-unknown}) at the end of the window."; exit 3 ;; esac
      ms=$(( t2 - t1 )); [ "$ms" -gt 0 ] || ms=$(( secs * 1000 ))
      fpsv=$(awk -v a="$f1" -v b="$f2" -v ms="$ms" 'BEGIN { printf "%.1f", (b - a) * 1000 / ms }')
      echo "fps: $fpsv  (frames $f1 -> $f2 over $(awk -v ms="$ms" 'BEGIN { printf "%.2f", ms / 1000 }') s)"
      if [ -n "$menus" ]; then
          echo "WARNING: non-HUD menu open ($menus). The game may be idle behind it and this reading is not valid; close it and measure again."
      fi
      if [ "$f1" = "$f2" ]; then
          echo "WARNING: the frame counter did not advance; the game is paused, loading or hung (run 'alive'). Not a frame rate."
      fi
      if [ "$F_GPU" -eq 1 ] && [ "$(uname -s 2>/dev/null)" = Darwin ] && command -v ioreg >/dev/null 2>&1; then
          gpu=$(ioreg -r -d 1 -c IOAccelerator 2>/dev/null | sed -n 's/.*"Device Utilization %"[[:space:]]*=[[:space:]]*\([0-9][0-9]*\).*/\1/p' | head -1)
          [ -n "$gpu" ] && echo "gpu: Device Utilization ${gpu}%"
      fi
      exit 0 ;;

  state)
      post inspect '{"kind":"state"}' | pretty ;;

  inspect)
      # inspect <kind> [key=value | {json object}]...  Extra args are merged into the request (formType=Actor,
      # radius=800, filter=..., limit=...). --grep <text> then filters `refs` client-side, case-insensitively.
      kind="${1:-state}"; [ $# -gt 0 ] && shift
      payload="{\"kind\":$(json_string "$kind")"
      for a in "$@"; do
          case "$a" in
              \{*) inner="${a#\{}"; inner="${inner%\}}"
                   [ -n "${inner//[[:space:]]/}" ] && payload="$payload,$inner" ;;
              ?*=*) k="${a%%=*}"; v="${a#*=}"
                   if [ "$v" = true ] || [ "$v" = false ] || [ "$v" = null ] || [[ "$v" =~ ^-?(0|[1-9][0-9]*)(\.[0-9]+)?$ ]]; then tok="$v"
                   else tok="$(json_string "$v")"; fi
                   payload="$payload,$(json_string "$k"):$tok" ;;
              *) echo "usage: devbench-cli.sh inspect <kind> [key=value | {json}]... [--grep <text>]" >&2; exit 1 ;;
          esac
      done
      payload="$payload}"
      [ "$HAVE_GREP" -eq 0 ] || need_jq "inspect --grep"
      result=$(post inspect "$payload"); rc=$?
      if [ "$HAVE_GREP" -eq 1 ] && [ "$rc" -eq 0 ]; then
          g=$(printf '%s' "$result" | jq -c --arg g "$GREP" '
              if type == "object" and (.refs | type) == "array" then
                  (.refs | length) as $of
                  | .refs |= map(select(
                        ([.formType, .name, .editorId, .model, .base]
                         | map(if . == null then "" elif type == "string" then . else tojson end)
                         | join("\n") | ascii_downcase) | contains($g | ascii_downcase)))
                  | .grep = {text: $g, matched: (.refs | length), of: $of}
              else . end' 2>/dev/null) && [ -n "$g" ] && result="$g"
      fi
      printf '%s\n' "$result" | pretty
      exit "$rc" ;;

  exec)
      # Current servers return the fenced capture in the exec response.
      [ $# -ge 1 ] || { echo "usage: devbench-cli.sh exec \"<console command>\"" >&2; exit 1; }
      cmd="$*"
      payload="{\"action\":\"exec\",\"command\":$(json_string "$cmd"),\"capture\":true}"
      result=$(post console "$payload"); rc=$?
      [ "$rc" -eq 0 ] || { printf '%s\n' "$result" | pretty; exit "$rc"; }
      [ "$F_LINES" -eq 0 ] || need_jq "exec --lines"
      completed=$(printf '%s' "$result" | jget '.completed')
      if [ -n "$completed" ]; then
          if [ "$F_LINES" -eq 1 ]; then printf '%s\n' "$result" | emit_lines; else printf '%s\n' "$result" | pretty; fi
          # Do not read a shared capture buffer after this request's capture timed out.
          [ "$completed" = true ] || exit 3
      else
          # Compatibility with older servers that only queued capture.
          sleep 1
          if [ "$F_LINES" -eq 1 ]; then post console '{"action":"read"}' | emit_lines; else post console '{"action":"read"}' | pretty; fi
      fi
      ;;

  call)
      # papyrus call: globals/native omit `self`; member functions pass it.
      [ $# -ge 2 ] || { echo "usage: devbench-cli.sh call <Script> <Function> [argsJson] [selfJson]" >&2; exit 1; }
      script="$1"; func="$2"; args="${3:-[]}"; slf="${4:-}"
      [ "$F_VALUE" -eq 0 ] || need_jq "call --value"
      args=$(resolve_json "$args") || exit 4
      if [ -n "$slf" ]; then slf=$(resolve_json "$slf") || exit 4; fi
      args=$(coerce_args "$script" "$func" "$args" "$slf")
      if [ -n "$slf" ]; then
          payload="{\"action\":\"call\",\"script\":$(json_string "$script"),\"function\":$(json_string "$func"),\"args\":$args,\"self\":$slf}"
      else
          payload="{\"action\":\"call\",\"script\":$(json_string "$script"),\"function\":$(json_string "$func"),\"args\":$args}"
      fi
      result=$(post papyrus "$payload"); rc=$?
      if [ "$F_VALUE" -eq 1 ]; then printf '%s\n' "$result" | emit_value; else printf '%s\n' "$result" | pretty; fi
      exit "$rc"
      # NOTE: DevBench <= 1.24 padded omitted TRAILING optional params with neutral defaults (None/0/false/""),
      # so a short arg list silently no-opped reference ops (MoveTo/Disable/Kill). Since 1.25 (#118) only known
      # vanilla/SKSE defaults are filled and any other omitted param is refused with 400 (nothing runs):
      # pass every param explicitly, or send fillNeutral:true through `tool papyrus '{...}'` for the old padding.
      ;;

  form)
      # Print the runtime FormID of <Plugin>:<id> (or <id>:<Plugin>), from the loaded load order.
      [ $# -ge 1 ] || { echo "usage: devbench-cli.sh form <Plugin.esp>:<id>" >&2; exit 1; }
      resolve_form "$1"; rc=$?; [ "$rc" -eq 0 ] && echo; exit "$rc" ;;

  waitcall)
      # Repeat a Papyrus call until it returns the --equals value (compared as compact JSON): for results a
      # script produces late, where a fixed sleep gives false failures. 0 matched, 3 timeout, else the call's error.
      [ $# -ge 2 ] && [ "$HAVE_EQUALS" -eq 1 ] || {
          echo "usage: devbench-cli.sh waitcall <Script> <Function> [argsJson] [selfJson] --equals <json> [--timeout 15] [--every 1]" >&2; exit 1; }
      need_jq waitcall
      want=$(printf '%s' "$F_EQUALS" | jq -c . 2>/dev/null) || { echo "ERROR: --equals is not JSON: $F_EQUALS (a string needs quotes: '\"text\"')" >&2; exit 1; }
      script="$1"; func="$2"; args="${3:-[]}"; slf="${4:-}"
      args=$(resolve_json "$args") || exit 4
      if [ -n "$slf" ]; then slf=$(resolve_json "$slf") || exit 4; fi
      args=$(coerce_args "$script" "$func" "$args" "$slf")
      limit="${F_TIMEOUT:-15}"; start=$(now_ms); got=""
      while :; do
          got=$(pcall "$script" "$func" "$args" "$slf"); rc=$?
          [ "$rc" -eq 0 ] || exit "$rc"
          el=$(( ($(now_ms) - start) / 1000 ))
          if [ "$got" = "$want" ]; then echo "MATCHED after ${el}s: $got"; exit 0; fi
          if awk -v e="$(( $(now_ms) - start ))" -v l="$limit" 'BEGIN { exit !(e >= l * 1000) }'; then
              echo "TIMEOUT after ${el}s: last value $got (wanted $want)"; exit 3
          fi
          sleep "$F_EVERY"
      done ;;

  msgbox)
      # Read the open message box; --wait N polls up to N s for one to open; --answer <label|index> clicks a button
      # (label: case-insensitive exact match). 0 done, 3 no box, 4 no such button.
      need_jq msgbox
      start=$(now_ms); box=""
      while :; do
          d=$(post menu '{"action":"describe"}' 2>/dev/null)
          if [ "$(printf '%s' "$d" | jq -r '.messageBoxOpen // false' 2>/dev/null)" = true ]; then box="$d"; break; fi
          awk -v e="$(( $(now_ms) - start ))" -v l="$F_WAIT" 'BEGIN { exit !(e >= l * 1000) }' && break
          sleep 0.5
      done
      [ -n "$box" ] || { echo "NO MESSAGE BOX (waited ${F_WAIT}s)"; exit 3; }
      printf '%s' "$box" | jq -c '{bodyText, buttons}'
      [ "$HAVE_ANSWER" -eq 1 ] || exit 0
      idx=$(printf '%s' "$box" | jq -r --arg a "$F_ANSWER" '
          (.buttons // []) as $b
          | if ($a | test("^[0-9]+$")) then (if ($a | tonumber) < ($b | length) then $a else empty end)
            else ([range(0; $b | length) | select(($b[.] | ascii_downcase) == ($a | ascii_downcase))] | first // empty | tostring) end')
      [ -n "$idx" ] || { echo "ERROR: no button '$F_ANSWER' (buttons: $(printf '%s' "$box" | jq -c '.buttons'))" >&2; exit 4; }
      post menu "{\"action\":\"accept\",\"index\":$idx}" >/dev/null || exit $?
      label=$(printf '%s' "$box" | jq -r --argjson i "$idx" '.buttons[$i]')
      sleep 0.5
      next=$(post menu '{"action":"describe"}' 2>/dev/null | jq -c 'if .messageBoxOpen then {bodyText, buttons} else empty end' 2>/dev/null)
      echo "ANSWERED: $label (index $idx)"
      [ -n "$next" ] && echo "NEXT BOX: $next"
      exit 0 ;;

  coc)
      # Console `coc <cell>`, then wait until the load is over: no Loading Menu, a loaded player in the target cell,
      # and the frame counter advancing. 0 arrived, 3 timeout, 4 the console rejected the cell.
      [ $# -ge 1 ] || { echo "usage: devbench-cli.sh coc <CellEditorID> [--timeout 120]" >&2; exit 1; }
      need_jq coc
      target="$1"; limit="${F_TIMEOUT:-120}"; tl=$(printf '%s' "$target" | tr '[:upper:]' '[:lower:]')
      from=$(player_cell)
      out=$(post console "{\"action\":\"exec\",\"command\":$(json_string "coc $target"),\"capture\":true}") || exit $?
      if printf '%s' "$out" | jq -r '(.lines // [])[]' 2>/dev/null | grep -qi 'not found\|invalid'; then
          echo "ERROR: coc rejected: $(printf '%s' "$out" | jq -r '(.lines // []) | join(" / ")')" >&2; exit 4
      fi
      start=$(now_ms); saw_loading=0; arrived=""; settle=0; cur=""; cl=""
      while :; do
          sleep 1
          el=$(( ($(now_ms) - start) / 1000 ))
          if probe_health && [ "${PH_CODE:-}" = 200 ]; then
              case "$PH_BODY" in *'"Loading Menu"'*) saw_loading=1; settle=0; continue ;; esac
              cur=$(player_cell); cl=$(printf '%s' "$cur" | tr '[:upper:]' '[:lower:]')
              # before the load visibly starts, the old cell (even the same one) proves nothing: wait 3 s for it
              if [ -n "$cur" ] && { [ "$saw_loading" -eq 1 ] || [ "$el" -ge 3 ]; }; then
                  f1=$(printf '%s' "$PH_BODY" | jget '.frame'); sleep 0.5; probe_health
                  f2=$(printf '%s' "$PH_BODY" | jget '.frame')
                  if [ -n "$f1" ] && [ "$f1" != "$f2" ]; then
                      if [ "$cl" = "$tl" ]; then echo "ARRIVED: $cur after ${el}s"; exit 0; fi
                      # an exterior coc can land in a neighbouring cell: accept a changed cell after 5 settled seconds
                      if [ "$cur" != "$from" ]; then settle=$((settle + 1)); arrived="$cur"
                          [ "$settle" -ge 5 ] && { echo "ARRIVED: $cur after ${el}s (asked for $target; an exterior coc can land in a neighbouring cell)"; exit 0; }
                      fi
                  fi
              fi
          fi
          # The console prints nothing for an unknown cell (checked live 2026-11-13). A real coc always shows the
          # Loading Menu, so 10 s with no load and the player still in the old cell means it did nothing.
          if [ "$saw_loading" -eq 0 ] && [ "$el" -ge 10 ] && [ -n "$cur" ] && [ "$cur" = "$from" ] && [ "$cl" != "$tl" ]; then
              echo "ERROR: coc $target did nothing after ${el}s (no loading screen, still in $cur): unknown cell?" >&2; exit 4
          fi
          if [ "$el" -ge "$limit" ]; then
              echo "TIMEOUT after ${el}s: player in ${cur:-${arrived:-unknown}}, wanted $target"; exit 3
          fi
      done ;;

  goto)
      # Put the player BESIDE a reference, never inside it: `player.moveto <ref>` lands in the ref's own collision
      # (stuck in a runestone, 2026-11-13). Moves --dist units (150) in front of the ref along its facing, --z (20)
      # up, turns the player to face it, then waits for its 3D. --if-unloaded: do nothing when the 3D is already
      # loaded (Activate works from across the cell). 0 there, 3 its 3D did not load, 4 the reference is unknown.
      [ $# -ge 1 ] || { echo "usage: devbench-cli.sh goto <0xREF | Plugin.esp:id> [--dist 150] [--z 20] [--if-unloaded] [--timeout 30]" >&2; exit 1; }
      need_jq goto
      ref=$(resolve_form "$1") || exit 4
      self="{\"form\":\"$ref\"}"
      loaded=$(pcall ObjectReference Is3DLoaded '[]' "$self" 2>/dev/null)
      if [ -z "$loaded" ]; then
          echo "ERROR: reference $ref is not in memory (a temporary reference in an unloaded cell). 'coc' to its cell first." >&2
          exit 4
      fi
      if [ "$F_IFUNLOADED" -eq 1 ] && [ "$loaded" = true ]; then echo "ALREADY LOADED: $ref (player not moved)"; exit 0; fi
      az=$(pcall ObjectReference GetAngleZ '[]' "$self") || exit $?
      read -r dx dy dz face < <(awk -v a="$az" -v d="$F_DIST" -v z="$F_Z" 'BEGIN { r = a * 3.14159265358979 / 180
          printf "%.1f %.1f %.1f %.1f\n", d * sin(r), d * cos(r), z, (a + 180) % 360 }')
      pcall ObjectReference MoveTo "[$self,$dx,$dy,$dz,false]" '{"form":"0x14"}' >/dev/null || exit $?
      limit="${F_TIMEOUT:-30}"; start=$(now_ms)
      while :; do
          sleep 1
          [ "$(pcall ObjectReference Is3DLoaded '[]' "$self" 2>/dev/null)" = true ] && break
          [ $(( ($(now_ms) - start) / 1000 )) -ge "$limit" ] && { echo "TIMEOUT: moved, but the 3D of $ref did not load in ${limit}s"; exit 3; }
      done
      pcall ObjectReference SetAngle "[0.0,0.0,$face]" '{"form":"0x14"}' >/dev/null 2>&1
      dist=$(pcall ObjectReference GetDistance '[{"form":"0x14"}]' "$self" 2>/dev/null)
      echo "AT: $ref (distance ${dist:-?}, cell $(player_cell))"
      exit 0 ;;

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

  logmark)
      # Record how long the Papyrus log is now, so `logdiff` can show only what a test added.
      log=$(papyrus_log_path) || exit 3
      [ -f "$log" ] || { echo "ERROR: Papyrus log not found: $log (Papyrus logging may be off, or the game has not run yet)." >&2; exit 3; }
      size=$(file_size "$log")
      mkdir -p "$DIAG_DIR" || { echo "ERROR: cannot create $DIAG_DIR" >&2; exit 1; }
      hlen=$size; [ "$hlen" -le 256 ] || hlen=256
      printf 'path=%s\nsize=%s\nhead=%s\nheadlen=%s\n' "$log" "$size" "$(file_head_sum "$log" "$hlen")" "$hlen" > "$PAPYRUS_MARK" \
          || { echo "ERROR: cannot write $PAPYRUS_MARK" >&2; exit 1; }
      echo "mark${MARK_NAME:+ '$MARK_NAME'}: $size bytes  $log" ;;

  logdiff)
      # Everything the Papyrus log gained since `logmark`. --errors keeps lines containing error/warning plus
      # their continuation (stack) lines. Says so when the log was rotated or truncated since the mark.
      [ -f "$PAPYRUS_MARK" ] || { echo "ERROR: no mark${MARK_NAME:+ '$MARK_NAME'} yet; run 'devbench-cli.sh logmark${MARK_NAME:+ --name $MARK_NAME}' first." >&2; exit 1; }
      log=$(papyrus_log_path) || exit 3
      [ -f "$log" ] || { echo "ERROR: Papyrus log not found: $log" >&2; exit 3; }
      msize=$(mark_field size); mpath=$(mark_field path); mhead=$(mark_field head); mhlen=$(mark_field headlen)
      case "$mhlen" in ''|*[!0-9]*) mhlen=256 ;; esac   # a mark written before headlen existed hashed 256 bytes (or "-")
      case "$msize" in ''|*[!0-9]*) echo "ERROR: $PAPYRUS_MARK is unreadable; run logmark again." >&2; exit 1 ;; esac
      size=$(file_size "$log"); start=$(( msize + 1 )); why=""
      if [ "$log" != "$mpath" ]; then why="the log path changed (was $mpath)"
      elif [ "$size" -lt "$msize" ]; then why="the log shrank ($msize -> $size bytes)"
      elif [ "$mhead" != "-" ] && [ "$msize" -gt 0 ] && [ "$(file_head_sum "$log" "$mhlen")" != "$mhead" ]; then why="the log's opening bytes changed"
      fi
      if [ -n "$why" ]; then
          echo "NOTE: the log was rotated or replaced since the mark: $why. Showing the whole current log ($size bytes)." >&2
          start=1
      elif [ "$size" -eq "$msize" ]; then
          echo "(no new Papyrus log output since the mark at $msize bytes)" >&2
          exit 0
      fi
      refhex=""
      if [ -n "$F_REF" ]; then
          refhex=$(resolve_form "$F_REF") || exit 4
          refhex=$(printf '%s' "${refhex#0[xX]}" | tr '[:lower:]' '[:upper:]')
          while [ ${#refhex} -lt 8 ]; do refhex="0$refhex"; done
      fi
      if [ "$F_ERRORS" -eq 1 ] || [ "$HAVE_GREP" -eq 1 ] || [ -n "$refhex" ]; then
          tail -c +"$start" "$log" | filter_entries "$F_ERRORS" "$GREP" "$refhex"
      else
          tail -c +"$start" "$log"
      fi ;;

  port)
      echo "$PORT" ;;

  ""|-h|--help|help)
      sed -n '2,/^set -u/{ /^set -u/d; p; }' "$0" | sed 's/^# \{0,1\}//' ;;

  *)
      echo "Unknown command: $CMD" >&2
      echo "Try: ping | alive | wait | health | quest | state | fps | inspect <kind> | exec | call | waitcall | form | coc | goto | msgbox | describe | notify | logmark | logdiff | tool | gfx | dialogue | tools | port" >&2
      exit 1 ;;
esac

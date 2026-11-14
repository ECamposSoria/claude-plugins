#!/usr/bin/env bash
# VoiceStudio on the laptop's GPU, started on demand so the laptop's WSL stays off between jobs.
# `up` opens one WSL session that starts the container and then holds the session open (WSL stops a distro,
# containers included, once no session is left) until `down` or the deadline; after that WSL shuts itself off.
#
#   voicestudio_remote.sh up [--for MINUTES]   start or extend (default 30 min), return once $URL answers
#   voicestudio_remote.sh down                 stop it and free the GPU
#   voicestudio_remote.sh status
#
# Exit codes: 0 ok, 1 failed, 2 usage, 3 the laptop cannot take it (unreachable, GPU busy, WSL stuck): use
# ElevenLabs or the VM's CPU copy instead.
set -euo pipefail

HOST="${VOICESTUDIO_HOST:-lenovo-nat}"
URL="${VOICESTUDIO_URL:-http://127.0.0.1:13900}"     # the VM end of host-gpu-tunnel.service
MIN_FREE_MIB="${VOICESTUDIO_MIN_FREE_MIB:-4500}"     # VoiceStudio holds ~3.9 GB of VRAM
UNIT=voicestudio-hold
DIR="${XDG_STATE_HOME:-$HOME/.local/state}/voicestudio-remote"
SSH_OPTS=(-T -o BatchMode=yes -o ConnectTimeout=10 -o ServerAliveInterval=30 -o ServerAliveCountMax=4)
mkdir -p "$DIR"

# Runs inside the laptop's WSL. cmd.exe sits between ssh and WSL and mangles nested quotes, so the script goes
# in on stdin and only plain words go on the command line. Everything is inside main() so bash has read all of
# it before any command could consume stdin. Its status lines start with VSR: so container logs can't pass
# for them. $S holds the deadline and is the claim: the holder writes it (and its pid to $S.pid) before
# starting the container, `down` removes it, and a holder that finds it gone stops the container and exits.
# The lock makes "the deadline passed, stop" and "extend the deadline" exclude each other.
read -r -d '' REMOTE <<'EOF' || true
main() {
    local C=~/voicestudio/docker-compose.yml S=/dev/shm/voicestudio-hold free t deadline pid i=0
    command -v nvidia-smi >/dev/null || PATH="$PATH:/usr/lib/wsl/lib"
    dc() { docker compose -p voicestudio -f "$C" "$@"; }
    running() { [ "$(docker inspect -f '{{.State.Running}}' voicestudio 2>/dev/null)" = true ]; }
    publish() { echo "$1" > "$S.$$" && mv -f "$S.$$" "$S"; }
    later() {   # push the deadline to MINUTES from now, never earlier than it already is (call under the lock)
        t=$(( $(date +%s) + $1 * 60 ))
        if [ ! -f "$S" ] || [ "$t" -gt "$(cat "$S")" ]; then publish "$t"; fi
    }
    release() { flock 9; rm -f "$S"; if [ "$(cat "$S.pid" 2>/dev/null)" = "$$" ]; then rm -f "$S.pid"; fi; flock -u 9; }
    exec 9>"$S.lock"
    case "$1" in
    hold)   # hold MINUTES MIN_FREE_MIB
        flock 9; later "$2"; echo $$ > "$S.pid"; flock -u 9
        if ! running; then
            free="$(nvidia-smi --query-gpu=memory.free --format=csv,noheader,nounits | head -1)"
            if ! [ "$free" -ge "$3" ] 2>/dev/null; then
                echo "VSR:BUSY ${free:-?} MiB of VRAM free, $3 needed. Containers there:"
                docker ps --format '  {{.Names}} ({{.Image}})'
                release; return 3
            fi
            dc up -d --wait --wait-timeout 300 || { echo "VSR:FAILED docker compose up"; dc logs --tail 30; dc down; release; return 1; }
        fi
        flock 9
        if [ -f "$S" ]; then
            later "$2"; flock -u 9
            echo VSR:READY
            while running; do
                sleep 5
                flock 9
                deadline="$(cat "$S" 2>/dev/null)" || deadline=""
                if [ -z "$deadline" ] || [ "$(date +%s)" -ge "$deadline" ]; then rm -f "$S"; flock -u 9; break; fi
                flock -u 9
            done
        else
            flock -u 9; echo VSR:CANCELLED  # `down` arrived during startup
        fi
        if running; then dc down || echo "VSR:FAILED docker compose down"; fi
        release
        echo VSR:STOPPED ;;
    extend) # extend MINUTES
        flock 9
        [ -f "$S" ] || { flock -u 9; echo VSR:NOHOLD; return 1; }
        later "$2"
        echo "VSR:UNTIL $(cat "$S")"
        flock -u 9 ;;
    down)
        flock 9; rm -f "$S"; pid="$(cat "$S.pid" 2>/dev/null)" || pid=""; flock -u 9
        # The holder notices within 5 s, or once its startup returns (up to 300 s), and stops the container.
        while [ "$i" -lt 165 ] && [ -n "$pid" ] && [ -f "$S.pid" ] && kill -0 "$pid" 2>/dev/null; do sleep 2; i=$((i + 1)); done
        if running; then dc down || { echo "VSR:FAILED docker compose down"; return 1; }; fi
        echo VSR:DOWN ;;
    esac
}
main "$@" </dev/null
EOF

# A short WSL call. A launch that collides with another one while the distro boots fails after ~10 s (the
# OpenAI Codex app polls WSL every few seconds while it has a WSL project open); WSL before 3.0.5 wedged instead,
# failing every launch with Wsl/Service/E_UNEXPECTED. Killing our ssh does not kill wsl.exe on Windows, so the
# timeout only frees this script.
remote() { printf '%s\n' "$REMOTE" | timeout 400 ssh "${SSH_OPTS[@]}" "$HOST" "wsl -d Ubuntu -- bash -l -s -- $*" 2>&1 | tr -d '\r'; }
answers() { curl -fsS -m 5 -o /dev/null "$URL/health" 2>/dev/null; }
holding() { systemctl --user is-active -q "$UNIT"; }
wsl_state() { timeout 20 ssh "${SSH_OPTS[@]}" "$HOST" "wsl -l -v" 2>/dev/null | tr -d '\0\r' | awk '/Ubuntu/ {print $(NF-1)}'; }   # no launch
wedged_help() {
    echo "  Check: ssh $HOST \"wsl -d Ubuntu -u root -- dmesg\" | grep -E 'Timed out|CaptureCrash'  (if that hangs too, WSL is stuck)" >&2
    echo "  Clearing it takes 'wsl --terminate Ubuntu' on the laptop, which kills everything in that distro: ask the owner." >&2
}

start_hold() {
    printf '%s\n' "$REMOTE" > "$DIR/remote.sh"
    systemd-run --user --unit "$UNIT" --collect -q \
        -p StandardInput=file:"$DIR/remote.sh" -p StandardOutput=truncate:"$DIR/hold.log" -p StandardError=inherit \
        ssh "${SSH_OPTS[@]}" "$HOST" "wsl -d Ubuntu -- bash -l -s -- hold $1 $MIN_FREE_MIB"
}

# 0 ready, 1 failed, 3 busy or stuck, 4 the hold ended early for another reason (worth one retry).
wait_ready() {
    local i log
    for ((i = 0; i < 84; i++)); do              # 7 min: WSL boot, image start and the model load
        if ! holding; then
            log="$(tr -d '\r' < "$DIR/hold.log" 2>/dev/null)" || log=""
            case "$log" in
                *VSR:BUSY*) echo "voicestudio_remote: GPU busy: ${log#*VSR:BUSY }" >&2
                        echo "Ask the owner before sharing it, or use ElevenLabs / the CPU copy." >&2; return 3 ;;
                *E_UNEXPECTED*) echo "voicestudio_remote: WSL on the laptop is stuck (Wsl/Service/E_UNEXPECTED)." >&2
                        wedged_help; return 3 ;;
                *"VSR:FAILED docker compose up"*) echo "voicestudio_remote: the container did not start:" >&2
                        printf '%s\n' "$log" | tail -30 >&2; return 1 ;;
                *VSR:CANCELLED*) echo "voicestudio_remote: a 'down' stopped it while it was starting" >&2; return 1 ;;
                *) printf '%s\n' "$log" | tail -5 > "$DIR/last-failure.log"; return 4 ;;
            esac
        fi
        # /health can answer before compose's --wait returns; the hold exists only once its holder says READY.
        if answers && grep -q VSR:READY "$DIR/hold.log" 2>/dev/null; then return 0; fi
        sleep 5
    done
    echo "voicestudio_remote: nothing answered at $URL after 7 min." >&2
    if ! systemctl --user is-active -q host-gpu-tunnel; then
        echo "  The tunnel is down: systemctl --user status host-gpu-tunnel. The container may still be up: run 'down'." >&2
    elif ! grep -q VSR:READY "$DIR/hold.log" 2>/dev/null; then
        echo "  The WSL launch never got going, which is how a stuck WSL looks." >&2; wedged_help
    fi
    systemctl --user stop "$UNIT" 2>/dev/null || true
    return 3
}

# Start a hold and wait for it, retrying once when the WSL session ends early (a launch collision).
fresh_hold() {
    local rc=0
    start_hold "$1"; wait_ready || rc=$?
    if [ "$rc" -eq 4 ]; then
        sleep 5; rc=0; start_hold "$1"; wait_ready || rc=$?
        if [ "$rc" -eq 4 ]; then
            echo "voicestudio_remote: the WSL session ended before VoiceStudio came up:" >&2
            cat "$DIR/last-failure.log" >&2; rc=3
        fi
    fi
    return "$rc"
}

up() {
    local mins="$1" rc=0 out i
    if ! holding; then
        fresh_hold "$mins" || return $?
    else
        # Join the running hold: let it come up, then push its deadline out to ours.
        wait_ready || rc=$?
        if [ "$rc" -eq 4 ]; then fresh_hold "$mins" || return $?
        elif [ "$rc" -ne 0 ]; then return "$rc"
        else
            out="$(remote extend "$mins")" || true
            case "$out" in
                *VSR:UNTIL*) echo "voicestudio_remote: hold runs until $(date -d "@${out##*VSR:UNTIL }" +%H:%M)" ;;
                *VSR:NOHOLD*)       # it reached its deadline as we joined: let it finish, then start afresh
                    for ((i = 0; i < 24; i++)); do holding || break; sleep 5; done
                    systemctl --user stop "$UNIT" 2>/dev/null || true
                    fresh_hold "$mins" || return $? ;;
                *) echo "voicestudio_remote: could not extend the hold: $out" >&2; return 1 ;;
            esac
        fi
    fi
    echo "voicestudio_remote: ready at $URL (run 'down' when done)"
}

down() {
    local i out state
    if ! holding && ! answers; then
        state="$(wsl_state)" || state=""
        case "$state" in
            Stopped) echo "voicestudio_remote: not running (the laptop's WSL is off)"; return 0 ;;
            Running) ;;     # a lost tunnel or hold can leave the container up: stop it explicitly
            *) echo "voicestudio_remote: laptop unreachable ($HOST); can't confirm VoiceStudio is stopped" >&2; return 3 ;;
        esac
    fi
    out="$(remote down)" || true
    for ((i = 0; i < 12; i++)); do holding || break; sleep 5; done
    if holding; then
        systemctl --user stop "$UNIT" 2>/dev/null || true
        echo "voicestudio_remote: the WSL session did not close after the stop; VoiceStudio may still be up: $out" >&2
        return 1
    fi
    case "$out" in
        *VSR:DOWN*) echo "voicestudio_remote: stopped; WSL shuts itself off once nothing else holds it" ;;
        *VSR:FAILED*) echo "voicestudio_remote: the container did not stop:" >&2; printf '%s\n' "$out" | tail -20 >&2; return 1 ;;
        *) echo "voicestudio_remote: could not reach WSL to stop the container: $out" >&2; wedged_help; return 3 ;;
    esac
}

status() {
    local wsl
    if holding; then echo "hold: active ($(systemctl --user show -p ActiveEnterTimestamp --value "$UNIT"))"; else echo "hold: none"; fi
    if answers; then echo "VoiceStudio: answering at $URL"; else echo "VoiceStudio: not answering at $URL"; fi
    echo "tunnel: $(systemctl --user is-active host-gpu-tunnel 2>&1)"
    wsl="$(wsl_state)" || wsl=""
    echo "laptop WSL: ${wsl:-unreachable}"
}

# One up/down at a time on this VM: a down issued while an up is still launching would otherwise reach WSL before
# the holder claims the hold, find nothing, and let the container start after it.
serialize() {
    exec 8>"$DIR/lock"
    flock -n 8 || { echo "voicestudio_remote: waiting for another up/down on this VM to finish" >&2; flock 8; }
}

case "${1:-}" in
    up)
        mins=30
        if [ "${2:-}" = --for ]; then mins="${3:-}"; fi
        if ! [[ "$mins" =~ ^[0-9]+$ ]] || [ "$((10#$mins))" -lt 1 ] || [ "$((10#$mins))" -gt 720 ]; then
            echo "usage: voicestudio_remote.sh up [--for MINUTES (1-720)]" >&2; exit 2
        fi
        serialize
        up "$((10#$mins))" ;;
    down) serialize; down ;;
    status) status ;;
    *) echo "usage: voicestudio_remote.sh up [--for MINUTES] | down | status" >&2; exit 2 ;;
esac

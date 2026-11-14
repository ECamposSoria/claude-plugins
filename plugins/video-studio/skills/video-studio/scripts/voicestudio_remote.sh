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
# it before any command could consume stdin.
read -r -d '' REMOTE <<'EOF' || true
main() {
    local C=~/voicestudio/docker-compose.yml S=/dev/shm/voicestudio-hold free t
    command -v nvidia-smi >/dev/null || PATH="$PATH:/usr/lib/wsl/lib"
    dc() { docker compose -p voicestudio -f "$C" "$@"; }
    running() { [ "$(docker inspect -f '{{.State.Running}}' voicestudio 2>/dev/null)" = true ]; }
    case "$1" in
    hold)   # hold MINUTES MIN_FREE_MIB
        if ! running; then
            free="$(nvidia-smi --query-gpu=memory.free --format=csv,noheader,nounits | head -1)"
            if ! [ "$free" -ge "$3" ] 2>/dev/null; then
                echo "BUSY ${free:-?} MiB of VRAM free, $3 needed. Containers there:"
                docker ps --format '  {{.Names}} ({{.Image}})'
                return 3
            fi
            dc up -d --wait --wait-timeout 300 || { echo "FAILED docker compose up"; dc logs --tail 30; dc down; return 1; }
        fi
        echo $(( $(date +%s) + $2 * 60 )) > "$S"
        echo READY
        while running && [ "$(date +%s)" -lt "$(cat "$S" 2>/dev/null || echo 0)" ]; do sleep 15; done
        ! running || dc down
        rm -f "$S"
        echo STOPPED ;;
    extend) # extend MINUTES
        [ -f "$S" ] || { echo NOHOLD; return 1; }
        t=$(( $(date +%s) + $2 * 60 ))
        [ "$t" -le "$(cat "$S")" ] || echo "$t" > "$S"
        echo "UNTIL $(cat "$S")" ;;
    down)
        rm -f "$S"
        ! running || dc down
        echo DOWN ;;
    esac
}
main "$@" </dev/null
EOF

# A short WSL call. A launch that collides with another one while the distro boots fails after ~10 s (the
# OpenAI Codex app polls WSL every few seconds while it has a WSL project open); WSL before 3.0.5 wedged instead,
# failing every launch with Wsl/Service/E_UNEXPECTED. Killing our ssh does not kill wsl.exe on Windows, so the
# timeout only frees this script.
remote() { printf '%s\n' "$REMOTE" | timeout 120 ssh "${SSH_OPTS[@]}" "$HOST" "wsl -d Ubuntu -- bash -l -s -- $*" 2>&1 | tr -d '\r'; }
answers() { curl -fsS -m 5 -o /dev/null "$URL/health" 2>/dev/null; }
holding() { systemctl --user is-active -q "$UNIT"; }
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
            log="$(tr -d '\r' < "$DIR/hold.log" 2>/dev/null)"
            case "$log" in
                *BUSY*) echo "voicestudio_remote: GPU busy: ${log#*BUSY }" >&2
                        echo "Ask the owner before sharing it, or use ElevenLabs / the CPU copy." >&2; return 3 ;;
                *E_UNEXPECTED*) echo "voicestudio_remote: WSL on the laptop is stuck (Wsl/Service/E_UNEXPECTED)." >&2
                        wedged_help; return 3 ;;
                *FAILED*) echo "voicestudio_remote: the container did not start:" >&2; printf '%s\n' "$log" | tail -30 >&2; return 1 ;;
                *) printf '%s\n' "$log" | tail -5 > "$DIR/last-failure.log"; return 4 ;;
            esac
        fi
        if answers; then return 0; fi
        sleep 5
    done
    echo "voicestudio_remote: nothing answered at $URL after 7 min." >&2
    if ! systemctl --user is-active -q host-gpu-tunnel; then
        echo "  The tunnel is down: systemctl --user status host-gpu-tunnel" >&2
    elif ! grep -q READY "$DIR/hold.log" 2>/dev/null; then
        echo "  The WSL launch never got going, which is how a stuck WSL looks." >&2; wedged_help
    fi
    systemctl --user stop "$UNIT" 2>/dev/null || true
    return 3
}

up() {
    local mins="$1" rc out
    if holding; then
        if grep -q READY "$DIR/hold.log" 2>/dev/null; then
            out="$(remote extend "$mins")" || true
            case "$out" in
                *UNTIL*) echo "voicestudio_remote: hold extended to $(date -d "@${out##*UNTIL }" +%H:%M)" ;;
                *) echo "voicestudio_remote: could not extend the hold: $out" >&2; return 1 ;;
            esac
        fi
    else
        start_hold "$mins"
    fi
    rc=0; wait_ready || rc=$?
    if [ "$rc" -eq 4 ]; then
        sleep 5; start_hold "$mins"; rc=0; wait_ready || rc=$?
        [ "$rc" -ne 4 ] || { echo "voicestudio_remote: the WSL session ended before VoiceStudio came up:" >&2
                             cat "$DIR/last-failure.log" >&2; rc=3; }
    fi
    [ "$rc" -eq 0 ] && echo "voicestudio_remote: ready at $URL (run 'down' when done)"
    return "$rc"
}

down() {
    local i out
    if ! holding && ! answers; then echo "voicestudio_remote: not running"; return 0; fi
    out="$(remote down)" || true
    for ((i = 0; i < 12; i++)); do holding || break; sleep 5; done
    systemctl --user stop "$UNIT" 2>/dev/null || true
    case "$out" in
        *DOWN*) echo "voicestudio_remote: stopped; WSL shuts itself off once nothing else holds it" ;;
        *) echo "voicestudio_remote: could not reach WSL to stop the container: $out" >&2; wedged_help; return 3 ;;
    esac
}

status() {
    local wsl
    if holding; then echo "hold: active ($(systemctl --user show -p ActiveEnterTimestamp --value "$UNIT"))"; else echo "hold: none"; fi
    if answers; then echo "VoiceStudio: answering at $URL"; else echo "VoiceStudio: not answering at $URL"; fi
    echo "tunnel: $(systemctl --user is-active host-gpu-tunnel 2>&1)"
    wsl="$(timeout 20 ssh "${SSH_OPTS[@]}" "$HOST" "wsl -l -v" 2>&1 | tr -d '\0\r' | awk '/Ubuntu/ {print $(NF-1)}')" || true
    echo "laptop WSL: ${wsl:-unreachable}"
}

case "${1:-}" in
    up)
        mins=30
        if [ "${2:-}" = --for ]; then mins="${3:-}"; fi
        if ! [[ "$mins" =~ ^[0-9]+$ ]] || [ "$mins" -lt 1 ] || [ "$mins" -gt 720 ]; then
            echo "usage: voicestudio_remote.sh up [--for MINUTES (1-720)]" >&2; exit 2
        fi
        up "$mins" ;;
    down) down ;;
    status) status ;;
    *) echo "usage: voicestudio_remote.sh up [--for MINUTES] | down | status" >&2; exit 2 ;;
esac

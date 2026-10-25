#!/usr/bin/env bash
# Run listen.py on the laptop's GPU (WSL Docker, image video-studio-listener:0.1.0-cu128) and copy the
# results back. Same arguments as listen.py; paths stay local.
#
#   listen_remote.sh SONG [-o OUTDIR] [--lyrics FILE] [--force] [other listen.py options]
#
# Exit codes: listen.py's own (0 written, 1 failed, 2 usage/refused), or 3 when the laptop cannot take the job
# (unreachable, GPU busy, image missing, transfer failed): run the CPU container on the VM instead.
set -euo pipefail

HOST="${LISTEN_HOST:-lenovo-nat}"
BUSY_MIB="${LISTEN_GPU_BUSY_MIB:-1500}"   # the idle desktop holds ~850 MiB; more means another job is on the GPU
SCRIPTS="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ssh_l() { ssh -o BatchMode=yes -o ConnectTimeout=10 -o ServerAliveInterval=30 "$HOST" "$@"; }
# cmd.exe sits between ssh and WSL and mangles nested quotes, so each remote script is uploaded to a file
# first and then run. Files never travel through that pipe (150 MB stalled it): they go by scp to the
# Windows home, which WSL sees under /mnt/<drive>.
remote() {
    local f="/tmp/listen-remote-$$-$RANDOM.sh"
    printf 'rm -f %q\n%s\n' "$f" "$1" | ssh_l "wsl -- bash -lc \"cat > $f\"" || return 3
    ssh_l "wsl -- bash -l $f" </dev/null
}

[ $# -ge 1 ] || { echo "usage: listen_remote.sh SONG [-o OUTDIR] [listen.py options]" >&2; exit 2; }
song="$1"; shift
[ -f "$song" ] || { echo "listen_remote: no such file: $song" >&2; exit 2; }
out="$(dirname "$song")"; lyrics=""; force=0; pass=()
while [ $# -gt 0 ]; do
    case "$1" in
        -o) out="$2"; shift 2 ;;
        --lyrics) lyrics="$2"; pass+=(--lyrics "/work/lyrics.txt"); shift 2 ;;
        --device) shift 2 ;;
        --force) force=1; pass+=(--force); shift ;;
        *) pass+=("$1"); shift ;;
    esac
done
[ -z "$lyrics" ] || [ -f "$lyrics" ] || { echo "listen_remote: no such lyrics file: $lyrics" >&2; exit 2; }
if [ "$force" -eq 0 ]; then
    for f in README.md analysis.json features.json; do
        [ ! -e "$out/$f" ] || { echo "listen_remote: $out/$f exists; pass --force to overwrite" >&2; exit 2; }
    done
fi

state="$(remote 'nvidia-smi --query-gpu=memory.used --format=csv,noheader,nounits | head -1;
docker image inspect video-studio-listener:0.1.0-cu128 >/dev/null 2>&1 && echo image-ok || echo image-missing' \
    2>/dev/null | tr -d '\r')" || { echo "listen_remote: laptop unreachable ($HOST)" >&2; exit 3; }
used="$(printf '%s\n' "$state" | head -1)"
case "$state" in *image-ok*) ;; *) echo "listen_remote: image missing on the laptop; build it (setup/listener/README.md)" >&2; exit 3 ;; esac
if ! [ "$used" -eq "$used" ] 2>/dev/null || [ "$used" -gt "$BUSY_MIB" ]; then
    echo "listen_remote: GPU busy (${used} MiB in use). Containers there:" >&2
    remote 'docker ps --format "  {{.Names}} ({{.Image}})"' >&2 || true
    echo "Ask the owner before sharing it, or run the CPU container." >&2
    exit 3
fi

winhome="$(ssh_l 'echo %USERPROFILE%' </dev/null | tr -d '\r' | sed 's/ *$//')"        # C:\Users\<name>
drive="$(printf '%s' "${winhome%%:*}" | tr '[:upper:]' '[:lower:]')"
wsl_home="/mnt/$drive$(printf '%s' "${winhome#*:}" | tr '\\' '/')"
job="$(date -u +%Y%m%dT%H%M%S)-$$"
name="$(basename "$song" | tr ':*?"<>|\\' '_______')"   # characters Windows refuses in file names
stage="$(mktemp -d)"
cleanup() { rm -rf "$stage"; ssh_l "rmdir /s /q listener\\jobs\\$job" </dev/null >/dev/null 2>&1 || true; }
trap cleanup EXIT

ssh_l "mkdir listener\\jobs\\$job\\tool" </dev/null >/dev/null || { echo "listen_remote: cannot create the job folder" >&2; exit 3; }
cp "$song" "$stage/$name"
scp -q -o BatchMode=yes "$stage/$name" "$HOST:listener/jobs/$job/" \
    && scp -q -o BatchMode=yes "$SCRIPTS/listen.py" "$HOST:listener/jobs/$job/tool/" \
    && { [ -z "$lyrics" ] || scp -q -o BatchMode=yes "$lyrics" "$HOST:listener/jobs/$job/lyrics.txt"; } \
    || { echo "listen_remote: upload failed" >&2; exit 3; }

printf -v args ' %q' "${pass[@]+"${pass[@]}"}"
set +e
remote "cd ~/listener/setup && docker compose -p listener -f docker-compose.gpu.yml run --rm -T \
  -v $(printf '%q' "$wsl_home/listener/jobs/$job"):/work -v $(printf '%q' "$wsl_home/listener/jobs/$job/tool"):/tool:ro \
  listener /tool/listen.py $(printf '%q' "/work/$name") -o /work/out --device cuda$args"
status=$?
set -e
[ "$status" -eq 0 ] || exit "$status"
scp -q -r -o BatchMode=yes "$HOST:listener/jobs/$job/out" "$stage/" || { echo "listen_remote: download failed" >&2; exit 3; }
mkdir -p "$out"
cp -r "$stage/out/." "$out/"
echo "listen_remote: results in $out"

#!/usr/bin/env bash
# composite.sh — ffmpeg helpers for the hybrid leg.
# Subcommands:
#   overlay   layer a (usually alpha) animation clip over a base video, optionally timed
#   concat    join clips (intro/base/outro), normalizing res/fps/audio so they splice cleanly
#   mixaudio  duck/mix a music bed under the main audio (voiceover)
#
# Patterns inspired by OpenMontage's compose stage (AGPLv3) but written from scratch.
# Re-encodes are HEAVY — run in the background or hand to the user for long inputs.
set -euo pipefail

die() { echo "error: $*" >&2; exit 1; }
have_audio() { [ "$(ffprobe -v error -select_streams a:0 -show_entries stream=codec_type -of default=nk=1:nw=1 "$1")" = "audio" ]; }
vdim()  { ffprobe -v error -select_streams v:0 -show_entries stream="$2" -of default=nk=1:nw=1 "$1"; }
duration() { ffprobe -v error -show_entries format=duration -of default=nk=1:nw=1 "$1"; }
fps_of() {
  local r; r=$(ffprobe -v error -select_streams v:0 -show_entries stream=r_frame_rate -of default=nk=1:nw=1 "$1")
  awk -v r="$r" 'BEGIN{n=split(r,a,"/"); if(n==2 && a[2]!=0) printf "%.5f", a[1]/a[2]; else printf "%s", r}'
}

cmd_overlay() {
  local base="" ovl="" out="" x="0" y="0" start="" dur=""
  while [ $# -gt 0 ]; do case "$1" in
    --base) base="$2"; shift 2;; --overlay) ovl="$2"; shift 2;; --output) out="$2"; shift 2;;
    --x) x="$2"; shift 2;; --y) y="$2"; shift 2;; --start) start="$2"; shift 2;; --duration) dur="$2"; shift 2;;
    *) die "overlay: unknown arg $1";; esac; done
  [ -n "$base" ] && [ -n "$ovl" ] && [ -n "$out" ] || die "overlay needs --base --overlay --output"
  [ -f "$base" ] || die "no such file: $base"; [ -f "$ovl" ] || die "no such file: $ovl"

  local enable=""
  if [ -n "$start" ] && [ -n "$dur" ]; then
    enable=":enable='between(t,${start},$(awk -v s="$start" -v d="$dur" 'BEGIN{printf "%.3f", s+d}'))'"
  fi
  # overlay stays on top; eof_action=pass keeps base playing after the overlay ends
  local fc="[0:v][1:v]overlay=x=${x}:y=${y}:eof_action=pass${enable}[outv]"
  local map_a=()
  if have_audio "$base"; then map_a=(-map 0:a -c:a copy); fi
  echo "[overlay] $ovl over $base @ (${x},${y}) ${start:+timed ${start}s+${dur}s}" >&2
  ffmpeg -y -i "$base" -i "$ovl" -filter_complex "$fc" -map "[outv]" "${map_a[@]}" \
    -c:v libx264 -crf 18 -preset veryfast -pix_fmt yuv420p -movflags +faststart "$out"
  echo "[overlay] wrote $out" >&2
}

cmd_concat() {
  local out=""; local inputs=()
  while [ $# -gt 0 ]; do case "$1" in
    --output) out="$2"; shift 2;; *) inputs+=("$1"); shift;; esac; done
  [ -n "$out" ] || die "concat needs --output"
  [ "${#inputs[@]}" -ge 2 ] || die "concat needs at least 2 input files"
  for f in "${inputs[@]}"; do [ -f "$f" ] || die "no such file: $f"; done

  # target geometry/fps from the first input
  local W H FPS; W=$(vdim "${inputs[0]}" width); H=$(vdim "${inputs[0]}" height); FPS=$(fps_of "${inputs[0]}")
  echo "[concat] target ${W}x${H} @ ${FPS}fps, ${#inputs[@]} inputs" >&2

  local tmp; tmp=$(mktemp -d); trap 'rm -rf "$tmp"' RETURN
  local list="$tmp/list.txt"; : > "$list"
  local i=0
  for f in "${inputs[@]}"; do
    local seg="$tmp/norm_${i}.mp4"
    local vf="scale=${W}:${H}:force_original_aspect_ratio=decrease,pad=${W}:${H}:(ow-iw)/2:(oh-ih)/2,setsar=1,fps=${FPS},format=yuv420p"
    if have_audio "$f"; then
      ffmpeg -y -i "$f" \
        -filter_complex "[0:v]${vf}[v];[0:a]aresample=48000,aformat=sample_fmts=fltp:channel_layouts=stereo[a]" \
        -map "[v]" -map "[a]" -c:v libx264 -crf 18 -preset veryfast -c:a aac -ar 48000 -ac 2 "$seg"
    else
      ffmpeg -y -i "$f" -f lavfi -i anullsrc=channel_layout=stereo:sample_rate=48000 \
        -filter_complex "[0:v]${vf}[v]" \
        -map "[v]" -map 1:a -shortest -c:v libx264 -crf 18 -preset veryfast -c:a aac -ar 48000 -ac 2 "$seg"
    fi
    echo "file '$seg'" >> "$list"
    i=$((i+1))
  done
  # all segments now share codec/params → concat demuxer with stream copy
  ffmpeg -y -f concat -safe 0 -i "$list" -c copy -movflags +faststart "$out"
  echo "[concat] wrote $out" >&2
}

cmd_mixaudio() {
  local video="" music="" out="" vol="0.12" duck="0"
  while [ $# -gt 0 ]; do case "$1" in
    --video) video="$2"; shift 2;; --music) music="$2"; shift 2;; --output) out="$2"; shift 2;;
    --music-volume) vol="$2"; shift 2;; --duck) duck="1"; shift;; *) die "mixaudio: unknown arg $1";; esac; done
  [ -n "$video" ] && [ -n "$music" ] && [ -n "$out" ] || die "mixaudio needs --video --music --output"
  [ -f "$video" ] || die "no such file: $video"; [ -f "$music" ] || die "no such file: $music"
  have_audio "$video" || die "mixaudio: --video has no audio track to mix under (use overlay/concat instead)"

  local dur fout; dur=$(duration "$video"); fout=$(awk -v d="$dur" 'BEGIN{printf "%.3f", (d-2>0)?d-2:0}')
  local fc
  if [ "$duck" = "1" ]; then
    # compress the music whenever the voiceover is loud, then mix
    fc="[1:a]volume=${vol},afade=t=in:st=0:d=1,afade=t=out:st=${fout}:d=2[m];[m][0:a]sidechaincompress=threshold=0.03:ratio=8:attack=20:release=300[duckm];[0:a][duckm]amix=inputs=2:duration=first:dropout_transition=0[aout]"
    echo "[mixaudio] ducking music (vol=${vol}) under voiceover, ${dur}s" >&2
  else
    fc="[1:a]volume=${vol},afade=t=in:st=0:d=1,afade=t=out:st=${fout}:d=2[m];[0:a][m]amix=inputs=2:duration=first:dropout_transition=0[aout]"
    echo "[mixaudio] mixing music bed (vol=${vol}) under voiceover, ${dur}s" >&2
  fi
  # loop music so short beds cover the whole video; keep video untouched
  ffmpeg -y -i "$video" -stream_loop -1 -i "$music" \
    -filter_complex "$fc" -map 0:v -map "[aout]" \
    -c:v copy -c:a aac -ar 48000 -ac 2 -shortest -movflags +faststart "$out"
  echo "[mixaudio] wrote $out" >&2
}

sub="${1:-}"; shift || true
case "$sub" in
  overlay) cmd_overlay "$@";;
  concat)  cmd_concat "$@";;
  mixaudio) cmd_mixaudio "$@";;
  ""|-h|--help|help)
    cat >&2 <<'EOF'
composite.sh <subcommand>
  overlay  --base B --overlay O --output OUT [--x 0 --y 0] [--start S --duration D]
  concat   --output OUT  IN1 IN2 [IN3 ...]
  mixaudio --video V --music M --output OUT [--music-volume 0.12] [--duck]
EOF
    ;;
  *) die "unknown subcommand: $sub (try overlay|concat|mixaudio)";;
esac

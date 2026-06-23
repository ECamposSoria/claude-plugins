#!/usr/bin/env bash
# check-usage.sh — decide whether gpt-5.5 still has quota, else fall back to spark.
#
# Codex meters premium-model usage (gpt-5.5) against a single shared "codex" pool;
# gpt-5.3-codex-spark is the always-available fallback that does NOT draw it down.
# Policy: use gpt-5.5 until that pool is exhausted, then switch to spark.
#
# Reads the freshest rate-limit snapshot Codex wrote to disk
# (~/.codex/sessions/**/rollout-*.jsonl) — zero cost, no quota spent. Each Codex API
# turn records a `token_count` event with `rate_limits`:
#   primary   = rolling 5h window   (window_minutes 300)
#   secondary = rolling weekly window (window_minutes 10080)
# both as `used_percent` (0-100), plus `rate_limit_reached_type` (non-null once hit).
#
# This is only a PRE-CHECK to skip a doomed gpt-5.5 attempt. It can't be perfectly
# fresh, so the review subagent ALSO falls back at run time if gpt-5.5 returns a
# usage/rate-limit error (see SKILL.md) — that runtime signal is authoritative.
#
# Tunable: EXHAUSTED_AT_USED_PERCENT — used% at/above which gpt-5.5 is treated as
#          out of quota. Default 99 (i.e. essentially maxed). Override:
#          EXHAUSTED_AT_USED_PERCENT=95 ./check-usage.sh
#
# Output: human block on stderr + one machine line on stdout:
#   MODEL=<gpt-5.5|gpt-5.3-codex-spark> EFFORT=xhigh PRIMARY_USED=.. SECONDARY_USED=.. REACHED=<type|none> AGE_MIN=..
# Exit 0 on success; exit 3 if no snapshot found (caller should just start with gpt-5.5).

set -euo pipefail

EXHAUSTED_AT="${EXHAUSTED_AT_USED_PERCENT:-99}"
SESS_DIR="${CODEX_HOME:-$HOME/.codex}/sessions"

python3 - "$SESS_DIR" "$EXHAUSTED_AT" <<'PY'
import json, os, sys, time, glob

sess_dir, exhausted_at = sys.argv[1], float(sys.argv[2])

# Most recent rate_limits record across all rollout files (newest first).
files = sorted(glob.glob(os.path.join(sess_dir, "**", "rollout-*.jsonl"), recursive=True),
               key=lambda p: os.path.getmtime(p), reverse=True)

rec = ts = None
for f in files[:200]:
    last = None
    try:
        with open(f) as fh:
            for line in fh:
                if '"rate_limits"' in line:
                    last = line
    except OSError:
        continue
    if last:
        o = json.loads(last)
        rl = o.get("payload", {}).get("rate_limits") or o.get("rate_limits")
        if rl:
            rec, ts = rl, o.get("timestamp")
            break

if not rec:
    sys.stderr.write("codex-usage: no rate_limit snapshot found — starting with gpt-5.5.\n")
    sys.exit(3)

prim = (rec.get("primary") or {}).get("used_percent")
sec  = (rec.get("secondary") or {}).get("used_percent")
prim = 0.0 if prim is None else float(prim)
sec  = 0.0 if sec  is None else float(sec)
reached = rec.get("rate_limit_reached_type")
plan = rec.get("plan_type") or "?"
worst = max(prim, sec)

age_min = -1.0
if ts:
    try:
        t = time.mktime(time.strptime(ts.split(".")[0], "%Y-%m-%dT%H:%M:%S"))
        age_min = max(0.0, (time.time() - t) / 60.0)
    except Exception:
        pass

exhausted = bool(reached) or worst >= exhausted_at
if exhausted:
    model = "gpt-5.3-codex-spark"
    why = (f"gpt-5.5 quota exhausted (reached_type={reached})" if reached
           else f"gpt-5.5 pool at {worst:.0f}% used (>= {exhausted_at:.0f}%)") + " — falling back to spark"
else:
    model = "gpt-5.5"
    why = f"gpt-5.5 pool at {worst:.0f}% used ({100-worst:.0f}% left) — using gpt-5.5"

sys.stderr.write(
    f"Codex usage (plan={plan}, snapshot age ~{age_min:.0f} min, reached={reached or 'none'}):\n"
    f"  5h window      : {prim:.0f}% used  ({100-prim:.0f}% left)\n"
    f"  weekly window  : {sec:.0f}% used  ({100-sec:.0f}% left)\n"
    f"  -> {model} xhigh — {why}\n"
)
if age_min > 45 and not exhausted:
    sys.stderr.write("  (note: snapshot is stale; if gpt-5.5 returns a rate-limit error, fall back to spark.)\n")

print(f"MODEL={model} EFFORT=xhigh PRIMARY_USED={prim:.0f} SECONDARY_USED={sec:.0f} "
      f"REACHED={reached or 'none'} AGE_MIN={age_min:.0f} PLAN={plan}")
PY

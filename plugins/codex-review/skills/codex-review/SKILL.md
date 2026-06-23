---
name: codex-review
description: >-
  Loop a Codex code review over the local commit(s) you just made until Codex confirms
  they are good to go. Spawns a dedicated Claude subagent whose ONLY job is to run
  `codex exec review` on the local commit and relay the verdict verbatim; if Codex flags
  issues, fix them, re-commit, and re-review — repeating until Codex approves. Use this
  whenever the user says "codex review", "/codex-review", "have codex review/check my
  commit", "run a codex review", "get codex's sign-off / second opinion", or otherwise
  wants Codex to vet local commits before pushing or merging. The final call stays with
  Claude: Claude may override Codex — accept the commit despite a flagged issue, or keep
  iterating despite a GOOD — when Codex lacked full context, but MUST tell the user.
---

# Codex Review

## Goal (do not drop this until it's met)

**Keep going until you have a clear confirmation that the local commit is good to go.**
A run of this skill is only finished when one of these is true:

1. Codex returns a clean **GOOD** verdict (no actionable findings), or
2. You (Claude) make a deliberate, justified override — see [The final call is yours](#the-final-call-is-yours).

Do not stop at the first round of findings, do not hand back a half-finished loop, and do
not declare success on your own opinion while Codex still has open findings unless you are
explicitly overriding (and saying so). This is a loop, not a single review.

## Why this exists

Codex is a strong, independent second reviewer. Running it in a loop — review → fix →
re-review — catches the regressions a single pass misses, and the iterations tend to
surface *new* issues created by earlier fixes. The point is an adversarial back-and-forth
that converges on a commit both reviewers trust, not a rubber stamp.

You spawn a **separate Claude subagent** to drive Codex (rather than calling it yourself)
for two reasons: it keeps the raw Codex output uncontaminated by your own opinion, and it
isolates the long-running `codex exec` call from your main loop.

## Which model: gpt-5.5 first, fall back to spark only when it runs out

Always run the review on **`gpt-5.5` at `xhigh` reasoning** — the stronger reviewer. Codex
meters gpt-5.5 against a single shared quota pool; **`gpt-5.3-codex-spark` (also `xhigh`) is
the always-available fallback** that does not draw that pool down. So: use gpt-5.5 until its
quota is exhausted, then switch to spark. Don't downgrade early — only when gpt-5.5 actually
runs out.

There are two signals for "gpt-5.5 ran out", and you use both:

1. **Pre-check (cheap, before spawning the subagent).** Run the bundled helper to read the
   freshest usage snapshot Codex wrote to disk (zero cost, no quota spent):

   ```bash
   bash "${CLAUDE_PLUGIN_ROOT}/skills/codex-review/check-usage.sh"
   ```

   It prints a machine line and tells you which model to start with:

   ```
   MODEL=gpt-5.5 EFFORT=xhigh PRIMARY_USED=10 SECONDARY_USED=9 REACHED=none AGE_MIN=5 PLAN=prolite
   ```

   It recommends `gpt-5.5` unless the pool is **exhausted** — either `rate_limit_reached_type`
   is set, or a window is essentially maxed (default ≥99% used; tune with
   `EXHAUSTED_AT_USED_PERCENT=95 bash …/check-usage.sh`). If it can't find a snapshot it
   exits non-zero — just start with gpt-5.5.

2. **Runtime fallback (authoritative).** The disk snapshot can lag, so the review subagent
   **starts on gpt-5.5 and, if Codex returns a usage/rate-limit-reached error, immediately
   re-runs the same review on `gpt-5.3-codex-spark`** and relays that result (noting the
   fallback). This is the source of truth — the pre-check just avoids a doomed first attempt.

Pass the starting `MODEL` + `EFFORT` into every review subagent this run. If a later round
hits the gpt-5.5 limit, stay on spark for the rest of the loop.

## The loop

1. **Scope it.** Work out exactly what Codex should review:
   - The **repo** — the git repository containing the work you just committed (often a
     subdirectory like `platform/<repo>`, not the top-level cwd). `cd` into it.
   - The **branch** — `git rev-parse --abbrev-ref HEAD`.
   - The **review target**, in priority order:
     - If the user named a base or commit, use it.
     - Else if the branch was cut from a clear base branch, review the whole branch diff
       vs that base (this covers *all* the session's commits, which is usually what "the
       local commit" means). Find it via the obvious parent (e.g. the branch you forked
       from) or `git merge-base`.
     - Else review the latest commit(s): `--commit <sha>` for one, or the range since the
       work started.
   - If you genuinely can't tell, ask the user one short question rather than guessing.

2. **Spawn the review subagent** (see [template](#review-subagent-prompt)). It runs Codex
   and returns the verbatim output plus a final `VERDICT: GOOD` or `VERDICT: ISSUES` line.

3. **Read the verdict.**
   - `GOOD` → you're done (unless you disagree and want another pass — your call).
   - `ISSUES` → for each finding, decide: **fix it** (the common case), or **reject it
     with reasoning** (Codex was wrong / lacked context — note it for the user). Apply the
     fixes, add or update tests that lock the fix, run the test suite, and **commit**.

4. **Re-review.** Spawn a fresh review subagent on the updated commit(s). Codex commonly
   raises *new* findings as the diff evolves — that's expected and good. Keep looping.

5. **Stop** only when the goal above is met. Then summarize for the user: how many rounds,
   what each round found, what you changed, and any findings you overrode (with why).

## The final call is yours

Codex is an advisor, not the gate. **You** decide whether the commit is good to go. Two
override directions, both of which you must surface to the user explicitly:

- **Accept despite `ISSUES`.** If a Codex finding is wrong, already handled, out of scope,
  or based on missing context (it can't run the app, doesn't see a related file, etc.),
  you may declare the commit good. Tell the user plainly: *"Codex flagged X; I'm overriding
  because Y."* Don't silently drop a finding — name it and justify it.
- **Keep going despite `GOOD`.** If Codex approves but you can see it missed something
  (didn't have the full picture, reviewed the wrong scope, skipped a file), say so and
  do another round or fix it yourself.

When you override, prefer to also give Codex the missing context on the next pass (a richer
review prompt, the right base/scope, a pointer to the related file) so its verdict becomes
trustworthy rather than just dismissed.

## Review subagent prompt

Spawn a `general-purpose` subagent (it has Bash) with a task like the following. Fill in
the repo path, branch, base/commit, the **model + effort** picked above, and a short
description of what the commits do and what to focus on. The subagent's job is to run Codex
and relay — **not** to review the code itself or edit anything.

```
Your ONLY job is to run the Codex CLI to review my local commit(s) and report its verdict
verbatim. Do NOT review the code yourself, do NOT edit anything, do NOT commit. Just run
codex and relay its output.

Context: <1-3 sentences: what the commits change, and — if this is a re-review — what the
previous round flagged and what was just fixed, so you can confirm it's resolved>.

Run the review on <MODEL> at <EFFORT> reasoning (e.g. gpt-5.5 / xhigh). If <MODEL> is
gpt-5.5 and Codex says its usage/rate limit is reached, fall back to gpt-5.3-codex-spark.

Steps:
1. cd <absolute path to the repo>
2. Confirm the branch (git rev-parse --abbrev-ref HEAD) and show the commits under review
   (e.g. `git log --oneline <base>..HEAD`).
3. Run a NON-INTERACTIVE Codex review of those changes on the chosen model/effort. Prefer
   reviewing the whole branch vs its base:

     codex review --base <base-branch> -c model="<MODEL>" -c model_reasoning_effort="<EFFORT>"

   IMPORTANT codex quirks (v0.140.x):
   - `codex review` is the non-interactive review subcommand (`codex exec review` also works).
   - `-c model="gpt-5.5"` selects the model; `-c model_reasoning_effort="xhigh"` sets effort.
     Pass BOTH exactly as given to you — do not substitute your own model.
   - `--base <branch>` CANNOT be combined with a custom prompt argument — run it WITHOUT a
     prompt. To review just one commit instead, use:
       `codex review --commit <sha> -c model="<MODEL>" -c model_reasoning_effort="<EFFORT>"`
     (a prompt argument is allowed in that form).
   - It must run on its own and exit; use a large timeout (e.g. 600000 ms).
   - If it errors about sandbox/approval, retry once adding `-c sandbox_mode=read-only -c
     approval_policy=never`; if still blocked, `--dangerously-bypass-approvals-and-sandbox`.
   - If `--base` is rejected, fall back to
     `codex review --commit $(git rev-parse HEAD) -c model="<MODEL>" -c model_reasoning_effort="<EFFORT>"`.
4. USAGE FALLBACK: if you started on gpt-5.5 and the command fails because gpt-5.5's
   usage/rate limit is reached (output mentions "usage limit", "rate limit", "limit reached",
   a 429, or it nudges you to switch models), DO NOT give up — re-run the exact same review
   command with `-c model="gpt-5.3-codex-spark"` (keep `-c model_reasoning_effort="xhigh"`),
   and report that you fell back plus why. (A sandbox/approval error is NOT a usage limit —
   handle that per step 3, don't switch models for it.)
5. Return to me, in full:
   - The exact codex command(s) you ran (including the model/effort flags), and — if you fell
     back — both commands and the gpt-5.5 limit message that triggered the switch.
   - Codex's COMPLETE review output, verbatim — every finding, or its statement that there
     are none. Do not summarize away findings.
   - A final line, exactly `VERDICT: GOOD` if Codex reported no actionable issues / approved,
     or `VERDICT: ISSUES` if it raised ANY concern, bug, or change request. Base this strictly
     on what Codex said, not your own judgment.
```

## Notes & gotchas

- **`codex` must be installed** (`which codex`). It's the Codex CLI; `codex review` runs a
  non-interactive repo code review (`codex exec review` is the older equivalent). Check
  `codex review --help` if the flags differ in the installed version.
- **Model: gpt-5.5 first, spark when it runs out.** Always start on `gpt-5.5 xhigh`; only
  drop to `gpt-5.3-codex-spark xhigh` when gpt-5.5's quota is exhausted — detected by the
  `check-usage.sh` pre-check and, authoritatively, by the subagent's runtime rate-limit
  fallback. Never hard-code one model or downgrade gpt-5.5 early.
- **Root-owned `node_modules` / sandbox**: Codex may need write access to a temp dir to run
  the project's tests. The non-interactive flags above (`approval_policy=never`, full or
  read-only sandbox) usually suffice; the subagent can escalate sandbox if Codex asks.
- **Don't combine reviewers' opinions in the relay.** The subagent returns Codex verbatim;
  *you* do the judging in the main loop. That separation is what keeps the verdict honest.
- **Each round ends in a commit.** Re-review the committed state, not the dirty tree, so the
  verdict maps to a real commit the user can push.
- **Leave unrelated dirty files alone.** Only stage what your fixes touched.

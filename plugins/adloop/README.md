# adloop (Claude Code plugin)

Google Ads + GA4 from your IDE via the [AdLoop](https://github.com/kLOsk/adloop) MCP server.

43 tools for reads, writes, cross-reference analysis (Ads ↔ GA4), tracking validation, and budget planning — with dry-run-by-default, budget caps, and Broad Match + Manual CPC protection.

## What this plugin ships

- `.mcp.json` — stdio transport pointing at the adloop MCP server in `~/.adloop/venv/bin/python -m adloop`
- `commands/` — 6 slash commands from upstream:
  - `/analyze-performance` · `/create-ad` · `/diagnose-tracking`
  - `/optimize-campaign` · `/create-campaign` · `/budget-plan`
- `skills/adloop/SKILL.md` — upstream orchestration rules (GAQL reference, safety protocols, workflow patterns) wrapped as a discoverable skill that triggers on Google Ads / GA4 language

No secrets are stored in the plugin. OAuth credentials and the developer token live in `~/.adloop/` on your machine.

## One-time setup

This plugin assumes you've already:

1. Installed adloop in a dedicated venv:
   ```bash
   python3 -m venv ~/.adloop/venv
   ~/.adloop/venv/bin/pip install adloop
   ```
2. Placed your Google OAuth Desktop client JSON at `~/.adloop/credentials.json` (mode `0600`).
3. Run `~/.adloop/venv/bin/adloop init` — the wizard asks for:
   - **Google Ads Developer Token** — from your MCC → Tools & Settings → API Center
   - **MCC Account ID** — 10-digit number, top bar of the MCC UI (e.g. `298-496-7978`)
   - **OAuth sign-in** — opens a browser (or prints a URL for headless servers)
   - **GA4 property + Ads customer** — auto-discovered
   - **Safety caps** — max daily budget, dry-run default

Config ends up at `~/.adloop/config.yaml`. Token at `~/.adloop/token.json`.

### Developer token access levels

New developer tokens start at "Test Account" level and can't touch production accounts — you'll see `DEVELOPER_TOKEN_NOT_APPROVED`. Make one API call with a production customer, wait for Explorer access (2,880 ops/day), or apply for Basic (15,000 ops/day) from the same API Center page.

### Headless VM

`adloop init` detects no-browser environments and falls back to a manual flow: it prints the authorization URL, you open it on any machine, and paste the redirect URL back into the terminal.

## Using it

After install, relaunch Claude Code. Verify with `/mcp` (adloop should be listed) and try:

- *"Run a health check on adloop."*
- *"How did my campaigns perform last week?"*
- *"Which search terms are wasting budget?"*
- *"Draft a responsive search ad for the macregala main campaign."* (will stay PAUSED until `confirm_and_apply` with `dry_run=false`)

The bundled `adloop` skill loads automatically when you mention Google Ads / GA4 — it carries the orchestration playbook so Claude knows which tools to chain for common workflows.

## Safety model (enforced by the server, not Claude)

- Writes return a preview first; a separate `confirm_and_apply` executes.
- `confirm_and_apply` defaults to `dry_run=true`. Real changes need `dry_run=false` explicitly.
- Budget cap (`safety.max_daily_budget` in config) is server-enforced.
- Every op (including dry runs) appended to `~/.adloop/audit.log`.
- New campaigns and ads ship PAUSED.
- BROAD match on non-Smart-Bidding campaigns is blocked before the API call.

## Multi-account (altometodo / macgroup / unitevirtual / macregala)

adloop's config is single-customer. The `login_customer_id` (your MCC) stays constant; the active `ads.customer_id` and `ga4.property_id` switch per brand. Simplest pattern: run `adloop init` for macregala first, then swap the two IDs in `~/.adloop/config.yaml` when working on a different brand. If you find yourself switching often, open an issue upstream or script a config-swap alias.

## Troubleshooting

| Symptom | Fix |
|--------|-----|
| `/mcp` doesn't show `adloop` | Check `/home/eze/.adloop/venv/bin/python -m adloop` runs without error. Plugin enabled? |
| OAuth token keeps expiring weekly | Publish the GCP consent screen from "Testing" to "In production". |
| `DEVELOPER_TOKEN_NOT_APPROVED` | Token still at "Test Account" level — see access-levels note above. |
| Built-in credentials blocked | Not applicable — this plugin uses your custom credentials at `~/.adloop/credentials.json`. |

## Upgrades

```bash
~/.adloop/venv/bin/pip install -U adloop
```

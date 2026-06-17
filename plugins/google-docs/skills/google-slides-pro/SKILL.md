---
name: google-slides-pro
description: "Use whenever the user wants to create or update a Google Slides presentation. Triggers include any mention of 'google slides', 'google presentation', 'slide deck in google', 'gslides', or requests to produce a slide deck intended to live in Google Drive / Google Slides. Workflow is hybrid: generate a .pptx locally with the pptx skill, then upload to Drive where it can be opened/converted to Google Slides. Do NOT use for local-only .pptx files without Drive handoff (use the pptx skill directly) or for Google Docs / Sheets."
version: 1.0.0
allowed-tools: mcp__plugin_google-docs_google-docs__listDriveFiles, mcp__plugin_google-docs_google-docs__searchDriveFiles, mcp__plugin_google-docs_google-docs__createFolder, mcp__plugin_google-docs_google-docs__getFolderInfo, mcp__plugin_google-docs_google-docs__listFolderContents, mcp__plugin_google-docs_google-docs__moveFile, mcp__plugin_google-docs_google-docs__renameFile, mcp__plugin_google-docs_google-docs__copyFile, mcp__plugin_google-docs_google-docs__downloadFile, Bash, Read, Write, Edit
---

## Pre-flight: token health check (RUN BEFORE ANYTHING ELSE)

This skill depends on the `google-docs` MCP server, which uses an OAuth refresh token at `~/.config/google-docs-mcp/token.json`. If that token is missing, malformed, or revoked, the MCP fails at session start and **none** of its `mcp__plugin_google-docs_google-docs__*` tools register — every call will fail with "tool not found".

**Step 1 — probe the token + MCP authorization** (single Bash call):

```bash
TOK=~/.config/google-docs-mcp/token.json
([ -f "$TOK" ] && python3 -c "import json,sys;sys.exit(0 if json.load(open('$TOK')).get('refresh_token') else 1)" 2>/dev/null \
  && timeout 8 bash -c '(printf "%s\n" "{\"jsonrpc\":\"2.0\",\"id\":1,\"method\":\"initialize\",\"params\":{\"protocolVersion\":\"2024-11-05\",\"capabilities\":{},\"clientInfo\":{\"name\":\"p\",\"version\":\"0\"}}}";sleep .5)|/home/eze/.nvm/versions/node/v22.22.1/bin/google-docs-mcp 2>&1' \
    | grep -q "Google API client authorized successfully" \
  && echo PREFLIGHT_OK) || echo PREFLIGHT_FAIL
```

**Step 2 — confirm MCP tools are registered in *this* session.** Even with a valid token, the harness only loads the MCP tools at session start. Run `ToolSearch` with `query="select:mcp__plugin_google-docs_google-docs__readDocument"`. If it returns the tool's schema, the MCP is live in this session. If it returns "No matching deferred tools found", treat it as a pre-flight failure.

If both step 1 prints `PREFLIGHT_OK` **and** step 2 finds the tool, proceed to the skill body below.

**Step 3 — if pre-flight fails, run the auth flow:**

```bash
pkill -f 'bin/google-docs-mcp auth' 2>/dev/null; rm -f /tmp/gdocs-auth.log
nohup /home/eze/.nvm/versions/node/v22.22.1/bin/google-docs-mcp auth > /tmp/gdocs-auth.log 2>&1 &
sleep 3; grep -oE 'https://accounts\.google\.com[^ ]+' /tmp/gdocs-auth.log
```

Then:
1. Print the `https://accounts.google.com/...` URL to the user. Ask them to open it, click "Allow", and paste the **full callback URL** back to you (the URL the browser tries to load after consent — looks like `http://localhost:PORT/?state=...&code=...&scope=...`, even though the page itself fails to load because the listener is on the VM's localhost).
2. Deliver the code to the listening server: `curl -sS "<callback-url>" -o /dev/null -w '%{http_code}\n'`. Expect `200`.
3. Confirm: `grep "Authentication successful" /tmp/gdocs-auth.log`.

**Step 4 — STOP and request a session restart.** Tell the user verbatim:

> *Token refreshed. The MCP tool registry is locked at session start, so the new tools won't appear until you restart Claude Code. Please exit and reopen the session, then re-invoke the skill.*

Do **not** attempt any `mcp__plugin_google-docs_google-docs__*` call in the same session as the auth flow — those tools are not registered and will fail.

---

# Google Slides — Hybrid Creation Workflow

**Critical:** the Google Docs MCP server does NOT expose the Google Slides API. There is no `createPresentation`, no `insertSlide`, no `applySlideLayout` tool. So "make me a Google Slides deck" uses a two-step hybrid:

1. Generate a local `.pptx` using the **`pptx` skill** from the `document-skills` plugin (OOXML + html2pptx, full formatting).
2. Upload the `.pptx` to Google Drive and (optionally) convert to native Google Slides format.

This skill orchestrates steps 1 and 2.

## Quick Reference

| Stage | Tool(s) |
|-------|---------|
| Build deck locally | Delegate to `pptx` skill (document-skills) |
| List target folder | `listFolderContents(folderId)` or `searchDriveFiles` |
| Upload `.pptx` to Drive | Python one-liner using Drive API (see below) — MCP has no upload tool |
| Convert PPTX → Google Slides | Re-upload with `mimeType="application/vnd.google-apps.presentation"` (or right-click → Open with Slides in UI) |
| Move / rename in Drive | `moveFile`, `renameFile` |
| Download back as PPTX | `downloadFile(fileId, mimeType="application/vnd.openxmlformats-officedocument.presentationml.presentation")` |

## Step 1 — Build the Deck Locally

Invoke the `pptx` skill via its usual triggers. When operating inside this skill, delegate by describing the deck and letting the `pptx` skill generate it. The output is a validated `.pptx` file at a known path.

**Important choice for cross-compatibility with Google Slides:**

- **Prefer `docx-js`-style / `python-pptx` generation** for body text, bullet lists, tables, charts — these round-trip cleanly into Google Slides.
- **Avoid HTML→PPTX for complex vector graphics** — Slides often rerenders CSS in lossy ways. Keep layouts simple (title + content, two-column, section header, blank).
- **Use standard fonts:** Arial, Calibri, Roboto. Custom fonts drop to a default on Slides.
- **Embed images** rather than linking — Slides can't resolve local file paths after upload.

## Step 2 — Upload to Google Drive

The MCP server has no generic file upload. Two options:

### Option 2A — Python script using the plugin's OAuth creds (automated)

Piggyback on the MCP server's existing OAuth refresh token at `~/.config/google-docs-mcp/token.json` plus the `GOOGLE_CLIENT_ID` / `GOOGLE_CLIENT_SECRET` env vars (exported in `~/.bashrc`).

```bash
pip install --user google-api-python-client google-auth-httplib2
```

```python
# upload_pptx_to_drive.py
import json, os, pathlib, sys
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

TOKEN_PATH = pathlib.Path.home() / ".config" / "google-docs-mcp" / "token.json"
raw = json.loads(TOKEN_PATH.read_text())

# google-docs-mcp stores tokens as {access_token, refresh_token, scope, token_type, expiry_date}
# — NOT the shape Credentials.from_authorized_user_file expects. Construct manually.
scope_val = raw.get("scope") or raw.get("scopes")
scopes = scope_val.split() if isinstance(scope_val, str) else list(scope_val or [])

creds = Credentials(
    token=raw.get("access_token"),
    refresh_token=raw.get("refresh_token"),
    token_uri="https://oauth2.googleapis.com/token",
    client_id=os.environ["GOOGLE_CLIENT_ID"],
    client_secret=os.environ["GOOGLE_CLIENT_SECRET"],
    scopes=scopes,
)

drive = build("drive", "v3", credentials=creds)

local_path = sys.argv[1]                                  # e.g. /tmp/deck.pptx
folder_id  = next((a for a in sys.argv[2:] if not a.startswith("--")), None)
convert    = "--convert" in sys.argv                      # convert to native Slides

body = {"name": pathlib.Path(local_path).name}
if folder_id:
    body["parents"] = [folder_id]
if convert:
    body["mimeType"] = "application/vnd.google-apps.presentation"

media = MediaFileUpload(
    local_path,
    mimetype="application/vnd.openxmlformats-officedocument.presentationml.presentation",
    resumable=True,
)
file = drive.files().create(body=body, media_body=media, fields="id,name,webViewLink").execute()
print(file["webViewLink"])
```

Usage:

```bash
python upload_pptx_to_drive.py /tmp/deck.pptx <folderId> --convert
```

Drive scope requirement: the stored token must already include `https://www.googleapis.com/auth/drive` or `drive.file`. If uploads 403, re-authorize the MCP with the broader scope.

### Option 2B — Manual upload (zero code)

Deliver the `.pptx` path to the user and instruct:

1. Open Drive, drag the `.pptx` into the target folder (or use "New → File upload").
2. Right-click the uploaded file → **Open with → Google Slides**. Drive creates a native Slides copy side-by-side.
3. Optionally delete the original `.pptx` and keep the converted copy.

Fallback to this when the OAuth script path is unavailable or the user prefers not to run scripts.

## Step 3 — Verify and Finalize

After upload:

1. `searchDriveFiles(query="name='<deck name>'")` → confirm the file exists and grab its `fileId`.
2. Move to final folder: `moveFile(fileId, folderId)`.
3. Rename if needed: `renameFile(fileId, newName)`.
4. Return the Drive URL (`webViewLink`) to the user.

## Known Limits

| Limit | Note |
|-------|------|
| No programmatic slide-by-slide edits in Slides | All deck composition happens in the `.pptx` step. To edit an existing Google Slides deck, download → edit locally → re-upload. |
| No speaker-notes read/write | Same — handled inside the `.pptx`. |
| No real-time collaboration triggers | Use `addComment` on the Drive file for async feedback (works on any Drive-hosted file). |
| Fonts may substitute on conversion | Stick to web-safe + Google Fonts defaults (Arial, Roboto, Open Sans). |

## Upgrade Path

If this hybrid gets painful, swap in a broader MCP server that natively implements the Slides API (candidates: `mcp-google-workspace` or similar community servers covering Docs + Sheets + Slides + Drive in one). Replace `command` in `.mcp.json`, keep OAuth, and this skill's "Step 2" becomes direct MCP calls.

## Best Practices

- **Build once locally, upload once.** Don't iterate by re-uploading — fix the `.pptx` generator instead.
- **Use landscape 16:9 by default** (pptx skill has a switch). Google Slides' default is 16:9; 4:3 looks dated.
- **Name the file meaningfully before upload.** Renames in Drive don't propagate to the slide master's internal title.
- **If the user will present from Slides,** skip heavy transitions and video embeds — they often break on conversion.

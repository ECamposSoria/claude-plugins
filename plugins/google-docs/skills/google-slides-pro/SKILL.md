---
name: google-slides-pro
description: "Use whenever the user wants to create or update a Google Slides presentation. Triggers include any mention of 'google slides', 'google presentation', 'slide deck in google', 'gslides', or requests to produce a slide deck intended to live in Google Drive / Google Slides. Workflow is hybrid: generate a .pptx locally with the pptx skill, then upload to Drive where it can be opened/converted to Google Slides. Do NOT use for local-only .pptx files without Drive handoff (use the pptx skill directly) or for Google Docs / Sheets."
version: 1.0.0
allowed-tools: mcp__plugin_google-docs_google-docs__listDriveFiles, mcp__plugin_google-docs_google-docs__searchDriveFiles, mcp__plugin_google-docs_google-docs__createFolder, mcp__plugin_google-docs_google-docs__getFolderInfo, mcp__plugin_google-docs_google-docs__listFolderContents, mcp__plugin_google-docs_google-docs__moveFile, mcp__plugin_google-docs_google-docs__renameFile, mcp__plugin_google-docs_google-docs__copyFile, mcp__plugin_google-docs_google-docs__downloadFile, Bash, Read, Write, Edit
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

The plugin config at `~/.claude/plugins/cache/eze-claude-plugins/google-docs/1.0.0/.mcp.json` holds `GOOGLE_CLIENT_ID` / `GOOGLE_CLIENT_SECRET`. The MCP server already maintains a refresh token for the authorized account. Piggyback on it by running a short script that reads the stored token and uses `google-api-python-client`:

```bash
pip install --user google-api-python-client google-auth-httplib2 google-auth-oauthlib
```

```python
# upload_pptx_to_drive.py
import sys, json, pathlib
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from google.oauth2.credentials import Credentials

# The google-docs-mcp server stores its token at ~/.config/google-docs-mcp/token.json
# (path may vary; check the MCP server's source if not there).
TOKEN_PATH = pathlib.Path.home() / ".config" / "google-docs-mcp" / "token.json"
creds = Credentials.from_authorized_user_file(str(TOKEN_PATH),
    ["https://www.googleapis.com/auth/drive.file"])

drive = build("drive", "v3", credentials=creds)

local_path = sys.argv[1]                                  # e.g. /tmp/deck.pptx
folder_id  = sys.argv[2] if len(sys.argv) > 2 else None   # optional parent folder
convert    = "--convert" in sys.argv                      # convert to native Slides

body = {"name": pathlib.Path(local_path).name}
if folder_id:
    body["parents"] = [folder_id]
if convert:
    body["mimeType"] = "application/vnd.google-apps.presentation"  # triggers conversion

media = MediaFileUpload(local_path,
    mimetype="application/vnd.openxmlformats-officedocument.presentationml.presentation",
    resumable=True)

file = drive.files().create(body=body, media_body=media, fields="id,name,webViewLink").execute()
print(file["webViewLink"])
```

Usage:

```bash
python upload_pptx_to_drive.py /tmp/deck.pptx <folderId> --convert
```

**Token path caveat:** the exact path depends on how `google-docs-mcp` stores tokens. If `~/.config/google-docs-mcp/token.json` doesn't exist, `find ~ -name "token.json" 2>/dev/null | grep -i google` to locate it before hard-coding.

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

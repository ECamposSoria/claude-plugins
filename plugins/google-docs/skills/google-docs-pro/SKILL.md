---
name: google-docs-pro
description: "Use whenever the user wants to create, read, edit, or structure a Google Doc (not a .docx file). Triggers include any mention of 'google doc', 'google docs', 'gdoc', or requests to produce polished documents in Google Docs with headings, tables of contents, tables, images, page breaks, comments, find/replace, or tracked-change-style edits. Also use for reports, memos, letters, templates, or policy documents that live in Google Docs. Do NOT use for .docx files on disk (use the docx skill in document-skills), for class transcript knowledge-base entries (use the class-notes skill), or for Google Sheets/Slides."
version: 1.0.0
allowed-tools: mcp__plugin_google-docs_google-docs__createDocument, mcp__plugin_google-docs_google-docs__readDocument, mcp__plugin_google-docs_google-docs__getDocumentInfo, mcp__plugin_google-docs_google-docs__appendMarkdown, mcp__plugin_google-docs_google-docs__appendText, mcp__plugin_google-docs_google-docs__replaceDocumentWithMarkdown, mcp__plugin_google-docs_google-docs__replaceRangeWithMarkdown, mcp__plugin_google-docs_google-docs__insertText, mcp__plugin_google-docs_google-docs__modifyText, mcp__plugin_google-docs_google-docs__findAndReplace, mcp__plugin_google-docs_google-docs__deleteRange, mcp__plugin_google-docs_google-docs__applyParagraphStyle, mcp__plugin_google-docs_google-docs__applyTextStyle, mcp__plugin_google-docs_google-docs__copyFormatting, mcp__plugin_google-docs_google-docs__insertImage, mcp__plugin_google-docs_google-docs__insertTable, mcp__plugin_google-docs_google-docs__insertTableWithData, mcp__plugin_google-docs_google-docs__getTable, mcp__plugin_google-docs_google-docs__listTables, mcp__plugin_google-docs_google-docs__updateTableRange, mcp__plugin_google-docs_google-docs__deleteTable, mcp__plugin_google-docs_google-docs__insertPageBreak, mcp__plugin_google-docs_google-docs__addTab, mcp__plugin_google-docs_google-docs__listTabs, mcp__plugin_google-docs_google-docs__renameTab, mcp__plugin_google-docs_google-docs__addComment, mcp__plugin_google-docs_google-docs__listComments, mcp__plugin_google-docs_google-docs__getComment, mcp__plugin_google-docs_google-docs__replyToComment, mcp__plugin_google-docs_google-docs__resolveComment, mcp__plugin_google-docs_google-docs__deleteComment, mcp__plugin_google-docs_google-docs__moveFile, mcp__plugin_google-docs_google-docs__copyFile, mcp__plugin_google-docs_google-docs__renameFile
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

# Google Docs — Professional Creation & Editing

Port of the `docx` skill's polish patterns to **Google Docs** via the MCP toolset. The target is a Google Doc (Drive-hosted), never a local `.docx` file.

## Quick Reference

| Task | Tool(s) |
|------|---------|
| Create new doc | `createDocument` → returns `documentId` |
| Bulk-write structured content | `appendMarkdown` (fastest for new docs with headings/lists/tables) |
| Precise insert at index | `insertText` + `applyParagraphStyle` / `applyTextStyle` |
| Find & replace | `findAndReplace` |
| Edit existing text | `modifyText` (matches text) or `deleteRange` + `insertText` |
| Images | `insertImage` (accepts URL or drive file id) |
| Tables | `insertTableWithData` (prefer over bare `insertTable`) |
| Page break | `insertPageBreak` |
| Comments / replies | `addComment`, `replyToComment`, `resolveComment` |
| Read / inspect | `readDocument`, `getDocumentInfo` |
| Move to folder | `moveFile` (after creation, by `documentId`) |

## Creating a New Document

1. `createDocument(title)` → keep the returned `documentId`.
2. **Fastest path — markdown dump:** call `appendMarkdown(documentId, markdown)` with a complete markdown body. It handles headings, bold/italic, lists, tables, links, code. Use this for 80% of create-from-scratch requests.
3. **Precise path — atomic operations:** when you need exact indices or non-markdown constructs (images from URL, multi-column, specific styles on existing text), use `insertText` + `applyParagraphStyle` / `applyTextStyle` per block.
4. Place the doc in a folder: `moveFile(fileId=documentId, folderId=...)`.

### Structure conventions

- **Headings:** use `HEADING_1` for the doc title line (first), `HEADING_2` for sections, `HEADING_3` for subsections. Never skip levels. Apply via `applyParagraphStyle(namedStyleType="HEADING_2", ...)`.
- **Body font:** Google Docs defaults to Arial 11pt — leave it unless the user specifies. If asked for a "report" feel, use `applyTextStyle` to set font family Arial and size 11 for body, 14 for H2, 18 for H1.
- **Lists:** write `- item` or `1. item` in markdown and pass through `appendMarkdown`. Do not insert unicode bullets (`•`, `◦`) as raw characters.
- **Smart quotes:** Google Docs auto-substitutes when the doc has "Smart quotes" on (default). No manual entity encoding needed.

### Tables

- `insertTableWithData(documentId, index, rows, headerStyle=bold)` is the one-shot primitive. Header row gets `applyTextStyle(bold=true)`.
- For widths: Docs auto-fits by default. To force column widths use `setColumnWidths` (sheets tool, not docs) — **not available for Docs tables**; document as a known limit.

### Images

- `insertImage(documentId, index, uri, width, height)`. `uri` can be an external URL or a Drive file id.
- Always pass width/height (in points); without them the image renders at the original pixel size which is often huge.

### Page Breaks & Sections

- `insertPageBreak(documentId, index)` between major sections.
- Google Docs has no "section break with different headers" like Word. Known gap.

## Editing an Existing Document

1. `readDocument(documentId, format="markdown")` to get current content + indices.
2. Decide:
   - **Small surgical edit** → `modifyText(textToMatch, newText)` or `findAndReplace`.
   - **Replace a region** → `replaceRangeWithMarkdown(documentId, startIndex, endIndex, markdown)`.
   - **Full rewrite** → `replaceDocumentWithMarkdown(documentId, markdown)`.
3. For reformatting (bold, color, link) on existing text: `applyTextStyle` with the text match.

### Comments (code-review-style feedback)

```
addComment(documentId, anchorText, commentText)
replyToComment(documentId, commentId, replyText)
resolveComment(documentId, commentId)
```

Use `anchorText` (an exact string in the doc) rather than indices — it's resilient to later edits.

## Known Gaps & Workarounds

The Google Docs MCP surface does NOT currently expose:

| Missing | Workaround |
|---------|------------|
| **Tracked changes / Suggesting mode** | Use comments to flag proposed edits: `addComment(anchorText, "SUGGEST: change X → Y because...")`. For deletions, `applyTextStyle(strikethrough=true, foregroundColor="RED")` on the target range and insert the replacement in green. The user then manually accepts/rejects. |
| **Automatic Table of Contents** | Generate manually: read headings (scan output of `readDocument`), build a bulleted list of H1/H2 lines with `→ page N` placeholders, insert at top with an H1 "Contents" above. Or tell the user: "Insert → Table of contents" in the UI after you hand off. |
| **Headers / footers / page numbers** | Not exposed. For recurring content, place it at the top/bottom of the body via `appendMarkdown`. For true headers/footers, tell the user: "Insert → Headers & footers" in the UI. |
| **Footnotes** | Not exposed. Use superscript numbers in-line (`applyTextStyle(baselineOffset="SUPERSCRIPT")`) and an "Endnotes" H2 section at the bottom with numbered entries. |
| **Section breaks with different orientation / margins** | Not exposed. Document as a hard limit. |

## Best Practices

- **Always read first for edits.** Never `replaceDocumentWithMarkdown` without first `readDocument` — you may clobber user-authored content.
- **Batch logical writes.** One `appendMarkdown` with the full body beats 20 `insertText` calls (avoids index drift).
- **Tabs (multi-tab docs).** `listTabs` first; if the doc has tabs and the user didn't specify one, ask. Don't default to tab 0 silently.
- **Links.** `applyTextStyle(link={url: "..."})` after inserting the text — don't embed `[text](url)` markdown inside `insertText` (it won't resolve).
- **Tracked-change handoff.** When using the comment-based workaround, produce a summary comment at the top: `"Claude proposed N edits. Search for 'SUGGEST:' to review."`

## Conversion & Export

- Export to `.docx` / `.pdf` / `.html`: use `downloadFile(fileId=documentId, mimeType="application/vnd.openxmlformats-officedocument.wordprocessingml.document")` (or `application/pdf`).
- Copy a doc as template: `copyFile(fileId=templateId, name="New Name")` → returns new `documentId` to edit.

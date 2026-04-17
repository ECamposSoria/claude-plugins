---
name: class-notes
description: Append structured class notes to a Google Doc knowledge base from a class transcript. Use when the user provides a class transcript (or audio/text) and wants the notes added to an existing Google Doc in the "knowledge base" format (numbered topics with Definición/Intuición/Ejemplo, refinements injected inline, matching visual design). Triggers on phrases like "add class notes to this doc", "take notes from this transcript", "notes of the class".
version: 1.0.0
argument-hint: [google-doc-url-or-id] + class transcript
allowed-tools: mcp__plugin_google-docs_google-docs__readDocument, mcp__plugin_google-docs_google-docs__appendMarkdown, mcp__plugin_google-docs_google-docs__findAndReplace, mcp__plugin_google-docs_google-docs__deleteRange, mcp__plugin_google-docs_google-docs__applyParagraphStyle, mcp__plugin_google-docs_google-docs__applyTextStyle, Bash, Read, Write
---

# Class Notes Knowledge Base Skill

This skill appends class notes to an existing Google Doc that uses the "Knowledge Base" format: a numbered list of topics, each with **Definición / Intuición / Ejemplo**, where refinements of previously-covered topics are injected **inline** into the original topic (not as a separate section).

## When to use

Invoke when the user:
- Provides a class transcript (text or audio) AND a Google Doc URL/ID
- Says something like "add these class notes to my doc", "take notes from this class", "process this transcript and update the knowledge base"
- Wants to enrich previous topics and/or add new topics from a new class

## The knowledge base format

The target doc has this structure:

```
**BLOCKCHAIN Y CRIPTOMONEDAS** (or project title)
Notas de Estudio Estructuradas
<subtitle / class name>

**RESUMEN DE CLASE**
| table with docentes, temas principales, nuevos tópicos, refinamientos, estado |

**NUEVOS TÓPICOS**
*Se identificaron N conceptos técnicos nuevos en esta clase.*

**01. Topic Name**
*[Categoría: X / Y]  [Nivel: Básico|Intermedio|Avanzado]*
**Definición:** <what it is, technical>
**Intuición:** <why it matters, mental model>
**Ejemplo:** <concrete case, real-world>

**02. Next Topic** ... etc.

*Knowledge Base vX.Y – Clase N*
*Próximos temas anticipados: ...*
```

**CRITICAL RULES:**
1. **Refinements are inline, never a separate section.** When a new class enriches a previous topic (e.g. #04), inject the new content directly into that topic's existing Definición / Intuición / Ejemplo. Do NOT create a "REFINAMIENTOS" section.
2. **Seamless flow.** Do not announce class boundaries ("Clase 3 starts here"). The doc is one continuous knowledge base with ever-growing numbered topics.
3. **Numbered topics are cumulative.** If the doc has 30 topics, the new class adds #31, #32, ... following the same template.

## Workflow

### Step 1 – Read the existing doc

```
mcp__plugin_google-docs_google-docs__readDocument(documentId, format="markdown")
```

Extract: the current topic count (last N), the summary table state, and any topics from previous classes that relate to content in the new transcript.

### Step 2 – Analyze the transcript

Identify:
- **New topics** → candidates for new numbered entries (#N+1 onwards)
- **Previously-covered topics that get enriched** → candidates for inline refinement (find them in the existing doc by name)

Be selective. Quality > quantity. 15–25 new topics per class is typical.

### Step 3 – Clean up any test artifacts

If earlier tests left strings like "claude was here", "hello world", delete them via:
```
findAndReplace(findText="...", replaceText="")
```
**Note:** parameter name is `findText`, not `searchText`.

### Step 4 – Update the summary table

Use `findAndReplace` to update:
- Topic count: `"30 conceptos extraídos"` → `"50 conceptos extraídos"`
- Intro line: `"Se identificaron 30 conceptos..."` → `"Se identificaron 50 conceptos..."`
- Refinamientos row if present
- Temas principales (append new subject areas)

### Step 5 – Delete the old footer before appending

The doc's footer (e.g. `Knowledge Base v1.0`, `Próximos temas anticipados:`) is italic + often center-aligned. If you `appendMarkdown` without removing it first, the new content will **inherit the centered italic style**. This is the #1 gotcha of this workflow.

**Fix:** Use `readDocument(format="json")` + a Python helper (see below) to find the footer's index range, then `deleteRange` from the start of the footer to just before the document's trailing newline.

Because JSON output is large, redirect it to a file and parse with Python:

```python
import json
with open('/tmp/doc.json') as f:
    data = json.load(f)
doc = json.loads(data[0]['text'])
content = doc['body']['content']
# Find index of last valid topic's end and footer start
```

### Step 6 – Reset trailing paragraph style

After deleting the footer, the document's trailing paragraph may still carry the old style. Before appending, reset it:

```
applyParagraphStyle(target={startIndex, endIndex}, style={"alignment": "START", "namedStyleType": "NORMAL_TEXT"})
applyTextStyle(target={startIndex, endIndex}, style={"italic": false, "bold": false})
```

### Step 7 – Append new topics via appendMarkdown

Follow the exact template. Use **bold text**, not heading levels (`#`, `##`):

```markdown
**31. Topic Name**

*[Categoría: X]  [Nivel: Intermedio]*

**Definición:** <text>

**Intuición:** <text>

**Ejemplo:** <text>

**32. Next Topic**

...
```

**Notes on formatting:**
- Use `*[Categoría: X]  [Nivel: Y]*` with **two spaces** between brackets (matches original).
- Use `**Definición:** text` (colon inside bold, space outside). The original doc also accepts this.
- Do NOT use `#` headings — use bold text only.
- Separate topics with a single blank line.

### Step 8 – Inject refinements inline

For each previous topic that the new class enriched, use `findAndReplace` targeting a **unique substring** of that topic's existing Definición/Intuición/Ejemplo and extend it:

```
findAndReplace(
  findText="<last sentence of existing Ejemplo, unique across the doc>",
  replaceText="<same last sentence> <new refinement content extending it>"
)
```

The new text will inherit the same paragraph's formatting (regular body text), keeping the refinement seamlessly inline.

**Tip:** Pick findText strings long enough to be unique in the doc (~80+ chars). Shorter strings may match multiple places.

If a topic's title needs updating (e.g. dropping a "(Mención Introductoria)" qualifier), also do that via `findAndReplace`.

### Step 9 – Re-append the footer

```markdown

*Knowledge Base vX.Y – Clase N*

*Próximos temas anticipados: topic1, topic2, topic3*
```

### Step 10 – Apply the visual styles (colors + borders)

The MCP `applyParagraphStyle` tool does NOT expose `borderBottom`, so for the orange underline under each topic title you must call the Google Docs API directly using the saved OAuth token.

**Token location:** `~/.config/google-docs-mcp/token.json`

**Style specifications (from the original doc):**
- Topic title **"NN. "** prefix: bold, orange `#F39C12` (RGB 0.953, 0.612, 0.071), size **13 pt**, Arial
- Topic title rest: bold, dark slate `#2C3E50` (RGB 0.173, 0.243, 0.314), size **13 pt**, Arial
- Topic title paragraph: `spaceAbove 18 pt`, `spaceBelow 6 pt`, `borderBottom` orange 0.5 pt solid, padding 4 pt
- Category line `*[Categoría: X]  [Nivel: Y]*`: italic, green `#1E8449` (RGB 0.118, 0.518, 0.286), size **9 pt**, Arial
- Category line paragraph: `spaceBelow 6 pt`
- Body text (Definición/Intuición/Ejemplo): default normal text, left-aligned

**Reusable Python script** (adapt DOC_ID, token path, and ranges):

```python
import json, urllib.request, urllib.parse, os

# --- Refresh OAuth token ---
with open(os.path.expanduser('~/.config/google-docs-mcp/token.json')) as f:
    token = json.load(f)

CLIENT_ID = "<your-client-id>"
CLIENT_SECRET = "<your-client-secret>"
refresh_data = urllib.parse.urlencode({
    "client_id": CLIENT_ID,
    "client_secret": CLIENT_SECRET,
    "refresh_token": token["refresh_token"],
    "grant_type": "refresh_token",
}).encode()
req = urllib.request.Request("https://oauth2.googleapis.com/token", data=refresh_data, method="POST")
with urllib.request.urlopen(req) as resp:
    access_token = json.loads(resp.read())["access_token"]

# --- Extract topic ranges from the doc JSON ---
# (Use readDocument first and parse the JSON to find title_start, title_end,
#  num_prefix_end, cat_start, cat_end for each new topic)
DOC_ID = "<your-doc-id>"

# Colors (match original doc)
ORANGE     = {"red": 0.9529412, "green": 0.6117647, "blue": 0.07058824}
DARK_SLATE = {"red": 0.17254902, "green": 0.24313726, "blue": 0.3137255}
GREEN      = {"red": 0.11764706, "green": 0.5176471,  "blue": 0.28627452}

requests = []
for t in topics:  # each topic dict has title_start, title_end, num_prefix_end, cat_start, cat_end
    # Title paragraph: spacing + orange bottom border
    requests.append({"updateParagraphStyle": {
        "range": {"startIndex": t["title_start"], "endIndex": t["title_start"] + 1},
        "paragraphStyle": {
            "spaceAbove":   {"magnitude": 18, "unit": "PT"},
            "spaceBelow":   {"magnitude": 6,  "unit": "PT"},
            "borderBottom": {
                "color":    {"color": {"rgbColor": ORANGE}},
                "width":    {"magnitude": 0.5, "unit": "PT"},
                "padding":  {"magnitude": 4,   "unit": "PT"},
                "dashStyle":"SOLID"
            }
        },
        "fields": "spaceAbove,spaceBelow,borderBottom"
    }})
    # "NN. " prefix: orange
    requests.append({"updateTextStyle": {
        "range": {"startIndex": t["title_start"], "endIndex": t["num_prefix_end"]},
        "textStyle": {
            "bold": True, "italic": False,
            "foregroundColor": {"color": {"rgbColor": ORANGE}},
            "fontSize": {"magnitude": 13, "unit": "PT"},
            "weightedFontFamily": {"fontFamily": "Arial", "weight": 400}
        },
        "fields": "bold,italic,foregroundColor,fontSize,weightedFontFamily"
    }})
    # Rest of title: dark slate
    requests.append({"updateTextStyle": {
        "range": {"startIndex": t["num_prefix_end"], "endIndex": t["title_end"]},
        "textStyle": {
            "bold": True, "italic": False,
            "foregroundColor": {"color": {"rgbColor": DARK_SLATE}},
            "fontSize": {"magnitude": 13, "unit": "PT"},
            "weightedFontFamily": {"fontFamily": "Arial", "weight": 400}
        },
        "fields": "bold,italic,foregroundColor,fontSize,weightedFontFamily"
    }})
    # Category line paragraph spacing
    requests.append({"updateParagraphStyle": {
        "range": {"startIndex": t["cat_start"], "endIndex": t["cat_start"] + 1},
        "paragraphStyle": {"spaceBelow": {"magnitude": 6, "unit": "PT"}},
        "fields": "spaceBelow"
    }})
    # Category line text: green italic small
    requests.append({"updateTextStyle": {
        "range": {"startIndex": t["cat_start"], "endIndex": t["cat_end"]},
        "textStyle": {
            "italic": True,
            "foregroundColor": {"color": {"rgbColor": GREEN}},
            "fontSize": {"magnitude": 9, "unit": "PT"},
            "weightedFontFamily": {"fontFamily": "Arial", "weight": 400}
        },
        "fields": "italic,foregroundColor,fontSize,weightedFontFamily"
    }})

body = json.dumps({"requests": requests}).encode()
req = urllib.request.Request(
    f"https://docs.googleapis.com/v1/documents/{DOC_ID}:batchUpdate",
    data=body,
    headers={"Authorization": f"Bearer {access_token}", "Content-Type": "application/json"},
    method="POST"
)
with urllib.request.urlopen(req) as resp:
    print("Applied", len(json.loads(resp.read())["replies"]), "style requests")
```

To build the `topics` list, extract ranges from the doc JSON:

```python
import re
topics = []
for i, elem in enumerate(content):
    if 'paragraph' not in elem:
        continue
    txt = ''.join(r.get('textRun', {}).get('content', '') for r in elem['paragraph'].get('elements', []))
    m = re.match(r'^(\d+)\. (.+?)\n$', txt)
    if m:
        num = int(m.group(1))
        if NEW_RANGE_START <= num <= NEW_RANGE_END:
            start = elem['startIndex']
            end   = elem['endIndex']
            cat_elem = content[i+1]
            cat_start = cat_elem['startIndex']
            cat_end   = cat_elem['endIndex']
            topics.append({
                'num': num,
                'title_start': start,
                'title_end':   end - 1,
                'num_prefix_end': start + len(f'{num}. '),
                'cat_start': cat_start,
                'cat_end':   cat_end - 1,
            })
```

## Gotchas & lessons learned

1. **`appendMarkdown` inherits the previous paragraph's style.** If the last paragraph is italic/centered (common for footers), the new content will be too. Always delete the footer first, reset the trailing paragraph style, then append.
2. **`findAndReplace` parameter is `findText`, not `searchText`.**
3. **`deleteRange` uses integers, not strings, for indices.**
4. **Don't use heading levels (`#`, `##`) in appendMarkdown** — the original doc uses only bold text. Headings create different paragraph styles that don't match.
5. **`readDocument(format="json")` output is huge** — it will exceed the tool's token limit. Let it save to the cached file and parse via `Bash + python3` instead.
6. **`findAndReplace` is plain text** — new text inherits the formatting of the replaced text. Use this to your advantage for inline refinements (target regular body text, get regular body text back).
7. **`applyParagraphStyle` MCP tool does NOT expose `borderBottom`** — use the direct API script above for orange title underlines.
8. **Topic refinements go INSIDE the topics**, never as a separate "REFINAMIENTOS" section. The user will reject any design that separates them.
9. **Two spaces between brackets in category lines** — `[Categoría: X]  [Nivel: Y]` (double space). It's subtle but matches the original.

## Content style guide for topics

Each topic should have:
- **Definición:** 1–3 sentences, technical and precise. Define what the thing IS.
- **Intuición:** 2–4 sentences. Explain WHY it matters, the mental model, and any domain-specific angle (e.g., "For a PM in quant: ...").
- **Ejemplo:** 1–3 sentences with a concrete real-world case, numbers, dates, or named entities.

Tone: pedagogical, confident, slightly informal (the original uses "ustedes", "fíjense", Argentine Spanish).

## Verification

After applying, always re-read the doc (markdown format) and visually check:
- Topic numbering is continuous
- Category lines render italic + green
- Title prefix "NN." renders in orange
- Orange underline appears below each title
- Refinements are embedded in their original topic, not in a separate section
- Footer "Knowledge Base vX.Y" is at the very bottom

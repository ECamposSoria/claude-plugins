---
name: google-sheets-pro
description: "Use whenever the user wants to create, read, edit, or build a Google Sheet (not a .xlsx file). Triggers include any mention of 'google sheet', 'google sheets', 'gsheet', 'spreadsheet in google', or requests to build financial models, dashboards, budgets, data tables, pivot-style summaries, charts, conditional formatting, dropdowns, or formulas in Google Sheets. Do NOT use for .xlsx files on disk (use the xlsx skill in document-skills) or for Google Docs / Slides."
version: 1.0.0
allowed-tools: mcp__plugin_google-docs_google-docs__createSpreadsheet, mcp__plugin_google-docs_google-docs__getSpreadsheetInfo, mcp__plugin_google-docs_google-docs__readSpreadsheet, mcp__plugin_google-docs_google-docs__readCellFormat, mcp__plugin_google-docs_google-docs__writeSpreadsheet, mcp__plugin_google-docs_google-docs__appendRows, mcp__plugin_google-docs_google-docs__appendTableRows, mcp__plugin_google-docs_google-docs__batchWrite, mcp__plugin_google-docs_google-docs__clearRange, mcp__plugin_google-docs_google-docs__addSheet, mcp__plugin_google-docs_google-docs__deleteSheet, mcp__plugin_google-docs_google-docs__duplicateSheet, mcp__plugin_google-docs_google-docs__renameSheet, mcp__plugin_google-docs_google-docs__formatCells, mcp__plugin_google-docs_google-docs__addConditionalFormatting, mcp__plugin_google-docs_google-docs__freezeRowsAndColumns, mcp__plugin_google-docs_google-docs__setColumnWidths, mcp__plugin_google-docs_google-docs__autoResizeColumns, mcp__plugin_google-docs_google-docs__groupRows, mcp__plugin_google-docs_google-docs__ungroupAllRows, mcp__plugin_google-docs_google-docs__setDropdownValidation, mcp__plugin_google-docs_google-docs__insertChart, mcp__plugin_google-docs_google-docs__deleteChart, mcp__plugin_google-docs_google-docs__copyFormatting, mcp__plugin_google-docs_google-docs__moveFile, mcp__plugin_google-docs_google-docs__copyFile, mcp__plugin_google-docs_google-docs__renameFile
---

# Google Sheets — Professional Models & Dashboards

Port of the `xlsx` skill's financial-model / dashboard patterns to **Google Sheets** via the MCP toolset. Target is a Google Sheet (Drive-hosted), never a local `.xlsx`.

## Quick Reference

| Task | Tool(s) |
|------|---------|
| Create new sheet | `createSpreadsheet(title)` → `spreadsheetId` |
| Add tab | `addSheet(spreadsheetId, sheetName)` |
| Write range | `writeSpreadsheet(spreadsheetId, range, values)` |
| Append rows | `appendRows` (auto-finds next empty row) |
| Many edits atomically | `batchWrite` (one call, many ranges) |
| Read data | `readSpreadsheet(range, valueRenderOption="FORMATTED_VALUE" or "FORMULA")` |
| Cell formatting | `formatCells` (colors, number formats, borders, alignment) |
| Conditional fmt | `addConditionalFormatting` |
| Freeze rows/cols | `freezeRowsAndColumns(rowCount, columnCount)` |
| Column widths | `setColumnWidths` or `autoResizeColumns` |
| Dropdowns | `setDropdownValidation(range, values)` |
| Chart | `insertChart` |
| Move to folder | `moveFile(fileId=spreadsheetId, folderId=...)` |

## Creating a New Spreadsheet

1. `createSpreadsheet(title)` — returns `spreadsheetId` and a default sheet "Sheet1".
2. Rename the default sheet to something meaningful: `renameSheet(spreadsheetId, "Sheet1", "Inputs")`.
3. Add additional tabs up-front (`addSheet`) for logical separation: `Inputs`, `Assumptions`, `Model`, `Outputs`, `Charts`.
4. Write data with `batchWrite` — one call with multiple `range → values` pairs is faster and atomic.
5. Apply formatting AFTER data is written (so `autoResizeColumns` gets the final widths).

## Formulas

Google Sheets accepts the same formula syntax as Excel for the 95% case. Differences worth knowing:

- **Array formulas:** prefer `ARRAYFORMULA(...)` wrapper or just write the formula in each cell — Sheets auto-extends many functions.
- **Unique Sheets power tools:** `QUERY(data, "SELECT A, SUM(B) WHERE A IS NOT NULL GROUP BY A")`, `FILTER`, `SORT`, `UNIQUE`, `IMPORTRANGE`, `GOOGLEFINANCE`. Use these for pivot-ish summaries instead of native PivotTables (MCP doesn't expose pivot creation).
- **No `@` implicit intersection.** Direct cell refs work fine.
- **Date literals:** `DATE(YYYY, MM, DD)` cross-locale safe. Don't rely on `"2026-01-15"` strings unless you format the cell as date first.
- **Error handling:** `IFERROR(expr, 0)` or `IFNA(expr, "")`. **Zero-error requirement** from the xlsx skill carries over — no visible `#N/A` / `#DIV/0!` in a deliverable.

## Professional Model Conventions (carry-over from xlsx)

Apply these via `formatCells` / `addConditionalFormatting`:

- **Color code by cell role:**
  - Inputs (hard-typed numbers): **blue text** `#0000EE`, light yellow fill `#FFF2CC`
  - Formulas (derived): **black text**, no fill
  - Linked cells (from another sheet): **green text** `#006100`
  - Check cells / balance rows: **bold**, red fill if nonzero
- **Number formats:**
  - Currency: `"$"#,##0;[Red]("$"#,##0)`
  - Percentage: `0.0%` (one decimal) unless precision matters
  - Years as text: `formatCells(numberFormat="@", values=[2025, 2026, ...])` then the values stay visible as years, not date-formatted
  - Zeros as dash: `#,##0;(#,##0);"-"`
- **Headers:** bold, white text on `#1F4E78` (dark blue) fill. Freeze row 1.
- **Borders:** thin grey (`#CCCCCC`) on all data cells. Thick top border on total rows.
- **Alignment:** numbers right-aligned, labels left-aligned, headers center-aligned.

## Formatting Recipes

### Freeze and size

```
freezeRowsAndColumns(spreadsheetId, sheetId, rowCount=1, columnCount=1)
autoResizeColumns(spreadsheetId, sheetId, startColumn, endColumn)
# or, for intentional widths:
setColumnWidths(sheetId, [{column: 0, width: 200}, ...])
```

### Conditional formatting (common patterns)

- Negative red: rule `numberLessThan 0` → red text
- Above/below average: `numberGreaterThan =AVERAGE($A$2:$A$100)` → green fill
- Heatmap: `gradient` rule from low color to high color on a numeric range

```
addConditionalFormatting(spreadsheetId, sheetId, range, rule={
  type: "GRADIENT",
  minpoint: {color: "#F8696B", type: "MIN"},
  midpoint: {color: "#FFEB84", type: "PERCENTILE", value: "50"},
  maxpoint: {color: "#63BE7B", type: "MAX"}
})
```

### Dropdowns (data validation)

```
setDropdownValidation(spreadsheetId, sheetId, range="B2:B100",
                     values=["Draft", "Review", "Approved", "Shipped"])
```

## Charts

`insertChart(spreadsheetId, sheetId, chartSpec)` where `chartSpec` declares:
- `chartType`: `COLUMN`, `LINE`, `BAR`, `PIE`, `SCATTER`, `AREA`, `COMBO`
- `title`, `domainAxis` (x), `series` (y), `legendPosition`
- Data source: A1-notation range or sheet-relative range

**When to pick what:**
- Time series → `LINE` or `AREA`
- Compare categories → `COLUMN` (vertical) or `BAR` (horizontal when labels are long)
- Part-of-whole → `PIE` (≤5 categories) or `COLUMN` stacked (>5)
- Correlation → `SCATTER`
- Two metrics on different scales → `COMBO` with dual Y-axis

## Editing Existing Sheets

1. `readSpreadsheet(range, valueRenderOption="FORMULA")` — see formulas, not computed values. Use `"FORMATTED_VALUE"` for display output.
2. `readCellFormat(range)` — inspect existing formatting before overwriting.
3. **Never overwrite formulas with values.** Check `valueRenderOption="FORMULA"` first; if the target cells have formulas, ask before `writeSpreadsheet` with raw numbers.
4. `clearRange(range)` before rewriting a region — avoids stale rows below new data.

## Known Gaps & Workarounds

| Missing | Workaround |
|---------|------------|
| **Pivot tables via MCP** | Use `QUERY()` formula for grouping/aggregation. Or create the pivot manually in the UI after handoff. |
| **Named ranges** | Not exposed. Use absolute cell refs (`$Inputs.$B$5`) and a key cell with a label comment. |
| **Protected ranges / locked cells** | Not exposed. Flag the convention in a README tab. |
| **Scripts / macros** | Not exposed. Document the logic in cells or an "Instructions" tab. |

## Best Practices

- **Structure first, data second, formatting last.** Create tabs + headers, then `batchWrite` data, then format.
- **One `batchWrite` over many `writeSpreadsheet`.** Atomic + faster.
- **Validate zero errors before reporting done.** After writes, `readSpreadsheet(range, valueRenderOption="FORMATTED_VALUE")` and grep for `#`.
- **Date formats are locale-sensitive.** Always `formatCells(numberFormat="yyyy-mm-dd")` on date columns to avoid US/EU display flips.
- **Absolute refs for anchors.** Lookup tables, assumption cells, and rate tables always `$A$1`-style so fills don't break.

## Conversion & Export

- Export to `.xlsx` / `.csv` / `.pdf`: `downloadFile(fileId=spreadsheetId, mimeType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")` (xlsx) or `"text/csv"` (first sheet) or `"application/pdf"`.
- Template copy: `copyFile(fileId=templateId, name="New Name")` → new `spreadsheetId`.

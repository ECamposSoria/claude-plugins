# Google Docs MCP Plugin

This plugin provides full Google Workspace integration via MCP tools.

## Available Tools

### Google Docs (18 tools)
- `readGoogleDoc` - Read document content (text/markdown/JSON)
- `appendToGoogleDoc` - Append content to end of document
- `insertText` - Insert text at specific location
- `deleteRange` - Remove content by range
- `findAndReplace` - Search and replace
- `modifyText` - Update existing text
- `insertImage`, `insertTable`, `insertTableWithData`
- `insertPageBreak`
- Tab management: `listDocumentTabs`, `addTab`, `renameTab`
- Comments: create, read, delete, resolve comments

### Google Sheets (14 tools)
- Cell range read/write, sheet management, formatting, charts

### Google Drive (13 tools)
- Create, copy, delete, rename, move files/folders
- Search and list documents
- Download/export files

## Usage
Tools are available as MCP tools prefixed with `mcp__google-docs__`.

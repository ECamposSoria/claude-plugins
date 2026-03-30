---
name: scrape
description: Scrape a URL and extract structured data
argument-hint: <url> [extraction instructions]
---

The user wants to scrape a URL. Use the scraper MCP tools to fetch and extract data.

**URL:** $1
**Instructions:** $ARGUMENTS (everything after the URL)

Follow the scraping-strategy skill to choose the right approach:
- If the URL is a marketplace (mercadolibre, amazon), use `search-prices`
- If the URL is a social media profile, use `extract-structured-data` with `useOllama: true`
- If extraction instructions are provided, use `extract-structured-data`
- Otherwise, use `scrape-url` to get the page content

Present the results in a clean, structured format.

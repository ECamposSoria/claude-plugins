---
name: scraping-strategy
description: Use when the user asks to scrape websites, extract data from pages, gather information from URLs, or do web research that requires fetching live page content. Auto-activates when URLs are mentioned alongside extraction/scraping intent.
---

# Web Scraping Strategy

When the user asks you to scrape or extract data from websites, follow this decision tree:

## 1. Determine the Extraction Strategy

**Is the target a known marketplace (MercadoLibre, Amazon)?**
- YES → Use `search-prices` tool directly. It handles URL construction, pagination, and price statistics.
- NO → Continue to step 2.

**Is the target a social media platform (LinkedIn, Instagram, X, TikTok, Facebook)?**
- YES → Use `scrape-url` or `extract-structured-data` with `useOllama: true`. Social platforms have JS-heavy dynamic layouts that require LLM interpretation. Always provide explicit `instructions` describing what metrics/data to extract.
- NO → Continue to step 3.

**Do you know the page's HTML structure (or is it a well-known site pattern)?**
- YES → Use `scrape-url` with CSS `selectors` and `useOllama: false`. This is fastest and free.
- NO → Use `extract-structured-data` with `instructions` describing what to extract. The LLM will figure out the layout.

## 2. Handle Bulk Scraping Efficiently

When scraping multiple URLs:
1. **Don't extract everything from every page.** First scrape a sample of 2-3 pages with `useOllama: false` to understand what's there.
2. **Build selectors from the sample.** If the pages share a common structure, create CSS selectors and apply them to all pages without LLM.
3. **Only use LLM extraction on pages where selectors fail** or the structure is inconsistent.

## 3. Structure Your Output

Always return extracted data in a clean, structured format:
- For prices: include currency, min, max, average
- For products: name, price, URL, availability
- For social media: platform, handle, followers, engagement metrics
- For contacts: name, role, email, phone, company

## 4. Error Handling

- If a scrape returns empty content, the site may require login or have anti-bot protection. Note this to the user.
- If LLM extraction returns unexpected results, try again with more specific `instructions`.
- If a social media profile returns limited data, it may be private.

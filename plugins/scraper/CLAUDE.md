# Scraper — Self-Hosted Web Scraping & Intelligence

A private scraping microservice powered by Crawl4AI (headless Chromium) and Ollama (local LLM). It can scrape any website — including those behind robots.txt restrictions that block normal AI crawlers — extract structured data, and compare prices across marketplaces.

## When to Use This Plugin

Use the scraper tools whenever you need to:
- **Get real-time data from websites** that your training data doesn't cover or that block AI crawlers
- **Extract structured data** (prices, products, contacts, listings) from any page
- **Compare prices** across MercadoLibre, Amazon, or any e-commerce site
- **Analyze competitor pricing** or market positioning
- **Gather supplier catalogs** for procurement decisions
- **Monitor price changes** over time
- **Scrape social media profiles and posts** from platforms with strict robots.txt (LinkedIn, Instagram, X/Twitter, TikTok, Facebook)
- **Gather social media analytics** — follower counts, engagement metrics, post frequency, bio info, content themes
- **Competitive social media intelligence** — compare brand presence, posting strategies, audience engagement across platforms

## How It Works

This scraper runs a real headless browser (Chromium) on a private server. It renders JavaScript, handles dynamic content, and bypasses robots.txt restrictions that prevent API-based AI tools from accessing data. This is critical for:

- **Social media platforms** (LinkedIn, Instagram, X, TikTok, Facebook) which block all AI crawlers via robots.txt
- **E-commerce sites** that serve different content to bots vs browsers
- **JavaScript-heavy SPAs** that don't render without a real browser
- **Anti-scraping protections** that detect non-browser user agents

The data stays on your own infrastructure — nothing goes through third-party services except the target website.

## Available MCP Tools

### `scrape-url`
Scrape any URL and get back clean markdown + optional structured extraction.

**Use when:** You need the content of a specific page, or need to extract specific fields from it.

```
E-commerce examples:
- "Scrape https://supplier.com/catalog and extract all product names and prices"
- "Get the content of this wholesaler page and summarize what they sell"
- "Extract the job listings from this company's careers page"

Social media examples:
- "Scrape this LinkedIn company page and extract their employee count, industry, and recent posts"
- "Get this Instagram profile's bio, follower count, and last 10 post captions"
- "Scrape this X/Twitter profile and extract their posting frequency and engagement metrics"
- "Get this TikTok profile's follower count, total likes, and recent video descriptions"
- "Scrape this Facebook business page and extract reviews, rating, and contact info"
```

**Parameters:**
- `url` (required): The page to scrape
- `selectors`: CSS selectors for targeted extraction (e.g., `{"title": "h1", "price": ".price"}`)
- `instructions`: Natural language instructions for LLM extraction (e.g., "Extract all product names, prices, and availability")
- `jsonSchema`: JSON schema for structured output
- `schemaId`: Use a saved extraction schema
- `useOllama`: Enable/disable LLM extraction (default: true)

### `search-prices`
Search MercadoLibre (AR/BR) or Amazon (US) for product prices and get statistics.

**Use when:** You need to know how much something costs, compare prices, or analyze market pricing.

```
Examples:
- "Search for iPhone 15 prices on MercadoLibre Argentina"
- "Compare termo Stanley prices between MercadoLibre and Amazon"
- "What's the average price of Nike Air Force 1 on MercadoLibre?"
```

**Parameters:**
- `query` (required): Product search term
- `marketplaces`: `["mercadolibre"]`, `["amazon"]`, or both (default: both)
- `limit`: Max results per marketplace (1-50, default: 10)

**Returns:** Min, max, average prices + individual listings per marketplace.

### `extract-structured-data`
Scrape a URL and force structured extraction using LLM intelligence.

**Use when:** The page has complex/inconsistent layout and you need the AI to understand it — especially useful for social media profiles where layouts change frequently.

```
E-commerce examples:
- "Extract all distributor contact info from this wholesale directory"
- "Parse this supplier's product table into structured JSON"
- "Get the pricing tiers from this SaaS pricing page"

Social media analytics examples:
- "Extract a full competitive analysis from these 5 Instagram profiles: followers, post count, avg likes, bio keywords"
- "Get structured data from this LinkedIn company page: size, industry, specialties, recent job postings"
- "Analyze this X/Twitter account: follower/following ratio, avg retweets, posting frequency, top hashtags"
- "Extract this TikTok creator's metrics: videos, likes, followers, most-used sounds and hashtags"
- "Parse this Facebook page's about section, review score, response time, and business hours"
```

**Parameters:**
- `url` (required): The page to scrape
- `instructions`: What to extract (natural language)
- `jsonSchema`: Expected output structure
- `selectors`: CSS selectors for targeted fields

### `list-schemas`
List saved extraction schemas that define how to extract data from specific websites.

**Use when:** You want to see what pre-configured extraction patterns exist, or before creating a new one.

## Scraping Strategy Guide

### For Known/Structured Sites (Fast, Free)
Use CSS `selectors` — no LLM needed, instant results:
```json
{
  "url": "https://listado.mercadolibre.com.ar/iphone",
  "selectors": {
    "titles": ".poly-component__title",
    "prices": ".andes-money-amount__fraction"
  },
  "useOllama": false
}
```

### For Unknown/Dynamic Sites (Slower, Uses Ollama)
Use `instructions` + `jsonSchema` — the LLM reads the page and extracts what you describe:
```json
{
  "url": "https://random-wholesaler.com/products",
  "instructions": "Extract every product with name, price, and SKU",
  "jsonSchema": {
    "type": "object",
    "properties": {
      "products": {
        "type": "array",
        "items": {
          "type": "object",
          "properties": {
            "name": {"type": "string"},
            "price": {"type": "number"},
            "sku": {"type": "string"}
          }
        }
      }
    }
  }
}
```

### For Social Media Profiles (LLM Required)
Social platforms have dynamic, JS-heavy layouts. Always use `useOllama: true` with clear instructions:
```json
{
  "url": "https://www.instagram.com/brandname/",
  "instructions": "Extract the profile's display name, bio text, follower count, following count, post count, and whether the account is verified. Also extract the captions and like counts of the most recent visible posts.",
  "jsonSchema": {
    "type": "object",
    "properties": {
      "display_name": {"type": "string"},
      "bio": {"type": "string"},
      "followers": {"type": "number"},
      "following": {"type": "number"},
      "posts": {"type": "number"},
      "verified": {"type": "boolean"},
      "recent_posts": {
        "type": "array",
        "items": {
          "type": "object",
          "properties": {
            "caption": {"type": "string"},
            "likes": {"type": "number"}
          }
        }
      }
    }
  }
}
```

### The Sniper Strategy (Bulk Efficiency)
When scraping many domains, don't run heavy extraction on every site:
1. First pass: scrape with `useOllama: false` — just get the markdown
2. Analyze the markdown to see if the page has what you need
3. Only run full LLM extraction on pages that have relevant content

## Social Media Platform Notes

| Platform | What You Can Scrape | Notes |
|----------|-------------------|-------|
| **LinkedIn** | Company pages, job listings, public profiles | Login-walled content may require cookie injection in future |
| **Instagram** | Public profiles, post counts, bios, recent posts | Private accounts show limited data |
| **X/Twitter** | Public profiles, tweets, follower counts, bios | Rate limits apply; space out requests |
| **TikTok** | Creator profiles, video counts, follower metrics | Video content requires separate extraction |
| **Facebook** | Business pages, reviews, ratings, about sections | Personal profiles are heavily restricted |
| **YouTube** | Channel info, subscriber counts, video titles | Structured data available in page metadata |

**Why this works when other AI tools can't:** LinkedIn, Instagram, X, TikTok, and Facebook all block AI crawlers in robots.txt. Claude, ChatGPT, Perplexity, and other AI services respect these restrictions and return "I can't access that." Our scraper uses a real browser that renders the page like a human visitor.

## Important Notes

- The scraper uses a **real browser** — it handles JavaScript, SPAs, lazy loading, and anti-bot measures
- All data stays on your private infrastructure — no third-party APIs except the target website
- LLM extraction uses a **local Ollama model** (llama3 8B) — zero API cost
- For bulk operations, use the async API (`/scrape/async`) to avoid timeouts
- Price data from `search-prices` includes statistical analysis (min, max, avg, std dev)
- Social media scraping should be done responsibly — respect rate limits and avoid excessive requests

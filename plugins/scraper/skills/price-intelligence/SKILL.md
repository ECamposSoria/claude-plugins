---
name: price-intelligence
description: Use when the user asks about prices, pricing analysis, cost comparison, market research, wholesaler pricing, supplier comparison, or competitive pricing intelligence.
---

# Price Intelligence & Market Analysis

When the user asks about prices or market analysis, use the scraper to gather real-time data.

## Price Comparison Workflow

1. **Single product, known marketplaces** → Use `search-prices` with the product query
2. **Single product, specific URL** → Use `scrape-url` with price selectors or LLM instructions
3. **Multiple products or suppliers** → Scrape each URL, then compare in a structured table

## Analysis Output Format

Always present price data with:
- **Source** (which site/marketplace)
- **Currency** (ARS, USD, BRL, EUR)
- **Price range** (min — max)
- **Average price**
- **Number of listings found**
- **Best deal** (lowest price with link if available)

Example output format:
```
## iPhone 15 128GB — Price Analysis

| Source | Currency | Min | Max | Avg | Listings |
|--------|----------|-----|-----|-----|----------|
| MercadoLibre AR | ARS | 850,000 | 1,200,000 | 985,000 | 15 |
| Amazon US | USD | $699 | $849 | $742 | 10 |

Best deal: MercadoLibre AR — ARS 850,000 (~USD 850)
```

## Wholesaler/Supplier Analysis

When comparing suppliers:
1. Scrape each supplier's product page
2. Extract prices, MOQs (minimum order quantities), shipping terms
3. Calculate unit costs including shipping
4. Present a comparison table with total cost analysis

## Social Media Pricing Intelligence

For brands selling via social media:
1. Scrape their Instagram/Facebook shop or bio link
2. Extract product names and prices from posts/stories highlights
3. Compare with marketplace prices to identify markup

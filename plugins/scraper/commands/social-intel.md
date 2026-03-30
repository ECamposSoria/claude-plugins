---
name: social-intel
description: Analyze a social media profile (Instagram, LinkedIn, X, TikTok, Facebook)
argument-hint: <profile url>
---

The user wants to analyze a social media profile. Use `extract-structured-data` with `useOllama: true`.

**Profile URL:** $1

Extract the following (adapt based on the platform):
- Display name, handle, bio
- Follower count, following count
- Post/video count
- Verification status
- Recent content (last 5-10 posts): captions, engagement (likes, comments, shares)
- Content themes and posting frequency

Present the analysis as a structured profile summary with key metrics highlighted. If comparing multiple profiles, use a comparison table.

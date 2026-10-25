# fal endpoints, prices and traps

Prices checked on each model page on 2026-10-24. The catalog changes weekly: confirm the id with
`fal.py search` and the price on `https://fal.ai/models/<endpoint>` before quoting a total.

🔴 **The pricing API is not the price.** `fal.py price` can be wrong in both directions. It reports the
720p rate for Kling 4.0 (1080p costs 1.5× more). For Kling 3.0 Pro it reports $0.14/s, but the page
charges $0.112/s. For OpenAI endpoints it reports a placeholder `1 USD per units`, and for 3D models it
reports "units"/"credits" with no meaning; Nano Banana Pro doubles at 4K. The model page is the source of
truth, and the full price of the request is what you pass as `--max-usd` on every paid run.

## Images

| Endpoint | Price | Use it for |
|---|---|---|
| `openai/gpt-image-2.5/flare/edit` | $0.039 high @1920×1072, +$0.008 per reference | **Default paid edit.** Keeps subject, composition and background. |
| `openai/gpt-image-2.5/sunburst/edit` | see model page | Tightest scoping across many revision rounds |
| `openai/gpt-image-2/edit` | $0.158 high @1920×1080 | Same model as `image.py --model codex`; prefer 2.5 Flare |
| `fal-ai/nano-banana-pro/edit` | $0.15 / image, **$0.30 at 4K**, +$0.015 with web search | 4K, multi-image composition |
| `fal-ai/seedvr/upscale/image` | $0.001 / megapixel | Upscale a 1376×768 Antigravity frame to 1080p+ (~$0.003) |
| `fal-ai/finegrain-eraser/mask` | $0.045 / image, `mode=standard` | Remove an object and keep the camera geometry (see below) |
| `fal-ai/sam-3/image` | $0.005 | Segmentation masks. Masks have holes exactly at printed logos. |

## Video

| Endpoint | Price | Use it for |
|---|---|---|
| `fal-ai/kling-video/v3/pro/image-to-video` | **$0.112/s** audio off, $0.168/s audio on | **Default realistic clip.** People and physics; start + end frame. 🔴 `generate_audio` defaults to `true`: pass `false` unless you use its sound. |
| `kling/v4/image-to-video` | $0.157/s 720p, **$0.235/s 1080p** | Only for 30 s clips, per-shot `multi_prompt`, native audio. 🔴 `resolution` defaults to `1080p`. |
| `bytedance/seedance-2.5/us/image-to-video` | $0.0214 per 1K tokens, tokens = w×h×s×24/1024 (≈$1.04/s at 1080p) | End frame plus synced audio, up to 30 s. ~2× BytePlus's own price. |
| `google/gemini-omni-flash/v1.1/image-to-video` | $0.10/s 720p, $0.15/s 1080p ($0.03/s is the 360p floor `price` shows) | End frame plus synced audio; motion drafts at 360p |
| `minimax/h3/image-to-video` | $0.06/s 768P, $0.13/s 2K, $0.16/s 4K | **Candidate default** (2026-10-25): #1 on Artificial Analysis image-to-video (Elo 1140 vs Kling 3.0 Pro's 1000) at half Kling's price. 🔴 `resolution` defaults to `2K` (an upscale of 768P): pass `768P`. Not yet A/B-tested by us on people, lettering or start+end frames. |
| `blackforestlabs/flux-3-max/image-to-video` | $0.0425/s 720p, $0.0725/s 1080p **until 2026-11-07** (then $0.17 / $0.29) | #2 on the same board (1138); 5–20 s, audio on by default (`generate_audio: false`). Cheapest top model only while the promotion lasts. |
| `fal-ai/film` | $0.0013/s | Frame interpolation to repair a pop: `start_image_url`, `end_image_url`, `num_frames` (≤ 8). Pass `--max-usd 0.01`. |
| `fal-ai/sam-3/video` | $0.005 per 16 frames | Per-frame masks of people/objects for compositing repairs |

Quality rankings (blind human votes, read 2026-10-25): https://artificialanalysis.ai/video/leaderboard/image-to-video.
Kling 3.0 Pro is ranked 18th there; it stays the default until one A/B take on a real brief confirms a
replacement, because it is the model our repair recipes and motion transfer were proven on.

When both the first and the last frame matter, pass both: on per-second pricing an end frame costs nothing.
Draft at 720p, render finals at 1080p, cap takes at three per shot.

## 3D models (output: GLB)

| Endpoint | Price | Use it for |
|---|---|---|
| `fal-ai/hunyuan-3d/v3.1/pro/image-to-3d` | $0.375; +$0.15 each for PBR, multi-view, custom face count | **Real product from several photos.** Takes `input_image_url` (front) plus optional `back_`, `left_`, `right_`, `top_`, `bottom_`, 45° views. |
| `fal-ai/hunyuan-3d/v3.1/rapid/image-to-3d` | $0.225 | Quick draft from one photo |
| `tripo3d/h3.1/image-to-3d` | $0.20 untextured, $0.30 standard texture, $0.40 HD; +$0.20 detailed geometry | Cheapest textured model; `orientation=align_image`, `auto_size` for real-world meters |
| `meshy/v7.1/image-to-3d` | $0.80 untextured, **$1.20 textured**; +$0.20 rigging | Low-poly / smart topology, rigged characters |

Input photo rules (from the Hunyuan schema): simple background, single object filling more than half the
frame, 128–5000 px, ≤ 8 MB. Generated models invent the hidden sides and smear printed labels, so for a
product page compare the model against the photos before it ships. Displaying the GLB on a site is
website-builder's job (its 3D section).

## Cost traps

- Every submit that passes validation **starts a billable run**. Read `schema`; never probe by omitting
  params. Unknown params are silently ignored, so copy names from `schema`.
- Schema enums can be stale: `fal-ai/finegrain-eraser/mask` lists `mode=premium`, the API rejects it.
- An empty balance locks the account: every call fails at upload with `403` on
  `rest.fal.ai/storage/auth/token` ("User is locked. Reason: Exhausted balance"). Nothing is billed; top up
  at fal.ai/dashboard/billing. Credits expire after 365 days; 5xx failures are not billed.
- The real lever on a video bill is the model and the resolution, not the provider: Kling 3.0 Pro at 720p
  for drafts is ~2× cheaper than Kling 4.0 at 1080p for the same seconds.

## Removing an object from a photo

- **Use the eraser** (`fal-ai/finegrain-eraser/mask`): it keeps the camera geometry pixel for pixel, so real
  pixels can be pasted back outside the mask. Good fill on floors and sky; invents junk where it has to
  continue printed text, and re-renders the frame slightly softer.
- **Not Flux Fill** (`fal-ai/flux-pro/v1/fill`): given an object-shaped mask it paints a new object of the
  same silhouette.
- **Not `mask_url` on `openai/gpt-image-2/edit`**: the mask is ignored and the whole scene regenerated.

## Other providers (decided 2026-10-24, details in the shared media memory `~/projects/image-video-generation/memory/`)

- **Venice**: never-expiring credits; its "Private" models are less restricted. Use only when fal models
  refuse a legitimate brief. Its "Anonymized" third-party models keep upstream filters.
- **Higgsfield API**: half-price Kling 4.0, but trains on all content including API calls. Not without the
  owner's consent.
- **BytePlus ModelArk**: official Seedance at half fal's price. No account yet; worth it only if Seedance
  becomes regular.

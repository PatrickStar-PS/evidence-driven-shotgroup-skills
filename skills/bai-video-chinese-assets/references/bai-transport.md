# 中转站传输约定

## Endpoints and models

- Chat endpoint default: `https://api.b.ai/v1/chat/completions`
- Models endpoint: derive `/v1/models` from the chat endpoint or use `BAI_MODELS_ENDPOINT`
- Authentication: `Authorization: Bearer <key>`
- Extraction model default: `gemini-3.6-flash`
- Merge model: explicit `BAI_MERGE_MODEL`/`--merge-model`, otherwise discover available models and prefer the highest available Gemini model ID containing `pro`

Do not hard-code `gemini-3.5-pro` unless the authenticated account returns that exact ID. Prefer exact discovered IDs. Stop if no Pro model is available.

## Requests

For extraction, encode one video as `data:<mime>;base64,...` in an `image_url` block followed by the extraction prompt. Run independent requests concurrently; default to five workers and distribute the key pool round-robin.

For merging, send only the combined structured candidate text. Make exactly one chat-completions request. Request structured JSON output when supported. Never upload all videos again for the merge.

Send `stream: false`, bounded output tokens, and low temperature. Treat all defaults as configurable. Preserve sanitized response metadata and raw model text.

Send a stable browser-compatible `User-Agent` on both chat and model-discovery requests. The 中转站 Cloudflare edge may reject Python's default client signature with HTTP 403 / Error 1010 even when the same credential is valid.

## Secrets

Read keys from `BAI_API_KEY`, `BAI_KEY_POOL_FILE`, or `--key-pool-file`. Accept one key per line and ignore blank/comment lines. Never log, persist, or place keys in prompts.

## Limits and retries

Default to a 20 MB binary inline-video limit because Base64 expands request size. Check before encoding and never silently bypass the limit. Bound concurrency to a positive integer.

Retry HTTP 429, 500, 502, 503, 504 and transient network failures with bounded exponential backoff. Do not retry ordinary 4xx errors. A failed global merge remains one semantic attempt: transport retries may resend the identical request, but no revised prompt or second-model adjudication is allowed.

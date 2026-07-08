# Verification — Token usage capture under streaming (root cause + fix)

**Date:** 2026-07-07  •  **Author:** Mark Brown (with agent)  •  **Related:** ADR-0002
**Status:** ✅ Verified live against Azure OpenAI (Entra ID auth)

## Question
The live Cosmos audit found `Debug.total_tokens = 0` for **334/334** documents. ADR-0002
hypothesized the cause was the model running `streaming=True` (`azure_open_ai.py:41`) while the
extractor reads `response_metadata['token_usage']` (`travel_agents_api.py:687-690`), and proposed
enabling `stream_usage`/`include_usage` as the fix. Both the cause and the proposed fix were
flagged "confirm by live test." This is that test.

## Method
Throwaway script built `AzureChatOpenAI` three ways using the app's **real** `.env`
(`02_completed/python/.env`, endpoint `openai-kfpokdh52vbec`, deployment `gpt-4.1-mini`,
api-version `2024-12-01-preview`) and Entra ID auth (`DefaultAzureCredential`, account
`disableLocalAuth: true`). For each, it invoked a short prompt and printed both
`response_metadata['token_usage']` (what the extractor reads) and `msg.usage_metadata`.

- **A.** `streaming=True` — current app config
- **B.** `streaming=True, stream_usage=True` — the fix ADR-0002 proposed
- **C.** `streaming=False` — baseline

Env: `langchain-openai 1.3.3`, Python 3.12.

## Result (verbatim)

```
=== A. streaming=True  (current app config) ===
  response_metadata['token_usage'] = {}
  msg.usage_metadata              = {'input_tokens': 18, 'output_tokens': 17, 'total_tokens': 35, ...}
  -> extractor would record total_tokens = 0  (usage_metadata total = 35)

=== B. streaming=True, stream_usage=True  (candidate fix) ===
  response_metadata['token_usage'] = {}
  msg.usage_metadata              = {'input_tokens': 18, 'output_tokens': 16, 'total_tokens': 34, ...}
  -> extractor would record total_tokens = 0  (usage_metadata total = 34)

=== C. streaming=False  (baseline) ===
  response_metadata['token_usage'] = {'completion_tokens': 17, 'prompt_tokens': 18, 'total_tokens': 35,
      ..., 'latency_checkpoint': {'engine_ttft_ms': 28, 'total_duration_ms': 369, ...}}
  msg.usage_metadata              = {'input_tokens': 18, 'output_tokens': 17, 'total_tokens': 35, ...}
  -> extractor would record total_tokens = 35  (usage_metadata total = 35)

SUMMARY (extractor-visible total_tokens, usage_metadata total):
  A_streaming_true (current app)         rm=     0  um=    35
  B_streaming_true+stream_usage          rm=     0  um=    34
  C_streaming_false                      rm=    35  um=    35
```

## ⚠️ Version-accurate correction (2026-07-07, added after end-to-end testing)
The probe below was run with **`langchain-openai 1.3.3`**, but the **app pins `langchain-openai==0.3.3`** (`requirements.txt`). Behavior differs, and the difference matters:
- On **0.3.3**, plain `streaming=True` leaves **both** `response_metadata['token_usage']` **and** `msg.usage_metadata` **empty** — so a reader-only change does **nothing** (confirmed: an initial reader-only fix still logged `total_tokens=0` end-to-end).
- The working fix on 0.3.3 is **two parts** (verified live, PR #70): (1) set `model_kwargs={"stream_options": {"include_usage": True}}` on the model so it emits a usage chunk that LangChain aggregates into `usage_metadata`, **and** (2) read `msg.usage_metadata`. After this, a 3-message session recorded real totals `2618 / 3178 / 3412` (0 before).
- Note `stream_usage=True` as a **constructor kwarg** is **not** accepted in 0.3.3 (it forwards to `Completions.create()` and errors); use `model_kwargs.stream_options` instead.

**Lesson:** always verify against the app's *pinned* dependency versions, not the latest. The findings below (1.3.3) are retained for history but superseded by this correction for the app.

---


1. **Root cause confirmed.** With `streaming=True`, `response_metadata['token_usage']` is `{}`, so
   the extractor at `travel_agents_api.py:687-690` records `total_tokens=0`. This reproduces the
   334/334 zero-token audit result exactly.
2. **ADR-0002's proposed fix is falsified.** Adding `stream_usage=True` (variant B) does **not**
   repopulate `response_metadata['token_usage']` — it stays `{}`. So the naive "enable stream usage
   and keep the reader" approach would **not** have fixed the bug.
3. **Correct fix identified.** `msg.usage_metadata` is populated (~35 tokens) in **all three**
   variants, including plain `streaming=True` with **no extra flags**. The fix is a **reader
   change**, not a model-config change:
   - Read `msg.usage_metadata` -> `input_tokens` / `output_tokens` / `total_tokens`.
   - Cached tokens: `usage_metadata['input_token_details']['cache_read']`
     (note: different path/name than `response_metadata`'s `prompt_tokens_details.cached_tokens`).
4. **Bonus (Pillar 1 latency lead).** Non-streaming `response_metadata` (variant C) carries a
   `latency_checkpoint` block (`engine_ttft_ms`, `total_duration_ms`, etc.). This is a candidate
   server-side latency source, but it is **absent under streaming** — capturing latency will need a
   different approach (e.g., wall-clock timing around the call) on the streaming hot path.

## Implication for the plan
- The `TokenUsage` instrumentation fix is a low-risk reader change in the extractor; it does **not**
  require touching `azure_open_ai.py` or changing `streaming=True`.
- Latency (Pillar 1) is **not** free from streaming metadata — it needs explicit timing.

## Reproduce
Script (throwaway, not committed): session workspace
`~/.copilot/session-state/<session>/files/verify_tokens.py`. Requires `az login` (Entra ID) with
data-plane access to the AOAI resource, and `pip install langchain-openai azure-identity python-dotenv`.

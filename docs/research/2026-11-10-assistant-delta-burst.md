# Why `assistant.delta` frames arrive in one burst (Issue 681)

Measured 2026-11-10 on the live gateway (hermes-agent `b200f5bc60`, Haiku 5.5 on the native Anthropic leg, `agent.reasoning_effort: high`).

## Verdict

**Hermes streams live. The burst is the provider's: after an adaptive-thinking block, Haiku 5.5 delivers the thinking summary and the whole short answer in one flush.** No Hermes code or config change is needed; Iris can switch thinking off per request and get live text. That is a quality trade the owner decides (see *What it would take*), so nothing is changed here.

## The path, and why none of it buffers

| Hop | Where | Behaviour |
|-|-|-|
| Model call | `agent/turn_api_call.py:46` `_should_stream` | streams whenever a delta callback is set (the chat/stream route sets one) |
| Wire loop | `agent/chat_completion_helpers.py:3444` | each `text_delta` event goes to `_emit_text` as it arrives |
| Delivery | `agent/stream_delivery.py:332` `_fire_stream_delta` | per-delta scrub, then the callback; no batching (the leading `\n\n` Iris saw is `_stream_needs_break`, lines 341-344) |
| SSE route | `gateway/platforms/api_server.py:3116` | `events.enqueue("assistant.delta", …)` per call; `_SessionEventQueue.enqueue` (`:978`) puts straight on the queue |
| Inference gateway | agent-workflows `packages/gateway/src/proxy.ts:468-512` | one upstream chunk per `pull`, `highWaterMark: 0`, tee reads a copy |

The paths that *do* re-emit text in bulk are not in play: `_replay_final_response` (`chat_completion_helpers.py:3248`, one delta for the whole reply) and the guardrail halt (`turn_tool_round.py:194`).

## Evidence

**1. Straight at the inference gateway**, adaptive thinking + `effort: high`, a prompt that makes the model think (two runs each):

| Thinking | Thinking ends | First text | Last text | Text deltas | Within first 50 ms |
|-|-|-|-|-|-|
| adaptive | 3.62 s | 3.62 s | 3.63 s | 37 | 37 |
| adaptive | 2.39 s | 2.39 s | 2.39 s | 30 | 30 |
| disabled | none | 0.66 s | 1.53 s | 44 | 2 |
| disabled | none | 0.56 s | 1.61 s | 50 | 2 |

With thinking on, every thinking delta and every text delta carries the same timestamp. With it off, text is spread over ~1 s. On prompts where the model skips thinking (a plain "explain X" prompt, nine runs across `high`/`medium`/`low` and `summarized`/`omitted`/default), text streams live too, so the burst follows a thinking block, not the effort setting itself.

**2. Through Hermes, same prompt, `POST /api/sessions/<id>/chat/stream`.** `ts` is the frame's own timestamp, offsets from the request:

| Request | `assistant.delta` | First | Last | Spread | Within first 50 ms | `assistant.completed` |
|-|-|-|-|-|-|-|
| default (`high`) | 26 | 3.828 s | 3.848 s | 0.020 s | 26 | 3.924 s |
| default (`high`) | 37 | 3.542 s | 3.564 s | 0.023 s | 37 | 3.625 s |
| `model_options.reasoning_effort: "none"` | 72 | 1.252 s | 2.791 s | 1.539 s | 1 | 2.865 s |
| `model_options.reasoning_effort: "none"` | 59 | 0.839 s | 2.005 s | 1.166 s | 1 | 2.572 s |

Hermes reproduces the Issue's burst (all deltas inside 23 ms, 0.07-0.1 s before `assistant.completed`) and, with thinking off, spreads the same kind of answer over 1.2-1.5 s. Hermes adds nothing in between.

**3. A longer answer after a tool call** (`terminal`, then ~700 chars): `tool.completed` at 11.551 s, first delta 13.283 s, 42 deltas by 13.397 s, then one every ~20 ms until 13.947 s. The head of the answer rides the post-thinking flush; only text beyond it is live. Short replies (Iris's, ~300 chars) fit entirely inside the flush, which is why Issue 642's recording saw all 28 deltas within 1 ms.

## What it would take

| Option | Effect | Cost |
|-|-|-|
| Iris sends `model_options: {"reasoning_effort": "none"}` with the memo turn | text streams from the first token; the final call is ~1 s shorter (3.9 → 2.9 s, 3.6 → 2.6 s above) | the model stops thinking before routing (answer / `capture` / note / `fleet`); the bench that picked `high` (15/15; `medium` dropped a task, per the `config.yaml` comment) did not include `none`. Needs a routing check on Iris turns first. No Hermes change; `api_server_request_options.py:13` already maps it, `api_server.py:2207` applies it |
| `agent.reasoning_effort: none` in `config.yaml:91` | same, for every surface | also hits cron briefings and the CLI; not recommended |
| `thinking.display: omitted` | none: the flush is the thinking block ending, not its display | measured, no change |
| A change in Hermes or the inference gateway | none | nothing is buffered there |

The live text is worth at most the generation time of the answer (~0.3 s for 300 chars at ~1 k chars/s); the wait the user feels is the thinking before it. Turning thinking off removes that wait, not the streaming.

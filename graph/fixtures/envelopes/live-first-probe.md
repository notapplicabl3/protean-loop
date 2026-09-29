# The first wet row — the probe record

`the build specification (not in this mirror)` § Deliverable 6 (the first wet row) · order W1 ·
DoD row W1. Written by `tests/wet/probe_first_row.py` from the captured stdout of four
real calls; every number below is read off the capture, none is typed in.

- **Resolved binary version at the time:** `2.1.263 (Claude Code)`
- **Model:** `claude-opus-5` at `--effort high` — the executor row of
  § Deliverable 1's `brain/seats.yaml` table.
- **Session handle minted on call 1:** `1a749df0-42f2-4d07-a793-1dcc78e86088`
- **Stable prefix:** 21073 characters of plain deterministic filler,
  passed on `--system-prompt`, identical across probe 1's two calls.
- **Structured output:** a minimal hand-authored schema, not one of the three tiers'
  narrowed schemas — those are order W2's artifact and row K1's offline compile.
- **Environment:** the parent's, less every `CLAUDE*`, `ANTHROPIC_*`, `RIG_*` and
  `PROTEAN_*` variable. § Deliverable 1's full scrub is order W2's contract and order
  W7's proof; it is **not** probed here.
- **cwd for every call:** a throwaway empty temporary directory. No `--add-dir` on any
  call, including the executor-shaped ones — this probe has no task workspace.

## Probe 1 — the resume cache hold, on the executor's real model

| Number | Value |
|---|---|
| call 1 `cache_creation_input_tokens` | 22170 |
| call 2 `cache_read_input_tokens` | 22170 |
| equal | True |
| call 1 `input_tokens` / `output_tokens` | 2 / 53 |
| call 2 `input_tokens` / `output_tokens` | 2 / 53 |
| call 1 `cache_read_input_tokens` | 0 |
| call 2 `cache_creation_input_tokens` | 156 |
| call 1 exit / wall | 0 / 3.321s |
| call 2 exit / wall | 0 / 2.878s |
| call 1 `total_cost_usd` | 0.22399699999999997 |
| call 2 `total_cost_usd` | 0.01398 |

A mismatch here does not stop the build — it moves the cost model to cold and is
reported (§ Deliverable 6).

Call 1 argv, as run:

```
claude -p --setting-sources "" --model claude-opus-5 --effort high --output-format json --json-schema "{\"type\":\"object\",\"properties\":{\"reply\":{\"type\":\"string\",\"description\":\"the literal token the prompt asks for\"}},\"required\":[\"reply\"],\"additionalProperties\":false}" --system-prompt "<the stable prefix: 21073 chars of filler>" --permission-mode auto --allowedTools Read Edit Write Grep Glob Bash(uv:*) Bash(python:*) Bash(pytest:*) "Bash(git status:*)" "Bash(git diff:*)" "Bash(git add:*)" "Bash(git commit:*)" "Bash(git checkout:*)" "Bash(git branch:*)" "Bash(git log:*)" --disallowedTools WebFetch WebSearch Bash(curl:*) Bash(wget:*) "Bash(git push:*)" "Bash(git remote:*)" "Bash(git fetch:*)" "Bash(git pull:*)" --max-budget-usd 1.00 --session-id 1a749df0-42f2-4d07-a793-1dcc78e86088
```

Call 2 argv, as run:

```
claude -p --setting-sources "" --model claude-opus-5 --effort high --output-format json --json-schema "{\"type\":\"object\",\"properties\":{\"reply\":{\"type\":\"string\",\"description\":\"the literal token the prompt asks for\"}},\"required\":[\"reply\"],\"additionalProperties\":false}" --system-prompt "<the stable prefix: 21073 chars of filler>" --permission-mode auto --allowedTools Read Edit Write Grep Glob Bash(uv:*) Bash(python:*) Bash(pytest:*) "Bash(git status:*)" "Bash(git diff:*)" "Bash(git add:*)" "Bash(git commit:*)" "Bash(git checkout:*)" "Bash(git branch:*)" "Bash(git log:*)" --disallowedTools WebFetch WebSearch Bash(curl:*) Bash(wget:*) "Bash(git push:*)" "Bash(git remote:*)" "Bash(git fetch:*)" "Bash(git pull:*)" --max-budget-usd 1.00 --resume 1a749df0-42f2-4d07-a793-1dcc78e86088
```

## Probe 2 — the envelope diff, and it is the blocker

Call 1's raw stdout is `fixtures/envelopes/live-first.json`, written byte-for-byte
before anything parsed it (folded: S-17).

| Required fact | Present |
|---|---|
| `stop_reason` | 'tool_use' |
| `result_is_a_json_string` | True |
| `modelUsage_present` | True |
| `usage.cache_read_input_tokens_present` | True |

- **Validates against `SeatEnvelope`:** True
- **Fields `SeatEnvelope` declares:** `stop_reason`, `result`, `modelUsage`, `usage`
- **Fields the envelope carries that the model does not name (21):**
  `api_error_status`, `duration_api_ms`, `duration_ms`, `fast_mode_disabled_reason`, `fast_mode_state`, `first_content_frame_ms`, `is_error`, `num_turns`, `permission_denials`, `queued_turn_count`, `session_id`, `structured_output`, `subagent_stats`, `subtype`, `terminal_reason`, `time_to_request_ms`, `total_cost_usd`, `ttft_ms`, `ttft_stream_ms`, `type`, `uuid`
- **Preserved by `ExtraTolerantModel` as `model_extra` (21):**
  `api_error_status`, `duration_api_ms`, `duration_ms`, `fast_mode_disabled_reason`, `fast_mode_state`, `first_content_frame_ms`, `is_error`, `num_turns`, `permission_denials`, `queued_turn_count`, `session_id`, `structured_output`, `subagent_stats`, `subtype`, `terminal_reason`, `time_to_request_ms`, `total_cost_usd`, `ttft_ms`, `ttft_stream_ms`, `type`, `uuid`

## Probe 3 — `--tools ""`, director-shaped

| Fact | Value |
|---|---|
| exit code | 1 |
| stdout bytes | 2073 |
| `stop_reason` | 'refusal' |
| `is_error` | True |
| `num_turns` | 1 |
| `subtype` | 'success' |
| `terminal_reason` | 'api_error' |
| `total_cost_usd` | 0.07132000000000001 |
| structured result | False |
| model | 'claude-opus-5' |
| wall | 1.427s |

**Outcome:** no structured result — so the `--disallowedTools` fallback is recorded below, per S-6.

`result`, verbatim:

```
API Error: Opus 5's safeguards flagged this message (https://www.anthropic.com/legal/aup). This sometimes happens with safe, normal conversations. Claude Code can't respond to this message with Opus 5.

Try rephrasing the request in a new session or change your model.

Learn more: https://support.claude.com/en/articles/16049681

Details: `[reasoning_extraction]`

Request ID: req_REDACTED
```

**Read this before order W2 fixes the director and planner argv.** The call was refused
at the API — `stop_reason` is not `tool_use`, `terminal_reason` is `api_error` and
`is_error` is true — and the refusal text is a model-safeguard message, not a complaint
about the flag. Probe 1's two calls ran on the same binary, the same model and the same
stable prefix and both returned structured successes, so `--tools ""` is **unproven**
here rather than disproven. Order W1's restriction is one call per probe and a recorded
failure over a retried spend, so it was not re-run. The conservative reading is the
recorded fallback; disambiguating costs one more real call.

Argv, as run:

```
claude -p --setting-sources "" --model claude-opus-5 --effort high --output-format json --json-schema "{\"type\":\"object\",\"properties\":{\"reply\":{\"type\":\"string\",\"description\":\"the literal token the prompt asks for\"}},\"required\":[\"reply\"],\"additionalProperties\":false}" --system-prompt "<the stable prefix: 21073 chars of filler>" --tools "" --max-budget-usd 1.00
```

The fallback, if it is ever needed (S-6) — `--disallowedTools` naming every acting tool:

```
WebFetch WebSearch Bash(curl:*) Bash(wget:*) Bash(git push:*) Bash(git remote:*) Bash(git fetch:*) Bash(git pull:*) Bash Edit Write NotebookEdit Task KillShell BashOutput
```

## Probe 4 — the dollar cap, `--max-budget-usd 0.001`

| Fact | Value |
|---|---|
| exit code | 1 |
| stdout bytes | 1773 |
| an envelope came back | True |
| `subtype` | 'error_max_budget_usd' |
| `is_error` | True |
| `stop_reason` | 'tool_use' |
| `num_turns` | 2 |
| `terminal_reason` | 'budget_exhausted' |
| `errors` | ['Reached maximum budget ($0.001)'] |
| `result` key present | False |
| `total_cost_usd` actually spent | 0.0559485 |
| validates as a `SeatEnvelope` | no — result: Field required |
| wall | 2.737s |

**What order W2's adapter does at the cap.** An envelope *did* come back on a non-zero
exit, but it carries no `result` key at all, so `SeatEnvelope` refuses it — the four
required facts are not all there. With `is_error` true and `subtype`
`error_max_budget_usd`, this is decision 11's shape and not a decode failure: the
adapter raises `SeatUnavailable` and never constructs an envelope. Note also that the
cap is enforced *after* a turn, not before it: the spend recorded on this call is two
orders of magnitude above the cap it was given, so `max_call_usd` bounds the *next*
turn rather than the current one.

Verbatim stderr at the cap:

```
(empty)
```

Verbatim stdout at the cap (first 2000 characters):

```
{"duration_api_ms":823,"stop_reason":"tool_use","session_id":"57d9fd47-f4a3-402d-81d7-738bdcbec070","total_cost_usd":0.0559485,"usage":{"output_tokens_details":{"thinking_tokens":0},"input_tokens":0,"cache_creation_input_tokens":0,"cache_read_input_tokens":0,"output_tokens":0,"server_tool_use":{"web_search_requests":0,"web_fetch_requests":0},"service_tier":"standard","cache_creation":{"ephemeral_1h_input_tokens":0,"ephemeral_5m_input_tokens":0},"inference_geo":"","iterations":[],"speed":"standard"},"modelUsage":{"claude-haiku-4-5-20251001":{"inputTokens":912,"outputTokens":9,"cacheReadInputTokens":0,"cacheCreationInputTokens":0,"webSearchRequests":0,"costUSD":0.0009570000000000001,"contextWindow":200000,"maxOutputTokens":32000,"thinkingTokens":0,"canonicalModel":"claude-haiku-4-5","provider":"firstParty","costBasis":"list"},"claude-opus-5":{"inputTokens":2,"outputTokens":53,"cacheReadInputTokens":17693,"cacheCreationInputTokens":4481,"webSearchRequests":0,"costUSD":0.0549915,"contextWindow":1000000,"maxOutputTokens":64000,"thinkingTokens":0,"canonicalModel":"claude-opus-5","provider":"firstParty","costBasis":"list"}},"permission_denials":[],"terminal_reason":"budget_exhausted","fast_mode_state":"off","fast_mode_disabled_reason":"sdk_opt_in_required","subagent_stats":{"spawned":0,"requested":{"background":0,"foreground":0,"unset":0},"started_in_background":0,"max_depth":0,"spawned_by_subagents":0,"completed":0,"failed":0,"killed":{"parent":0,"user":0,"system":0},"refused":{"depth_limit":0,"concurrency_limit":0,"budget":0},"by_type":{}},"is_error":true,"num_turns":2,"subtype":"error_max_budget_usd","errors":["Reached maximum budget ($0.001)"],"type":"result","duration_ms":1579,"uuid":"12aa457b-f32e-4438-9405-b26e552fb83d","queued_turn_count":0}
```

Argv, as run:

```
claude -p --setting-sources "" --model claude-opus-5 --effort high --output-format json --json-schema "{\"type\":\"object\",\"properties\":{\"reply\":{\"type\":\"string\",\"description\":\"the literal token the prompt asks for\"}},\"required\":[\"reply\"],\"additionalProperties\":false}" --system-prompt "<the stable prefix: 21073 chars of filler>" --permission-mode auto --allowedTools Read Edit Write Grep Glob Bash(uv:*) Bash(python:*) Bash(pytest:*) "Bash(git status:*)" "Bash(git diff:*)" "Bash(git add:*)" "Bash(git commit:*)" "Bash(git checkout:*)" "Bash(git branch:*)" "Bash(git log:*)" --disallowedTools WebFetch WebSearch Bash(curl:*) Bash(wget:*) "Bash(git push:*)" "Bash(git remote:*)" "Bash(git fetch:*)" "Bash(git pull:*)" --max-budget-usd 0.001
```

## What this row cost

| Probe | `total_cost_usd` |
|---|---|
| 1, call 1 (cold, cache creation) | 0.22399699999999997 |
| 1, call 2 (warm, cache read) | 0.01398 |
| 3 (`--tools ""`) | 0.07132000000000001 |
| 4 (at the cap) | 0.0559485 |
| **the whole row** | 0.365246 |

The cold call dominates: a 22 kB stable prefix is ~22k cache-creation tokens on the
executor's model, and the warm call is a sixteenth of it. That ratio is the cost model
order W8 re-seeds homeostasis's ceilings against, not the raw totals — this row's prefix
is filler and the real one is `brain/nodes/cortex/NODE.md` plus `brain/seats/<tier>.md`.

## What reads this file

Order W2 reads probe 3's outcome (which flag the director and planner argv carries) and
probe 4's at-cap behaviour (what the adapter does at the cap). Order W8 re-seeds
homeostasis's ceilings from probe 1's token numbers (S-19, and § Named assumptions 3).

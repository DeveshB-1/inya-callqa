# inya-callqa

A read-only MCP server and CLI that audits Gnani Inya voice-agent calls for the failures that show up in Indian code-mixed conversations: template variables spoken out loud, agents answering a Hindi or Kannada caller in English, questions the agent skipped, and user turns where the parallel ASR hypotheses (`en-IN` vs `hi-IN` / `kn-IN`) heard different words.

It talks to the [Agent Builder Platform API](https://docs.gnani.ai/Platform/platform-introduction) (`https://api.inya.ai/platform`), so you can ask Claude Code, Claude Desktop or Cursor things like "audit the last 50 answered calls of my collections agent and show me every call where it read a placeholder aloud".

## Why this matters to Gnani

Every user turn in the Stats API already carries one transcript per configured language plus `detectedLanguage` and `userInterruptionFlag`. That data is enough to catch a lot of bad calls automatically, but today someone has to read transcripts to find them.

Run against the **verified example call in Gnani's own [Get Conversation Statistics](https://docs.gnani.ai/Platform/Get_Conversation_Stats) docs**, the audit finds:

- The agent said `Your loan payment of [due_amount] was due on [due_date]` to the borrower. Two pre-call variables never got filled.
- It greeted the caller as `shyam1234` (a username, which TTS reads digit by digit), then asked "am I speaking with Nani?"
- The caller asked "how much is my due amount" and the agent's next line was "Hello, am I speaking with Nani?"
- For one turn, `en-IN` heard "yes you are" and `hi-IN` heard "येस शुर" (yes sure).

The bot is named `Muthoot-sanity_outbound_`, so it's probably a test call with test data. Still, that's four different kinds of problem (config, data, dialogue, ASR) in one 81-second call, found without an LLM, and the same classes of bug reach real borrowers on production agents.

## What it checks

| Check | Severity | Signal |
|---|---|---|
| `unrendered_placeholder` | high | `[var]`, `{{ var }}`, `{var}` or `<var>` in an agent turn |
| `null_value_spoken` | high | `None` / `null` / `undefined` / `NaN` in an agent turn |
| `spoken_identifier` | medium | letters glued to 3+ digits (`shyam1234`) in an agent turn |
| `asr_hypothesis_disagreement` | medium | the `totalResults` hypotheses for one user turn don't sound alike (see below) |
| `language_mismatch` | medium | caller turn detected as Hindi/Kannada/Tamil/Telugu/Marathi/Bengali, agent reply has neither that script nor common romanised words of that language |
| `possible_ignored_question` | medium | caller asked something (English, Hinglish or Kannada question words, or `?`), agent's next turn shares no content word and gives no number |
| `missing_disposition` | medium | `ANSWERED` call with empty `overallCallDisposition` |
| `high_average_latency` | medium | `averageAgentLatency` > 2s (the threshold Gnani's docs call out) |
| `slow_agent_turn` | low | > 2s between a user turn and the agent's reply |
| `repeated_agent_turn` | low | agent says the same line twice |

### How the code-mixed comparison works

`en-IN` returns Latin script and `hi-IN` returns Devanagari for the same audio, so string diffing is useless. `translit.py` uses the fact that the Brahmic Unicode blocks share one layout (offset `0x15` is "ka" in Devanagari, Kannada, Telugu, Bengali, Gujarati, Malayalam...) to transliterate any of them with one table, then both hypotheses go through a phonetic key (merge aspirates, fold vowel runs, drop silent English `e` / `gh`, soft and hard `c`) and a normalised edit distance.

```
how much is my due amount      vs  हाउ मच इज़ माइ ड्यू अमाउंट     0.95  same sounds
cancel maadi                   vs  ಕ್ಯಾನ್ಸಲ್ ಮಾಡಿ                 1.00  same sounds
yes you are                    vs  येस शुर                      0.71  flagged
can you call me                vs  ಕ್ಯಾನ್ಸಲ್ ಮಾಡಿ                 0.50  flagged
```

It catches "the two recognisers heard different sounds". It cannot catch "same sounds, wrong words" (an `en-IN` model writing Kannada audio as English look-alike words would score high). Flagged turns are good candidates for an ASR eval set.

## Quickstart

```bash
uv sync
# offline, no key: audit saved Stats API responses (or post-call payloads in the same shape)
uv run inya-callqa audit fixtures/docs_example_stats.json

# live: pull recent answered calls and audit them
export INYA_API_KEY=...            # Agent Builder API key with `conversations` + `agents` permission
export INYA_ENVIRONMENT=production # default: development
uv run inya-callqa audit-live --bot-id <botId> --limit 50
```

CLI exit code is 1 when any call has a high-severity finding, so it can gate a deploy in CI after a prompt change.

### As an MCP server

```json
{
  "mcpServers": {
    "inya-callqa": {
      "command": "uv",
      "args": ["--directory", "/path/to/inya-callqa", "run", "inya-callqa", "serve"],
      "env": { "INYA_API_KEY": "...", "INYA_ENVIRONMENT": "production" }
    }
  }
}
```

Tools: `list_agents`, `get_agent`, `list_conversations`, `get_conversation`, `audit_conversation`, `audit_recent_calls`, `audit_transcript` (offline, no key), `validate_prompt`.

All tools are read-only on purpose. There's no create/update/delete and no `trigger_call`, so a model can't edit a production agent or place a phone call. A test asserts that.

The client also guards two footguns the docs describe: `pageNo=0` (HTTP 500 on List Agents) and an empty `systemPrompt` on Validate Prompt (silently reported as valid).

## Demo run

Executed 2026-10-25 against the three fixtures. `docs_example_stats.json` is Gnani's documented example, verbatim. The other two are **synthetic** calls written by hand in the documented shape (labelled `_source: SYNTHETIC` inside the file).

```
$ uv run inya-callqa audit fixtures/docs_example_stats.json fixtures/synthetic_hinglish_calls.json fixtures/synthetic_kannada_english_call.json
call 1786433682702486082  bot=Muthoot-sanity_outbound_  status=ANSWERED  disposition=PTP
  turns=11 user_turns=5 languages={'english': 5} code_mixed_turns=0 interruptions=0 max_agent_gap=3.91s
  [HIGH  ] unrendered_placeholder       turn 4   [due_amount]
  [HIGH  ] unrendered_placeholder       turn 4   [due_date]
  [MEDIUM] spoken_identifier            turn 0   shyam1234
  [MEDIUM] possible_ignored_question    turn 2   user: 'how much is my due amount' -> agent: 'Hello, am I speaking with Nani?'
  [MEDIUM] asr_hypothesis_disagreement  turn 3   en-IN='yes you are' vs hi-IN='येस शुर'
  [LOW   ] slow_agent_turn              turn 10  3.91s

call syn-hi-001  bot=emi-reminder-hinglish  status=ANSWERED  disposition=PTP
  turns=7 user_turns=3 languages={'hindi': 3} code_mixed_turns=2 interruptions=1 max_agent_gap=4.5s
  [HIGH  ] unrendered_placeholder       turn 0   {{ customer_name }}
  [HIGH  ] null_value_spoken            turn 4   None
  [MEDIUM] high_average_latency         call     2.4s
  [MEDIUM] possible_ignored_question    turn 2   user: 'haan boliye, kitna baaki hai?' -> agent: 'Aapka account active hai. Kya aap is mahine payment kar payenge?'
  [MEDIUM] language_mismatch            turn 4   Thank you for confirming. I have noted your payment date as None.
  [MEDIUM] asr_hypothesis_disagreement  turn 5   en-IN='text me monday' vs hi-IN='नेक्स्ट वीक मंडे को'
  [LOW   ] slow_agent_turn              turn 4   4.50s

call syn-hi-002  bot=emi-reminder-hinglish  status=ANSWERED  disposition=AP
  turns=3 user_turns=1 languages={'hindi': 1} code_mixed_turns=1 interruptions=0 max_agent_gap=0.7s
  no findings

call syn-kn-001  bot=order-support-kannada  status=ANSWERED  disposition=
  turns=7 user_turns=3 languages={'kannada': 3} code_mixed_turns=3 interruptions=0 max_agent_gap=0.8s
  [MEDIUM] missing_disposition          call
  [MEDIUM] asr_hypothesis_disagreement  turn 5   en-IN='can you call me' vs kn-IN='ಕ್ಯಾನ್ಸಲ್ ಮಾಡಿ'
  [MEDIUM] language_mismatch            turn 6   Your order has been cancelled and the refund is initiated.

rollup: 4 calls, 12 user turns, code-mixed share 50%, 2 calls with HIGH findings
  asr_hypothesis_disagreement  3/4 calls
  possible_ignored_question    2/4 calls
  slow_agent_turn              2/4 calls
  unrendered_placeholder       2/4 calls
  language_mismatch            2/4 calls
  spoken_identifier            1/4 calls
  null_value_spoken            1/4 calls
  high_average_latency         1/4 calls
  missing_disposition          1/4 calls
```

The clean Hindi call (`syn-hi-002`, agent answers in Devanagari with an amount) produces no findings, and the romanised-Kannada agent replies in `syn-kn-001` aren't flagged as a language mismatch.

### MCP over stdio

`scripts/mock_inya.py` serves the same fixtures in the documented Platform API envelopes (`POST /v1/conversations/logs`, `GET /v1/conversations/{id}/stats`, ...). `scripts/mcp_demo.py` launches `inya-callqa serve` as a subprocess, the way Claude Desktop does, and calls a tool over stdio:

```
$ python scripts/mock_inya.py 18431 &
$ INYA_API_KEY=demo INYA_BASE_URL=http://127.0.0.1:18431/platform python scripts/mcp_demo.py
tools: list_agents, get_agent, list_conversations, get_conversation, audit_conversation, audit_recent_calls, audit_transcript, validate_prompt
{
  "calls": 4,
  "user_turns": 12,
  "code_mixed_turn_share": 0.5,
  "calls_with_high_severity": 2,
  ...
}
1786433682702486082: 6 findings, first = unrendered_placeholder '[due_amount]'
syn-hi-001: 7 findings, first = unrendered_placeholder '{{ customer_name }}'
syn-kn-001: 3 findings, first = missing_disposition ''
```

## Tests

```
$ uv run pytest -q
.........................                                                [100%]
25 passed in 3.17s
```

Covers transliteration (Devanagari nukta and schwa deletion, Kannada), the similarity thresholds, every check on the fixtures, the request shape the client sends (headers, `environment` query param, `filter` body), error `requestId` propagation, pagination against the mock HTTP server, and the MCP server in-process (including "no write tools exist").

## What's not verified

- I don't have an Inya API key. Every live path was run against `scripts/mock_inya.py`, which follows the request and response shapes in docs.gnani.ai. Field names on a real account could differ (e.g. extra languages in `totalResults`).
- `language_mismatch` and `possible_ignored_question` are heuristics with word lists. Expect some false positives; they're labelled "possible" for that reason.
- The transliterator is built to compare sounds, nothing more. It's not a display-quality transliteration.

## Layout

```
inya_callqa/translit.py   Brahmic -> Latin, phonetic key, similarity
inya_callqa/audit.py      checks, per-call report, rollup
inya_callqa/client.py     read-only Platform API client (httpx)
inya_callqa/server.py     MCP server (mcp 2.x MCPServer)
inya_callqa/cli.py        audit / audit-live / serve
scripts/                  mock API + MCP stdio demo
fixtures/                 docs example (verbatim) + 2 synthetic calls
```

Built by Devesh B (github.com/DeveshB-1). Not affiliated with Gnani.ai.

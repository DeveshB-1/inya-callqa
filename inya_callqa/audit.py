"""Deterministic QA checks over one Inya conversation (the ``response[]`` item
returned by ``GET /v1/conversations/{id}/stats``).

Every check works on the documented Stats shape: ``utteranceAnalytics`` turns with
``role``, ``content``, ``timestamp`` and, on user turns, ``totalResults``,
``detectedLanguage`` and ``userInterruptionFlag``. No LLM is involved, so the
same call always produces the same findings.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import asdict, dataclass, field
from typing import Any

from .translit import has_indic, scripts_in, sound_similarity

SEVERITY_ORDER = {"high": 0, "medium": 1, "low": 2}

# Template syntaxes that should never reach TTS: [var], {{ var }}, {var}, <var>
PLACEHOLDER_RE = re.compile(
    r"\[[A-Za-z_][A-Za-z0-9_ .]{0,40}\]"
    r"|\{\{.{1,60}?\}\}"
    r"|\{[A-Za-z_][A-Za-z0-9_]{0,40}\}"
    r"|<[a-z_][a-z0-9_]{0,40}>"
)
NULLISH_RE = re.compile(r"\b(None|null|undefined|NaN|nan)\b")
# letters immediately followed by 3+ digits: "shyam1234", "user2024"
SPOKEN_ID_RE = re.compile(r"\b[A-Za-z]+[_.]?\d{3,}\b")

QUESTION_WORDS = {
    # English
    "what", "when", "where", "why", "how", "which", "who", "can", "could",
    "will", "is", "are", "do", "does", "did", "should",
    # Romanised Hindi / Hinglish
    "kya", "kab", "kaise", "kyun", "kyon", "kahan", "kitna", "kitni", "kitne",
    "kaun", "konsa",
    # Romanised Kannada
    "yaavaga", "hege", "yaake", "elli", "eshtu", "yaaru", "yenu", "enu",
}
# Native-script question words (Devanagari + Kannada)
NATIVE_QUESTION_WORDS = {"क्या", "कब", "कैसे", "क्यों", "कहाँ", "कितना", "कितनी", "कौन",
                         "ಯಾವಾಗ", "ಹೇಗೆ", "ಯಾಕೆ", "ಎಲ್ಲಿ", "ಎಷ್ಟು", "ಯಾರು", "ಏನು"}
STOPWORDS = {
    "i", "me", "my", "you", "your", "the", "a", "an", "is", "are", "am", "to",
    "of", "for", "and", "or", "it", "this", "that", "in", "on", "do", "does",
    "can", "will", "what", "when", "how", "why", "which", "who", "hai", "ka",
    "ki", "ke", "mera", "meri", "kya", "kab", "please", "ok", "okay",
}

# detectedLanguage value -> (expected scripts, romanised marker words)
LANGUAGES = {
    "hindi": ({"devanagari"}, {"hai", "aap", "aapka", "aapki", "ji", "haan", "nahi",
                               "kya", "mein", "hum", "karenge", "kar", "raha", "rahe"}),
    "marathi": ({"devanagari"}, {"aahe", "tumhi", "nahi", "ho", "kay", "mi"}),
    "kannada": ({"kannada"}, {"illa", "houdu", "nimma", "beku", "ide", "swalpa",
                              "saar", "namaskara", "hegiddira", "sari"}),
    "tamil": ({"tamil"}, {"illai", "aamaa", "ungal", "vendum", "irukku", "sari"}),
    "telugu": ({"telugu"}, {"ledu", "avunu", "mee", "kavali", "undi", "sare"}),
    "bengali": ({"bengali"}, {"ache", "apnar", "na", "hya", "korbo"}),
}


@dataclass
class Finding:
    check: str
    severity: str
    turn: int
    evidence: str
    detail: str = ""


@dataclass
class CallReport:
    conversation_id: str
    bot_name: str
    call_status: str | None
    disposition: str | None
    turns: int
    user_turns: int
    languages: dict[str, int]
    code_mixed_turns: int
    interruptions: int
    max_agent_gap_s: float | None
    findings: list[Finding] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["findings_by_severity"] = dict(Counter(f.severity for f in self.findings))
        return d


def _words(text: str) -> list[str]:
    return re.findall(r"[^\W\d_]+|\d+", text.lower())


def _is_question(text: str) -> bool:
    if "?" in text:
        return True
    words = _words(text)
    if not words:
        return False
    if words[0] in QUESTION_WORDS:
        return True
    return any(w in NATIVE_QUESTION_WORDS for w in text.split()) or any(
        w in {"kitna", "kitni", "kab", "kaise", "eshtu", "yaavaga"} for w in words
    )


def _content_words(text: str) -> set[str]:
    return {w for w in _words(text) if w not in STOPWORDS and len(w) > 2}


def audit_call(
    call: dict[str, Any],
    *,
    disagreement_threshold: float = 0.75,
    slow_turn_s: float = 2.0,
) -> CallReport:
    turns = call.get("utteranceAnalytics") or []
    findings: list[Finding] = []
    langs: Counter[str] = Counter()
    code_mixed = interruptions = 0
    max_gap: float | None = None
    seen_agent_lines: dict[str, int] = {}

    for i, t in enumerate(turns):
        role, content = t.get("role"), (t.get("content") or "").strip()
        nxt = turns[i + 1] if i + 1 < len(turns) else None
        next_agent = nxt if nxt and nxt.get("role") == "assistant" else None

        if role == "assistant":
            for m in PLACEHOLDER_RE.finditer(content):
                findings.append(Finding("unrendered_placeholder", "high", i, m.group(0),
                    "Template variable spoken literally to the caller; the pre-call variable was missing or misnamed."))
            for m in NULLISH_RE.finditer(content):
                findings.append(Finding("null_value_spoken", "high", i, m.group(0),
                    "A null/None value was interpolated into the agent's speech."))
            for m in SPOKEN_ID_RE.finditer(content):
                findings.append(Finding("spoken_identifier", "medium", i, m.group(0),
                    "Looks like a username or ID read aloud; TTS will spell out the digits."))
            key = re.sub(r"\W+", " ", content.lower()).strip()
            if key and key in seen_agent_lines:
                findings.append(Finding("repeated_agent_turn", "low", i, content[:80],
                    f"Same line as turn {seen_agent_lines[key]}; possible loop."))
            seen_agent_lines.setdefault(key, i)
            continue

        if role != "user":
            continue

        lang = (t.get("detectedLanguage") or "unknown").lower()
        langs[lang] += 1
        if t.get("userInterruptionFlag"):
            interruptions += 1
        scripts = scripts_in(content)
        if len(scripts) > 1 or (lang != "english" and "latin" in scripts):
            code_mixed += 1

        # 1. Parallel ASR hypotheses that do not sound alike
        hyps = {k: v for k, v in (t.get("totalResults") or {}).items() if v}
        if len(hyps) >= 2:
            items = sorted(hyps.items())
            worst = min(
                ((a, b, sound_similarity(va, vb)) for n, (a, va) in enumerate(items)
                 for (b, vb) in items[n + 1:]),
                key=lambda x: x[2],
            )
            if worst[2] < disagreement_threshold:
                findings.append(Finding("asr_hypothesis_disagreement", "medium", i,
                    f"{worst[0]}={hyps[worst[0]]!r} vs {worst[1]}={hyps[worst[1]]!r}",
                    f"Sound similarity {worst[2]:.2f} < {disagreement_threshold}. "
                    "The recognisers heard different words; the agent acted on one of them."))

        if next_agent is None:
            continue
        reply = next_agent.get("content") or ""

        # 2. Slow agent response
        try:
            gap = float(next_agent["timestamp"]) - float(t["timestamp"])
        except (KeyError, TypeError, ValueError):
            gap = None
        if gap is not None:
            max_gap = gap if max_gap is None else max(max_gap, gap)
            if gap > slow_turn_s:
                findings.append(Finding("slow_agent_turn", "low", i + 1, f"{gap:.2f}s",
                    f"Agent took longer than {slow_turn_s}s to answer this user turn."))

        # 3. Caller spoke language X, agent answered in something else
        if lang in LANGUAGES:
            want_scripts, markers = LANGUAGES[lang]
            if not (scripts_in(reply) & want_scripts) and not (set(_words(reply)) & markers):
                findings.append(Finding("language_mismatch", "medium", i + 1, reply[:80],
                    f"Caller turn detected as {lang}; agent replied without {lang} script or common {lang} words."))

        # 4. Caller asked something, agent's next turn shares no words and no number
        if _is_question(content):
            asked = _content_words(content)
            for v in hyps.values():
                asked |= _content_words(v)
            if not (asked & _content_words(reply)) and not re.search(r"\d", reply):
                findings.append(Finding("possible_ignored_question", "medium", i + 1,
                    f"user: {content!r} -> agent: {reply[:70]!r}",
                    "Next agent turn shares no content words with the question and gives no number."))

    avg = call.get("averageAgentLatency")
    if isinstance(avg, (int, float)) and avg > slow_turn_s:
        findings.append(Finding("high_average_latency", "medium", -1, f"{avg}s",
            "averageAgentLatency above 2s; Gnani's docs flag this as worth tuning LLM/TTS settings."))
    if call.get("callStatus") == "ANSWERED" and not call.get("overallCallDisposition"):
        findings.append(Finding("missing_disposition", "medium", -1, "",
            "Answered call has no overallCallDisposition; it will not map to a CRM outcome."))

    findings.sort(key=lambda f: (SEVERITY_ORDER[f.severity], f.turn))
    return CallReport(
        conversation_id=str(call.get("conversationId", "")),
        bot_name=call.get("botName", ""),
        call_status=call.get("callStatus"),
        disposition=call.get("overallCallDisposition"),
        turns=len(turns),
        user_turns=sum(langs.values()),
        languages=dict(langs),
        code_mixed_turns=code_mixed,
        interruptions=interruptions,
        max_agent_gap_s=round(max_gap, 2) if max_gap is not None else None,
        findings=findings,
    )


def calls_from_payload(payload: Any) -> list[dict[str, Any]]:
    """Accept a full Stats API envelope, its ``response`` list, or one call."""
    if isinstance(payload, dict) and "response" in payload:
        payload = payload["response"]
    if isinstance(payload, dict):
        payload = [payload]
    return [c for c in payload if isinstance(c, dict) and "utteranceAnalytics" in c]


def rollup(reports: list[CallReport]) -> dict[str, Any]:
    checks: Counter[str] = Counter()
    calls_with: Counter[str] = Counter()
    for r in reports:
        names = [f.check for f in r.findings]
        checks.update(names)
        calls_with.update(set(names))
    user_turns = sum(r.user_turns for r in reports)
    return {
        "calls": len(reports),
        "user_turns": user_turns,
        "code_mixed_turn_share": round(sum(r.code_mixed_turns for r in reports) / user_turns, 3) if user_turns else 0.0,
        "calls_with_high_severity": sum(any(f.severity == "high" for f in r.findings) for r in reports),
        "findings_by_check": dict(checks.most_common()),
        "calls_affected_by_check": dict(calls_with.most_common()),
    }

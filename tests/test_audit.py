from conftest import load

from inya_callqa.audit import audit_call, calls_from_payload, rollup


def checks(report):
    return [(f.check, f.turn) for f in report.findings]


def test_docs_example_call(docs_call):
    r = audit_call(docs_call)
    assert ("unrendered_placeholder", 4) in checks(r)
    assert {f.evidence for f in r.findings if f.check == "unrendered_placeholder"} == {"[due_amount]", "[due_date]"}
    assert ("spoken_identifier", 0) in checks(r)
    assert ("possible_ignored_question", 2) in checks(r)
    assert ("asr_hypothesis_disagreement", 3) in checks(r)
    # high severity sorts first
    assert r.findings[0].severity == "high"
    assert r.user_turns == 5 and r.languages == {"english": 5}


def test_clean_hindi_call_has_no_findings():
    calls = calls_from_payload(load("synthetic_hinglish_calls.json"))
    clean = next(c for c in calls if c["conversationId"] == "syn-hi-002")
    assert audit_call(clean).findings == []


def test_hinglish_failures():
    calls = calls_from_payload(load("synthetic_hinglish_calls.json"))
    r = audit_call(next(c for c in calls if c["conversationId"] == "syn-hi-001"))
    got = {f.check for f in r.findings}
    assert {"unrendered_placeholder", "null_value_spoken", "language_mismatch", "slow_agent_turn",
            "high_average_latency", "possible_ignored_question", "asr_hypothesis_disagreement"} <= got
    assert r.interruptions == 1
    assert r.code_mixed_turns == 2


def test_kannada_english_failures():
    r = audit_call(calls_from_payload(load("synthetic_kannada_english_call.json"))[0])
    assert {f.check for f in r.findings} == {"missing_disposition", "language_mismatch", "asr_hypothesis_disagreement"}
    # agent replied in romanised Kannada on turns 2 and 4: not flagged
    assert [f.turn for f in r.findings if f.check == "language_mismatch"] == [6]


def test_threshold_is_configurable(docs_call):
    loose = audit_call(docs_call, disagreement_threshold=0.5)
    assert "asr_hypothesis_disagreement" not in {f.check for f in loose.findings}


def test_payload_shapes_and_rollup(docs_call):
    env = load("docs_example_stats.json")
    assert len(calls_from_payload(env)) == len(calls_from_payload(env["response"])) == 1
    assert len(calls_from_payload(docs_call)) == 1
    ru = rollup([audit_call(docs_call)])
    assert ru["calls"] == 1 and ru["calls_with_high_severity"] == 1
    assert ru["findings_by_check"]["unrendered_placeholder"] == 2
    assert ru["calls_affected_by_check"]["unrendered_placeholder"] == 1


def test_empty_call_is_safe():
    r = audit_call({"conversationId": "x", "utteranceAnalytics": []})
    assert r.findings == [] and r.max_agent_gap_s is None

from conftest import ROOT

from inya_callqa.cli import main

FX = ROOT / "fixtures"


def test_exit_code_reflects_high_findings(capsys):
    assert main(["audit", str(FX / "docs_example_stats.json")]) == 1
    out = capsys.readouterr().out
    assert "unrendered_placeholder" in out and "[due_amount]" in out


def test_clean_only_input_exits_zero(tmp_path, capsys):
    import json
    calls = json.loads((FX / "synthetic_hinglish_calls.json").read_text(encoding="utf-8"))["response"]
    p = tmp_path / "clean.json"
    p.write_text(json.dumps([c for c in calls if c["conversationId"] == "syn-hi-002"]), encoding="utf-8")
    assert main(["audit", str(p), "--json"]) == 0
    assert '"calls_with_high_severity": 0' in capsys.readouterr().out

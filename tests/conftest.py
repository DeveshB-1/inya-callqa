import json
import sys
import threading
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import mock_inya  # noqa: E402


def load(name: str):
    return json.loads((ROOT / "fixtures" / name).read_text(encoding="utf-8"))


@pytest.fixture
def docs_call():
    return load("docs_example_stats.json")["response"][0]


@pytest.fixture
def mock_api():
    srv = mock_inya.ThreadingHTTPServer(("127.0.0.1", 0), mock_inya.Handler)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    yield f"http://127.0.0.1:{srv.server_address[1]}/platform"
    srv.shutdown()

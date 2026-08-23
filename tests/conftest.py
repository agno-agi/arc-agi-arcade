"""Test scaffolding: offline engine, controlled run dirs. No network, no model calls."""

from os import environ
from pathlib import Path
from types import SimpleNamespace

REPO = Path(__file__).parent.parent

# Must precede arcade imports: tools.py reads these at import time (ENVIRONMENTS_DIR) and at engine reset.
environ["OPERATION_MODE"] = "offline"
environ.setdefault("ENVIRONMENTS_DIR", str(REPO / "environment_files"))
environ.pop("ARC_RUN_DIR", None)  # tests opt in per-fixture; never inherit a live run's directory

import pytest  # noqa: E402

_CACHE = Path(environ["ENVIRONMENTS_DIR"])
GAMES_CACHED = (_CACHE / "tr87").exists() and (_CACHE / "cd82").exists()
needs_engine = pytest.mark.skipif(not GAMES_CACHED, reason="game cache not downloaded (environment_files/)")


@pytest.fixture
def run_dir(tmp_path, monkeypatch):
    """A fresh ARC_RUN_DIR for one test; ArcadeTools reads it at construction."""
    directory = tmp_path / "run"
    monkeypatch.setenv("ARC_RUN_DIR", str(directory))
    return directory


@pytest.fixture
def fc():
    """A minimal FunctionCall stand-in: tools only touch fc.function.stop_after_tool_call."""
    return SimpleNamespace(function=SimpleNamespace(stop_after_tool_call=False))


@pytest.fixture
def usage():
    """Provider-usage stand-in matching what MeteredResponses feeds the meter."""

    def make(input_tokens=1000, output_tokens=200, cached=100, reasoning=150):
        return SimpleNamespace(
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            total_tokens=input_tokens + output_tokens,
            cache_read_tokens=cached,
            reasoning_tokens=reasoning,
        )

    return make

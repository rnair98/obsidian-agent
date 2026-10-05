import importlib.util
import json
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

_HOOK = Path(__file__).resolve().parents[2] / ".cursor" / "hooks" / "complexity.py"
_SPEC = importlib.util.spec_from_file_location("complexity_hook", _HOOK)
assert _SPEC is not None and _SPEC.loader is not None
_hook = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_hook)

_FIXTURES = Path(__file__).resolve().parents[1] / "support" / "sensors" / "fixtures"
_COMPLEX = _FIXTURES / "too_complex.py"
_SIMPLE = _FIXTURES / "simple_fn.py"


@pytest.fixture(autouse=True)
def _isolated_state(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # Hook state lives under gettempdir(); keep each test's conversation private.
    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path))


def test_cognitive_gate_flags_the_canary() -> None:
    report = _hook.violations([_COMPLEX, _SIMPLE])
    assert "nested" in report
    assert "plain" not in report
    assert "cognitive" in report


def test_post_edit_context_names_the_gate() -> None:
    result = _hook.handle(
        {
            "hook_event_name": "postToolUse",
            "conversation_id": "complexity-canary",
            "tool_name": "Write",
            "tool_input": {"path": str(_COMPLEX)},
        }
    )
    context = result["additional_context"]
    assert "§9 complexity" in context
    assert "nested" in context


def test_stop_followup_replays_a_recorded_edit() -> None:
    conversation_id = "complexity-stop"
    assert (
        _hook.handle(
            {
                "hook_event_name": "afterFileEdit",
                "conversation_id": conversation_id,
                "file_path": str(_COMPLEX),
            }
        )
        == {}
    )
    result = _hook.handle(
        {
            "hook_event_name": "stop",
            "conversation_id": conversation_id,
            "status": "completed",
            "loop_count": 0,
        }
    )
    assert "nested" in result["followup_message"]


def test_stop_is_quiet_when_the_edit_is_under_the_gate() -> None:
    conversation_id = "complexity-quiet"
    _hook.handle(
        {
            "hook_event_name": "afterFileEdit",
            "conversation_id": conversation_id,
            "file_path": str(_SIMPLE),
        }
    )
    assert (
        _hook.handle(
            {
                "hook_event_name": "stop",
                "conversation_id": conversation_id,
                "status": "completed",
                "loop_count": 0,
            }
        )
        == {}
    )


def test_hook_script_emits_json() -> None:
    completed = subprocess.run(
        [sys.executable, str(_HOOK)],
        input=json.dumps(
            {"hook_event_name": "stop", "status": "aborted", "loop_count": 0}
        ),
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0
    assert json.loads(completed.stdout) == {}

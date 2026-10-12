from __future__ import annotations

import json
from pathlib import Path

from agent_engineering_kit.events import append_event, read_events


def test_events_are_append_only_and_redacted(tmp_path: Path) -> None:
    path = tmp_path / "events.jsonl"

    append_event(
        path,
        {
            "event_id": "event-1",
            "run_id": "run-1",
            "recorded_at": "2026-10-12T10:00:00+00:00",
            "type": "tool_call",
            "payload": {"tool": "database.query", "arguments": {"token": "secret", "query": "select 1"}},
        },
    )
    append_event(
        path,
        {
            "event_id": "event-2",
            "run_id": "run-1",
            "recorded_at": "2026-10-12T10:00:01+00:00",
            "type": "verification",
            "payload": {"status": "passed"},
        },
    )

    lines = path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2
    assert "secret" not in path.read_text(encoding="utf-8")
    first = json.loads(lines[0])
    assert first["schema"] == "agent-engineering-kit/run-event/v1"
    assert first["payload"]["arguments"]["token"] == "[REDACTED]"
    assert [event["event_id"] for event in read_events(path)] == ["event-1", "event-2"]


def test_tool_results_can_be_replaced_with_metadata(tmp_path: Path) -> None:
    path = tmp_path / "events.jsonl"
    append_event(
        path,
        {
            "event_id": "event-1",
            "run_id": "run-1",
            "recorded_at": "2026-10-12T10:00:00+00:00",
            "type": "tool_result",
            "payload": {"result": "confidential row", "row_count": 1},
        },
        redact_tool_results=True,
    )

    event = read_events(path)[0]
    assert event["payload"]["result"] == "[REDACTED]"
    assert event["payload"]["row_count"] == 1

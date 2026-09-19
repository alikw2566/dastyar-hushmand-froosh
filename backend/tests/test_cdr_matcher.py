from types import SimpleNamespace

import pytest

from app.services.cdr import IssabelCdrMatcher
from app.services.filename_parser import CallFileMetadata


@pytest.mark.asyncio
async def test_unconfigured_cdr_is_explicitly_unmatched_not_fabricated():
    matcher = IssabelCdrMatcher()
    matcher.engine = None
    result = await matcher.match(CallFileMetadata(unique_call_id="171234.12"))
    assert result.status == "unmatched"
    assert result.method == "cdr_not_configured"
    assert result.row is None


def test_agent_extension_is_derived_from_asterisk_channel():
    assert IssabelCdrMatcher.extension("SIP/204-00001abc") == "204"
    assert IssabelCdrMatcher.extension("PJSIP/1001@trunk-00001") == "1001"
    assert IssabelCdrMatcher.extension(None) is None


@pytest.mark.asyncio
async def test_recordingfile_is_the_first_cdr_match_key():
    captured = {}

    class Result:
        def mappings(self):
            return self

        def all(self):
            return [{"uniqueid": "171234.12", "recordingfile": "call.wav"}]

    class Connection:
        async def execute(self, statement, parameters):
            captured["sql"] = str(statement)
            captured["parameters"] = parameters
            return Result()

    class ConnectionContext:
        async def __aenter__(self):
            return Connection()

        async def __aexit__(self, *_):
            return None

    class Engine:
        def connect(self):
            return ConnectionContext()

    matcher = IssabelCdrMatcher.__new__(IssabelCdrMatcher)
    matcher.settings = SimpleNamespace(
        issabel_cdr_table="cdr",
        issabel_cdr_recording_column="recordingfile",
        issabel_cdr_match_window_seconds=180,
    )
    matcher.engine = Engine()
    result = await matcher.match(CallFileMetadata(), recording_file="call.wav")
    assert result.status == "matched"
    assert result.method == "recordingfile"
    assert captured["parameters"]["recording_file"] == "call.wav"
    assert "`recordingfile`" in captured["sql"]

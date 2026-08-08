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

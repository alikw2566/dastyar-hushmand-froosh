from datetime import UTC, datetime
from pathlib import Path

from app.services.followups import build_followup_spec
from app.services.glossary import GlossaryEntry, apply_glossary, normalize_with_glossary
from app.tasks import run_provider_pipeline


def test_followup_triggers_are_deterministic_and_do_not_invent_due_date(analysis_factory):
    no_action = analysis_factory(outcome="lost", funnel_stage="closed_lost")
    assert build_followup_spec("call-1", no_action) is None
    promise = analysis_factory(customer={"commitments": ["ارسال پیش فاکتور و تماس"]})
    first = build_followup_spec("call-1", promise)
    second = build_followup_spec("call-1", promise)
    assert first is not None
    assert first.due_at is None
    assert first.dedupe_key == second.dedupe_key
    due = datetime(2026, 8, 4, 9, tzinfo=UTC)
    explicit = analysis_factory(customer={"followup_at": due})
    assert build_followup_spec("call-2", explicit).due_at == due


def test_glossary_normalizes_alias_without_overwriting_raw_text(analysis_factory):
    entries = [GlossaryEntry("Microsoft CRM", ("مایکروسافت سی آر ام",), "product")]
    raw = "درباره مایکروسافت سی آر ام توضیح بدهید"
    assert normalize_with_glossary(raw, entries) == "درباره Microsoft CRM توضیح بدهید"
    segments = apply_glossary(
        [{"speaker": "speaker_0", "text": raw, "start": 0, "end": 2}], entries
    )
    assert segments[0]["text"] == raw
    assert "Microsoft CRM" in segments[0]["normalized_text"]

    class Provider:
        def __init__(self):
            self.seen_glossary = None
            self.seen_segments = None

        def transcribe(self, _: Path):
            return [{"position": 0, "speaker": "speaker_0", "text": raw, "start": 0, "end": 2}]

        def analyze(self, received, measured, glossary=None):
            self.seen_segments = received
            self.seen_glossary = glossary
            return analysis_factory(outcome="lost", funnel_stage="closed_lost")

    provider = Provider()
    processed, _, _, _ = run_provider_pipeline(provider, Path("ignored.wav"), entries)
    assert processed[0]["text"] == raw
    assert "Microsoft CRM" in processed[0]["normalized_text"]
    assert provider.seen_glossary == [entries[0].as_prompt_item()]

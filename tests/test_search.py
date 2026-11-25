from pathlib import Path

from app.linkedin.search import JobCard, dedupe, parse_cards

SAMPLE = Path(__file__).parent / "sample_search.html"


def test_parse_cards_from_real_page():
    cards = parse_cards(SAMPLE.read_text(encoding="utf-8"))
    assert len(cards) == 10
    first = cards[0]
    assert first.linkedin_id.isdigit()
    assert first.title and first.company and first.location
    assert first.url.startswith("https://") and "?" not in first.url
    assert first.posted_on is not None


def test_dedupe_skips_seen_and_repeats():
    a = JobCard("1", "AI Engineer", "X", "Pune", "u1", None)
    b = JobCard("2", "LLM Engineer", "Y", "Pune", "u2", None)
    out = dedupe([a, b, a], seen_ids={"2"})
    assert [c.linkedin_id for c in out] == ["1"]

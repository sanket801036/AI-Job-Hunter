from unittest.mock import patch

from app.judge import Verdict, apply_rules, judge, pre_filter

PROFILE = {
    "experience_years": 3,
    "max_years_ok": 5,
    "skills": ["Python", "RAG"],
    "locations_ok": ["Pune"],
    "titles_skip": ["Staff", "Principal", "Lead"],
    "skip_companies": ["JobSphere"],
}


def test_pre_filter_skips_titles_and_companies():
    assert pre_filter("Principal AI Engineer", "Krista", PROFILE) == "title says Principal"
    assert pre_filter("AI Engineer", "JobSphere India", PROFILE).startswith("company on skip list")
    assert pre_filter("AI Engineer", "Krista", PROFILE) is None
    # "Leading" must not match "Lead"
    assert pre_filter("AI Engineer - Leading Fintech", "X", PROFILE) is None


def test_rules_override_llm():
    v = Verdict(is_relevant=True, min_years=7, eligible=True, match_score=90)
    assert apply_rules(v, PROFILE).eligible is False
    assert "asks 7+ years" in v.red_flags

    v = Verdict(is_relevant=False, eligible=True)
    assert apply_rules(v, PROFILE).eligible is False

    v = Verdict(is_relevant=True, min_years=3, max_years=5, seniority="mid", eligible=True)
    assert apply_rules(v, PROFILE).eligible is True


def test_score_is_clamped():
    assert Verdict(is_relevant=True, match_score=140).match_score == 100
    assert Verdict(is_relevant=True, match_score="abc").match_score == 0


def test_judge_uses_llm_and_rules():
    llm_answer = Verdict(is_relevant=True, min_years=6, eligible=True, match_score=85)
    with patch("app.judge.complete_json", return_value=(llm_answer, "gemini")):
        v, provider = judge("AI Engineer", "X", "Pune", "6+ years", profile=PROFILE)
    assert provider == "gemini"
    assert v.eligible is False

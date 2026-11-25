from pathlib import Path

from app.linkedin.detail import parse_detail

HERE = Path(__file__).parent


def test_easy_apply_job():
    d = parse_detail((HERE / "sample_detail_easy.html").read_text(encoding="utf-8"))
    assert d.easy_apply is True
    assert d.apply_url == ""
    assert len(d.description) > 300
    assert "\n" in d.description  # paragraphs kept
    assert "applicant" in d.applicants
    assert d.seniority and d.employment_type


def test_company_site_job():
    d = parse_detail((HERE / "sample_detail_offsite.html").read_text(encoding="utf-8"))
    assert d.easy_apply is False
    assert len(d.description) > 300
    assert "applicant" in d.applicants


def test_hidden_apply_url_is_decoded():
    page = (
        '<div data-tracking-control-name="public_jobs_apply-link-offsite"></div>'
        '<code id="applyUrl"><!--"https://www.linkedin.com/jobs/view/externalApply/1?url='
        'https%3A%2F%2Fcareers.example.com%2Fjobs%2F42&amp;urlHash=x"--></code>'
    )
    d = parse_detail(page)
    assert d.easy_apply is False
    assert d.apply_url == "https://careers.example.com/jobs/42"

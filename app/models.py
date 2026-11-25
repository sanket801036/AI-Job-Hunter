"""Tables: what to search for, my resumes, jobs found, LLM verdicts, applications,
people I contact for referrals, and interview rounds."""
from datetime import datetime, timezone

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Integer, LargeBinary, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


def now() -> datetime:
    return datetime.now(timezone.utc)


class Resume(Base):
    """A resume uploaded from the dashboard. The file is kept in the database because
    the free Render disk is wiped on every deploy."""

    __tablename__ = "resumes"

    id: Mapped[int] = mapped_column(primary_key=True)
    label: Mapped[str] = mapped_column(String(100))  # e.g. "AI Engineer", "Full Stack"
    filename: Mapped[str] = mapped_column(String(300))
    content: Mapped[bytes] = mapped_column(LargeBinary)
    text: Mapped[str] = mapped_column(Text, default="")  # extracted text, sent to the LLM
    uploaded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class SearchProfile(Base):
    """One search I want running, e.g. "AI Engineer" or "Full Stack". Each one can use
    its own resume for the eligibility check. Only active profiles are searched."""

    __tablename__ = "search_profiles"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100), unique=True)
    keywords: Mapped[str] = mapped_column(String(500))  # comma separated
    hours: Mapped[int] = mapped_column(Integer, default=6)
    work_types: Mapped[str] = mapped_column(String(20), default="1,2,3")  # 1 on-site, 2 remote, 3 hybrid
    geo_id: Mapped[str] = mapped_column(String(20), default="102713980")  # India
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    under_10: Mapped[bool] = mapped_column(Boolean, default=False)  # only jobs with < 10 applicants
    resume_id: Mapped[int | None] = mapped_column(ForeignKey("resumes.id"))

    resume: Mapped[Resume | None] = relationship()

    @property
    def keyword_list(self) -> list[str]:
        return [k.strip() for k in self.keywords.split(",") if k.strip()]


class Job(Base):
    __tablename__ = "jobs"

    id: Mapped[int] = mapped_column(primary_key=True)
    linkedin_id: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    title: Mapped[str] = mapped_column(String(300))
    company: Mapped[str] = mapped_column(String(200), default="")
    location: Mapped[str] = mapped_column(String(200), default="")
    url: Mapped[str] = mapped_column(String(500))
    posted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    found_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    search_profile_id: Mapped[int | None] = mapped_column(ForeignKey("search_profiles.id"))

    # filled from the job detail page
    description: Mapped[str] = mapped_column(Text, default="")
    seniority: Mapped[str] = mapped_column(String(100), default="")
    employment_type: Mapped[str] = mapped_column(String(100), default="")
    applicants: Mapped[str] = mapped_column(String(100), default="")
    easy_apply: Mapped[bool | None] = mapped_column(Boolean)
    apply_url: Mapped[str] = mapped_column(String(1000), default="")

    # new -> evaluated -> notified, then my action: applied / skipped / saved
    status: Mapped[str] = mapped_column(String(20), default="new", index=True)

    search_profile: Mapped[SearchProfile | None] = relationship()
    evaluation: Mapped["Evaluation | None"] = relationship(back_populates="job", uselist=False)
    application: Mapped["Application | None"] = relationship(back_populates="job", uselist=False)


class Evaluation(Base):
    """What the LLM (plus fixed rules) decided about a job."""

    __tablename__ = "evaluations"

    id: Mapped[int] = mapped_column(primary_key=True)
    job_id: Mapped[int] = mapped_column(ForeignKey("jobs.id"), unique=True)
    is_relevant: Mapped[bool] = mapped_column(Boolean, default=False)
    eligible: Mapped[bool] = mapped_column(Boolean, default=False)
    match_score: Mapped[int] = mapped_column(Integer, default=0)
    min_years: Mapped[int | None] = mapped_column(Integer)
    max_years: Mapped[int | None] = mapped_column(Integer)
    seniority: Mapped[str] = mapped_column(String(30), default="")
    matched_skills: Mapped[list] = mapped_column(JSON, default=list)
    missing_skills: Mapped[list] = mapped_column(JSON, default=list)
    red_flags: Mapped[list] = mapped_column(JSON, default=list)
    reason: Mapped[str] = mapped_column(Text, default="")
    provider: Mapped[str] = mapped_column(String(30), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)

    job: Mapped[Job] = relationship(back_populates="evaluation")


class Application(Base):
    __tablename__ = "applications"

    id: Mapped[int] = mapped_column(primary_key=True)
    job_id: Mapped[int] = mapped_column(ForeignKey("jobs.id"), unique=True)
    resume_id: Mapped[int | None] = mapped_column(ForeignKey("resumes.id"))
    applied_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    platform: Mapped[str] = mapped_column(String(50), default="")  # Easy Apply / company site / referral
    ctc_told: Mapped[str] = mapped_column(String(50), default="")
    # applied, hr_screen, assessment, tech_1, tech_2, manager, offer, rejected, ghosted
    stage: Mapped[str] = mapped_column(String(30), default="applied", index=True)
    notes: Mapped[str] = mapped_column(Text, default="")
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now)

    job: Mapped[Job] = relationship(back_populates="application")
    resume: Mapped[Resume | None] = relationship()
    rounds: Mapped[list["InterviewRound"]] = relationship(
        back_populates="application", order_by="InterviewRound.scheduled_at"
    )
    referrals: Mapped[list["Referral"]] = relationship(back_populates="application")


class Contact(Base):
    """A person at a company I reached out to (recruiter, employee for a referral)."""

    __tablename__ = "contacts"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    company: Mapped[str] = mapped_column(String(200), index=True)
    role: Mapped[str] = mapped_column(String(200), default="")
    linkedin_url: Mapped[str] = mapped_column(String(500), default="")
    notes: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)

    referrals: Mapped[list["Referral"]] = relationship(back_populates="contact")


class Referral(Base):
    """One referral ask: who, for which job, with which resume and message, and what happened."""

    __tablename__ = "referrals"

    id: Mapped[int] = mapped_column(primary_key=True)
    contact_id: Mapped[int] = mapped_column(ForeignKey("contacts.id"))
    application_id: Mapped[int | None] = mapped_column(ForeignKey("applications.id"))
    resume_id: Mapped[int | None] = mapped_column(ForeignKey("resumes.id"))
    message: Mapped[str] = mapped_column(Text, default="")
    # connection_sent, connected, asked, referred, declined, no_reply
    status: Mapped[str] = mapped_column(String(30), default="connection_sent")
    sent_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now)

    contact: Mapped[Contact] = relationship(back_populates="referrals")
    application: Mapped[Application | None] = relationship(back_populates="referrals")
    resume: Mapped[Resume | None] = relationship()


class InterviewRound(Base):
    __tablename__ = "interview_rounds"

    id: Mapped[int] = mapped_column(primary_key=True)
    application_id: Mapped[int] = mapped_column(ForeignKey("applications.id"))
    name: Mapped[str] = mapped_column(String(100))  # HR screen, Tech 1, ...
    scheduled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    result: Mapped[str] = mapped_column(String(30), default="pending")  # pending, passed, failed
    notes: Mapped[str] = mapped_column(Text, default="")

    application: Mapped[Application] = relationship(back_populates="rounds")


class Company(Base):
    """My notes about a company, and whether the bot should ignore it."""

    __tablename__ = "companies"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200), unique=True, index=True)
    # direct employer, staffing / consulting, freelance marketplace, job board / aggregator
    category: Mapped[str] = mapped_column(String(30), default="")
    website: Mapped[str] = mapped_column(String(500), default="")
    blocked: Mapped[bool] = mapped_column(Boolean, default=False)
    notes: Mapped[str] = mapped_column(Text, default="")
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now)


class Setting(Base):
    """Small key/value store for things edited from the dashboard (e.g. extra skip words)."""

    __tablename__ = "settings"

    key: Mapped[str] = mapped_column(String(100), primary_key=True)
    value: Mapped[dict | list | str] = mapped_column(JSON)

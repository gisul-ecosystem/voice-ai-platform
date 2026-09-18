"""Deterministic JD/resume extractors (Milestone 1 v1).

Heuristic, provenance-preserving extraction. Low-confidence items stay
unapproved so creators must review before publish. LLM enrichment can replace
section parsing later without changing the JobIntelligence / CandidateProfile
contracts.
"""
from __future__ import annotations

import hashlib
import re
import uuid
from datetime import datetime
from typing import Literal

from models.brain import (
    CandidateClaim,
    CandidateProfile,
    ClaimType,
    ExperienceSummary,
    ExtractedItem,
    JobIntelligence,
    JobRoleSummary,
    ProfileType,
    SeniorityLevel,
    SourceReference,
)

_WS = re.compile(r"[ \t]+")
_MULTI_NL = re.compile(r"\n{3,}")
_BULLET = re.compile(r"^\s*(?:[-*•]|\d+[.)])\s+(.*\S)\s*$")
_YEAR_RANGE = re.compile(
    r"(?P<start>(?:19|20)\d{2})\s*[-–—to]+\s*(?P<end>(?:19|20)\d{2}|present|current)",
    re.IGNORECASE,
)

_JD_SECTION_ALIASES: dict[str, str] = {
    "responsibilities": "responsibilities",
    "duties": "responsibilities",
    "what you will do": "responsibilities",
    "role overview": "responsibilities",
    "requirements": "mandatory_requirements",
    "required": "mandatory_requirements",
    "must have": "mandatory_requirements",
    "mandatory": "mandatory_requirements",
    "qualifications": "mandatory_requirements",
    "preferred": "preferred_requirements",
    "nice to have": "preferred_requirements",
    "bonus": "preferred_requirements",
    "skills": "skills",
    "technical skills": "skills",
    "tools": "tools",
    "technologies": "tools",
    "tech stack": "tools",
    "knowledge": "knowledge",
    "outcomes": "expected_outcomes",
    "success metrics": "expected_outcomes",
    "scenarios": "work_scenarios",
}

_RESUME_SECTION_ALIASES: dict[str, str] = {
    "education": "education",
    "academic": "education",
    "experience": "professional_experience",
    "work experience": "professional_experience",
    "professional experience": "professional_experience",
    "employment": "professional_experience",
    "internship": "internships",
    "internships": "internships",
    "projects": "projects",
    "personal projects": "projects",
    "skills": "skills_claimed",
    "technical skills": "skills_claimed",
    "certifications": "certifications",
    "certificates": "certifications",
    "achievements": "achievements",
    "awards": "achievements",
    "languages": "languages",
}

_SENIORITY_PATTERNS: list[tuple[re.Pattern[str], SeniorityLevel]] = [
    (re.compile(r"\bintern\b", re.I), "intern"),
    (re.compile(r"\bjunior\b|\bentry[- ]level\b", re.I), "junior"),
    (re.compile(r"\bmid[- ]level\b|\bintermediate\b", re.I), "mid"),
    (re.compile(r"\bsenior\b|\bsr\.?\b", re.I), "senior"),
    (re.compile(r"\blead\b|\bstaff\b|\bprincipal\b", re.I), "lead"),
]


def normalize_document_text(raw: str) -> str:
    text = (raw or "").replace("\r\n", "\n").replace("\r", "\n")
    text = _WS.sub(" ", text)
    text = _MULTI_NL.sub("\n\n", text)
    return text.strip()


def _item_id(prefix: str, text: str) -> str:
    digest = hashlib.sha1(text.encode("utf-8")).hexdigest()[:10]
    return f"{prefix}_{digest}"


def _provenance(
    source: Literal["jd", "resume"],
    span: str,
    *,
    confidence: float,
) -> SourceReference:
    return SourceReference(
        source=source,
        source_span=span[:4_000],
        confidence=max(0.0, min(1.0, confidence)),
        explicit=True,
        confirmed=False,
    )


def _extracted(
    prefix: str,
    text: str,
    *,
    source: Literal["jd", "resume"],
    confidence: float,
) -> ExtractedItem:
    cleaned = text.strip()
    return ExtractedItem(
        id=_item_id(prefix, cleaned),
        text=cleaned[:4_000],
        provenance=_provenance(source, cleaned, confidence=confidence),
    )


def _heading_key(line: str, aliases: dict[str, str]) -> str | None:
    cleaned = re.sub(r"[:#]+$", "", line.strip()).strip().lower()
    cleaned = re.sub(r"\s+", " ", cleaned)
    if cleaned in aliases:
        return aliases[cleaned]
    if len(cleaned) <= 40:
        for alias, key in aliases.items():
            if cleaned.startswith(alias):
                return key
    return None


def _split_sections(text: str, aliases: dict[str, str]) -> dict[str, list[str]]:
    sections: dict[str, list[str]] = {}
    current = "_preamble"
    sections[current] = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        key = _heading_key(line, aliases)
        if key:
            current = key
            sections.setdefault(current, [])
            continue
        bullet = _BULLET.match(line)
        sections.setdefault(current, []).append(
            bullet.group(1).strip() if bullet else line
        )
    return sections


def _infer_seniority(text: str) -> SeniorityLevel:
    for pattern, level in _SENIORITY_PATTERNS:
        if pattern.search(text):
            return level
    return "mid"


def _infer_title(text: str, sections: dict[str, list[str]]) -> str:
    for line in text.splitlines()[:8]:
        cleaned = line.strip()
        if not cleaned or _heading_key(cleaned, _JD_SECTION_ALIASES):
            continue
        labeled = re.match(
            r"^(?:job\s*title|title|role|position)\s*[:\-]\s*(.+)$",
            cleaned,
            re.I,
        )
        if labeled:
            return labeled.group(1).strip()[:160]
        if 3 <= len(cleaned) <= 80 and not cleaned.endswith("."):
            return cleaned[:160]
    preamble = sections.get("_preamble") or []
    if preamble:
        return preamble[0][:160]
    return "Untitled role"


def _lines_to_items(
    lines: list[str],
    *,
    prefix: str,
    source: Literal["jd", "resume"],
    confidence: float,
    limit: int,
) -> list[ExtractedItem]:
    items: list[ExtractedItem] = []
    seen: set[str] = set()
    for line in lines:
        cleaned = line.strip(" -•*\t")
        if len(cleaned) < 3:
            continue
        key = cleaned.lower()
        if key in seen:
            continue
        seen.add(key)
        items.append(
            _extracted(prefix, cleaned, source=source, confidence=confidence)
        )
        if len(items) >= limit:
            break
    return items


def extract_job_intelligence(
    job_description: str,
    *,
    target_level: SeniorityLevel | None = None,
    domain: str | None = None,
) -> JobIntelligence:
    raw = normalize_document_text(job_description)
    if not raw:
        raise ValueError("job_description is required")
    sections = _split_sections(raw, _JD_SECTION_ALIASES)
    title = _infer_title(raw, sections)
    level = target_level or _infer_seniority(raw)
    skills = _lines_to_items(
        sections.get("skills") or [],
        prefix="jd_skill",
        source="jd",
        confidence=0.72,
        limit=80,
    )
    # Prefer comma-separated skill lines when no bullets.
    if not skills:
        for line in (sections.get("_preamble") or []) + (sections.get("skills") or []):
            if "," in line and len(line) < 300:
                for part in line.split(","):
                    piece = part.strip()
                    if len(piece) >= 2:
                        skills.append(
                            _extracted(
                                "jd_skill",
                                piece,
                                source="jd",
                                confidence=0.55,
                            )
                        )
                if skills:
                    break
        skills = skills[:80]

    return JobIntelligence(
        role=JobRoleSummary(
            title=title,
            domain=(domain.strip()[:120] if domain and domain.strip() else None),
            target_level=level,
        ),
        responsibilities=_lines_to_items(
            sections.get("responsibilities") or [],
            prefix="jd_resp",
            source="jd",
            confidence=0.7,
            limit=40,
        ),
        mandatory_requirements=_lines_to_items(
            sections.get("mandatory_requirements") or [],
            prefix="jd_req",
            source="jd",
            confidence=0.75,
            limit=40,
        ),
        preferred_requirements=_lines_to_items(
            sections.get("preferred_requirements") or [],
            prefix="jd_pref",
            source="jd",
            confidence=0.65,
            limit=40,
        ),
        knowledge=_lines_to_items(
            sections.get("knowledge") or [],
            prefix="jd_know",
            source="jd",
            confidence=0.6,
            limit=40,
        ),
        skills=skills,
        tools=_lines_to_items(
            sections.get("tools") or [],
            prefix="jd_tool",
            source="jd",
            confidence=0.7,
            limit=40,
        ),
        work_scenarios=_lines_to_items(
            sections.get("work_scenarios") or [],
            prefix="jd_scen",
            source="jd",
            confidence=0.55,
            limit=20,
        ),
        expected_outcomes=_lines_to_items(
            sections.get("expected_outcomes") or [],
            prefix="jd_out",
            source="jd",
            confidence=0.55,
            limit=20,
        ),
        raw_job_description=raw[:100_000],
        extraction_version="jd-extractor-v1",
        approved=False,
        approved_at=None,
    )


def _estimate_months(text: str) -> tuple[int, int]:
    professional = 0
    internship = 0
    lower = text.lower()
    for match in _YEAR_RANGE.finditer(text):
        start = int(match.group("start"))
        end_raw = match.group("end").lower()
        end = datetime.now().year if end_raw in {"present", "current"} else int(end_raw)
        months = max(0, (end - start) * 12)
        # Only inspect the same line / immediate left context so later
        # section headings like "Internships" do not reclassify roles.
        line_start = text.rfind("\n", 0, match.start()) + 1
        context = lower[line_start : match.end()]
        if re.search(r"\bintern(?:ship|ships)?\b", context):
            internship += min(months, 24)
        else:
            professional += min(months, 240)
    return professional, internship


def _profile_type(professional_months: int, internship_months: int) -> ProfileType:
    if professional_months >= 120:
        return "lead"
    if professional_months >= 72:
        return "senior"
    if professional_months >= 36:
        return "mid"
    if professional_months >= 12:
        return "junior"
    if internship_months > 0 and professional_months == 0:
        return "final_year_student"
    if professional_months == 0 and internship_months == 0:
        return "unknown"
    return "recent_graduate"


def _claim_type_for_section(section: str) -> ClaimType:
    mapping: dict[str, ClaimType] = {
        "education": "education",
        "professional_experience": "employment",
        "internships": "internship",
        "projects": "project",
        "skills_claimed": "skill",
        "certifications": "certification",
        "achievements": "achievement",
        "languages": "other",
    }
    return mapping.get(section, "other")


def extract_candidate_profile(resume_text: str) -> CandidateProfile:
    raw = normalize_document_text(resume_text)
    if not raw:
        raise ValueError("resume_text is required")
    sections = _split_sections(raw, _RESUME_SECTION_ALIASES)
    education = _lines_to_items(
        sections.get("education") or [],
        prefix="cv_edu",
        source="resume",
        confidence=0.7,
        limit=20,
    )
    experience = _lines_to_items(
        sections.get("professional_experience") or [],
        prefix="cv_exp",
        source="resume",
        confidence=0.72,
        limit=40,
    )
    internships = _lines_to_items(
        sections.get("internships") or [],
        prefix="cv_int",
        source="resume",
        confidence=0.7,
        limit=20,
    )
    projects = _lines_to_items(
        sections.get("projects") or [],
        prefix="cv_proj",
        source="resume",
        confidence=0.74,
        limit=40,
    )
    skills = _lines_to_items(
        sections.get("skills_claimed") or [],
        prefix="cv_skill",
        source="resume",
        confidence=0.68,
        limit=80,
    )
    if not skills:
        for line in sections.get("skills_claimed") or sections.get("_preamble") or []:
            if "," in line:
                for part in line.split(","):
                    piece = part.strip()
                    if len(piece) >= 2:
                        skills.append(
                            _extracted(
                                "cv_skill",
                                piece,
                                source="resume",
                                confidence=0.5,
                            )
                        )
                break
        skills = skills[:80]

    certifications = _lines_to_items(
        sections.get("certifications") or [],
        prefix="cv_cert",
        source="resume",
        confidence=0.7,
        limit=40,
    )
    achievements = _lines_to_items(
        sections.get("achievements") or [],
        prefix="cv_ach",
        source="resume",
        confidence=0.6,
        limit=40,
    )
    languages = _lines_to_items(
        sections.get("languages") or [],
        prefix="cv_lang",
        source="resume",
        confidence=0.65,
        limit=20,
    )

    claims: list[CandidateClaim] = []
    for section_name, items in (
        ("education", education),
        ("professional_experience", experience),
        ("internships", internships),
        ("projects", projects),
        ("skills_claimed", skills),
        ("certifications", certifications),
        ("achievements", achievements),
        ("languages", languages),
    ):
        claim_type = _claim_type_for_section(section_name)
        for item in items:
            claims.append(
                CandidateClaim(
                    claim_id=f"claim_{uuid.uuid4().hex[:12]}",
                    type=claim_type,
                    value=item.text,
                    provenance=item.provenance,
                )
            )
            if len(claims) >= 200:
                break
        if len(claims) >= 200:
            break

    professional_months, internship_months = _estimate_months(raw)
    summary = ExperienceSummary(
        professional_months=professional_months,
        internship_months=internship_months,
        profile_type=_profile_type(professional_months, internship_months),
    )
    return CandidateProfile(
        education=education,
        professional_experience=experience,
        internships=internships,
        projects=projects,
        skills_claimed=skills,
        certifications=certifications,
        achievements=achievements,
        languages=languages,
        experience_summary=summary,
        claims=claims,
        raw_resume_text=raw[:100_000],
        extraction_version="resume-extractor-v1",
        confirmed=False,
        confirmed_at=None,
    )

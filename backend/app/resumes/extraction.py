"""Deterministic extraction of candidate details from resume text.

Everything returned here is an unverified suggestion with the text it came from. Nothing is
saved automatically: HR reviews and edits suggestions before applying them to a candidate.
No external services are called and no text is logged.
"""

import re
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import date

from backend.app.screening.normalization import SKILL_SYNONYMS, normalize_skill

# Display names for common skills, in addition to the screening synonym table and the workspace's own skills.
COMMON_SKILLS = (
    "Python", "Java", "JavaScript", "TypeScript", "C++", "C#", "Go", "Rust", "Ruby", "PHP", "Kotlin", "Swift", "Scala", "R",
    "SQL", "PostgreSQL", "MySQL", "SQLite", "MongoDB", "Redis", "Elasticsearch", "Microsoft SQL Server", "Oracle",
    "HTML", "CSS", "React", "Angular", "Vue", "Node.js", "Django", "Flask", "FastAPI", "Spring", ".NET", "Express",
    "AWS", "Azure", "GCP", "Docker", "Kubernetes", "Terraform", "Ansible", "Linux", "Git", "CI/CD", "Jenkins", "GitHub Actions",
    "Machine Learning", "Artificial Intelligence", "Deep Learning", "NLP", "TensorFlow", "PyTorch", "scikit-learn", "Pandas", "NumPy",
    "Data Analysis", "Data Visualization", "Tableau", "Power BI", "Excel", "Spark", "Hadoop", "Airflow", "Kafka", "Snowflake",
    "REST", "GraphQL", "Microservices", "Agile", "Scrum", "Jira", "Figma", "Selenium", "Testing", "Project Management",
    "Communication", "Leadership", "Salesforce", "SAP", "Accounting", "Recruiting",
)
# Short or common-word skills only count inside a "Skills" section, to avoid false matches in prose.
AMBIGUOUS = {"go", "r", "c", "ai", "ml", "ts", "js", "py", "rest", "testing", "communication", "leadership", "express", "spring", "swift", "oracle", "excel", "scrum", "agile"}

EMAIL = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,24}\b")
PHONE = re.compile(r"(?<![\w])\+?\(?\d[\d\s().-]{6,22}\d(?![\w])")
YEAR = re.compile(r"\b(19[5-9]\d|20\d\d)\b")
STATED_EXPERIENCE = re.compile(
    r"(\d{1,2}(?:\.\d)?)\s*\+?\s*(?:years?|yrs?)\.?\s+(?:of\s+)?(?:(?:professional|relevant|industry|work|hands-on|total)\s+)?experience",
    re.IGNORECASE,
)
MONTH = r"(?:jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\.?"
DATE_RANGE = re.compile(
    rf"(?:(?P<m1>{MONTH})\s+)?(?P<y1>(?:19|20)\d\d)\s*(?:-|–|—|to|until)\s*(?:(?P<m2>{MONTH})\s+)?(?P<y2>(?:19|20)\d\d|present|current|now|today)",
    re.IGNORECASE,
)
DEGREES = (
    ("PhD", r"ph\.?\s?d\.?|doctor(?:ate| of philosophy)"),
    ("MBA", r"m\.?\s?b\.?\s?a\.?|master of business administration"),
    ("MSc", r"m\.?\s?sc\.?|master of science|m\.?s\.?(?=\s+in\b)"),
    ("MTech", r"m\.?\s?tech\.?|master of technology"),
    ("MA", r"master of arts|m\.a\.?"),
    ("MCA", r"m\.?c\.?a\.?|master of computer applications"),
    ("BSc", r"b\.?\s?sc\.?|bachelor of science|b\.?s\.?(?=\s+in\b)"),
    ("BTech", r"b\.?\s?tech\.?|bachelor of technology"),
    ("BE", r"bachelor of engineering|b\.e\.?(?=\s|,|$)"),
    ("BA", r"bachelor of arts|b\.a\.?(?=\s|,|$)"),
    ("BCA", r"b\.?c\.?a\.?|bachelor of computer applications"),
    ("Master's degree", r"master(?:'s)?(?: degree)?"),
    ("Bachelor's degree", r"bachelor(?:'s)?(?: degree)?"),
    ("Diploma", r"diploma"),
    ("Associate degree", r"associate(?:'s)? degree"),
)
DEGREE_PATTERN = re.compile(r"(?<![a-z])(" + "|".join(pattern for _, pattern in DEGREES) + r")(?![a-z])", re.IGNORECASE)
INSTITUTION = re.compile(r"([A-Z][\w.&'-]*(?:\s+(?:of|and|&|for|the|[A-Z][\w.&'-]*))*\s+(?:University|College|Institute|School|Academy|Polytechnic)(?:\s+of\s+[A-Z][\w.&'-]*(?:\s+[A-Z][\w.&'-]*)*)?|(?:University|Institute|College)\s+of\s+[A-Z][\w.&'-]*(?:\s+[A-Z][\w.&'-]*)*)")
SECTION_HEADER = re.compile(r"^\s*(technical\s+skills|skills|core\s+competencies|technologies|tools)\s*:?\s*(.*)$", re.IGNORECASE)
OTHER_HEADER = re.compile(r"^\s*(experience|work experience|employment|education|projects|certifications|summary|profile|languages|interests)\s*:?\s*$", re.IGNORECASE)


@dataclass
class ResumeSuggestions:
    full_name: dict | None = None
    emails: list[dict] = field(default_factory=list)
    phones: list[dict] = field(default_factory=list)
    skills: list[dict] = field(default_factory=list)
    education: list[dict] = field(default_factory=list)
    total_experience: dict | None = None

    def is_empty(self) -> bool:
        return not (self.full_name or self.emails or self.phones or self.skills or self.education or self.total_experience)

    def as_dict(self) -> dict:
        return {
            "full_name": self.full_name,
            "emails": self.emails,
            "phones": self.phones,
            "skills": self.skills,
            "education": self.education,
            "total_experience": self.total_experience,
        }


def _snippet(line: str, limit: int = 120) -> str:
    line = " ".join(line.split())
    return line if len(line) <= limit else line[: limit - 1] + "…"


def _lines(text: str) -> list[str]:
    return [" ".join(line.split()) for line in text.splitlines() if line.strip()]


def _guess_name(lines: list[str]) -> dict | None:
    for line in lines[:5]:
        words = line.split()
        if 2 <= len(words) <= 4 and len(line) <= 60 and all(re.fullmatch(r"[A-Z][a-zA-Z'.-]*", word) for word in words) and not DEGREE_PATTERN.search(line):
            if line.lower() in {"curriculum vitae", "resume", "professional summary"}:
                continue
            return {"value": line, "evidence": line, "confidence": "low"}
    return None


def _emails(text: str) -> list[dict]:
    found: dict[str, dict] = {}
    for line in _lines(text):
        for match in EMAIL.finditer(line):
            value = match.group(0).lower().strip(".")
            found.setdefault(value, {"value": value, "evidence": _snippet(line)})
    return list(found.values())[:5]


def _phones(text: str) -> list[dict]:
    found: dict[str, dict] = {}
    for line in _lines(text):
        for match in PHONE.finditer(line):
            value = " ".join(match.group(0).split())
            digits = re.sub(r"\D", "", value)
            if not 7 <= len(digits) <= 15 or DATE_RANGE.fullmatch(value) or re.fullmatch(r"(19|20)\d\d\s*[-–]\s*(19|20)\d\d", value):
                continue
            found.setdefault(digits, {"value": value, "evidence": _snippet(line)})
    return list(found.values())[:3]


def _skill_vocabulary(extra: Iterable[str]) -> dict[str, tuple[str, list[str]]]:
    """canonical -> (display name, surface forms to search for)."""
    vocabulary: dict[str, tuple[str, list[str]]] = {}

    def add(display: str):
        canonical = normalize_skill(display)
        if not canonical:
            return
        current = vocabulary.get(canonical)
        forms = set(current[1]) if current else set()
        forms.update({display.lower(), canonical})
        forms.update(SKILL_SYNONYMS.get(canonical, ()))
        vocabulary[canonical] = (current[0] if current else display, sorted(forms, key=len, reverse=True))

    for name in extra:  # Workspace skills first so their display names win.
        add(name)
    for name in COMMON_SKILLS:
        add(name)
    for canonical in SKILL_SYNONYMS:
        add(canonical)
    return vocabulary


def _skill_section_lines(lines: list[str]) -> set[int]:
    in_section = False
    indexes: set[int] = set()
    for index, line in enumerate(lines):
        header = SECTION_HEADER.match(line)
        if header:
            in_section = True
            if header.group(2):
                indexes.add(index)
            continue
        if OTHER_HEADER.match(line):
            in_section = False
            continue
        if in_section:
            indexes.add(index)
    return indexes


def _skills(text: str, extra_vocabulary: Iterable[str]) -> list[dict]:
    lines = _lines(text)
    section = _skill_section_lines(lines)
    found: dict[str, dict] = {}
    for canonical, (display, forms) in _skill_vocabulary(extra_vocabulary).items():
        ambiguous = canonical in AMBIGUOUS or len(canonical) <= 2
        for form in forms:
            pattern = re.compile(r"(?<![a-z0-9+#.])" + re.escape(form) + r"(?![a-z0-9+#]|\.[a-z0-9])", re.IGNORECASE)
            hit = next((index for index, line in enumerate(lines) if (not ambiguous or index in section) and pattern.search(line)), None)
            if hit is not None:
                found[canonical] = {"value": display, "evidence": _snippet(lines[hit])}
                break
    return sorted(found.values(), key=lambda item: item["value"].lower())[:60]


def _degree_label(matched: str) -> str:
    for label, pattern in DEGREES:
        if re.fullmatch(pattern, matched, re.IGNORECASE):
            return label
    return matched.strip()


def _education(text: str) -> list[dict]:
    lines = _lines(text)
    results: list[dict] = []
    for index, line in enumerate(lines):
        match = DEGREE_PATTERN.search(line)
        if not match:
            continue
        rest = line[match.end():]
        field_match = re.match(r"\s*(?:degree\s+)?(?:\(|,)?\s*(?:in|of)\s+([A-Za-z&/ .'-]+?)(?=\s*(?:,|;|\||-|–|—|\(|\bat\b|\bfrom\b|\d|$))", rest, re.IGNORECASE)
        following = lines[index + 1] if index + 1 < len(lines) and not DEGREE_PATTERN.search(lines[index + 1]) else ""
        # Prefer details on the degree's own line; fall back to the next line (common two-line layout).
        institution = INSTITUTION.search(line) or (INSTITUTION.search(following) if following else None)
        years = YEAR.findall(line) or YEAR.findall(following)
        results.append({
            "degree": _degree_label(match.group(1)),
            "field_of_study": field_match.group(1).strip(" .") if field_match else None,
            "institution": institution.group(1).strip() if institution else None,
            "graduation_year": int(years[-1]) if years else None,
            "evidence": _snippet(line),
        })
        if len(results) >= 10:
            break
    unique: dict[tuple, dict] = {}
    for item in results:
        unique.setdefault((item["degree"], item["field_of_study"], item["graduation_year"]), item)
    return list(unique.values())


def _month(value: str | None, default: int) -> int:
    if not value:
        return default
    names = ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"]
    return names.index(value[:3].lower()) + 1


def _experience(text: str, today: date) -> dict | None:
    lines = _lines(text)
    stated = [(float(match.group(1)), line) for line in lines for match in STATED_EXPERIENCE.finditer(line)]
    stated = [(years, line) for years, line in stated if 0 < years <= 60]
    if stated:
        years, line = max(stated, key=lambda item: item[0])
        return {"value": years, "method": "stated", "evidence": _snippet(line)}
    intervals: list[tuple[int, int]] = []
    evidence: list[str] = []
    current = today.year * 12 + today.month
    for line in lines:
        if DEGREE_PATTERN.search(line):
            continue  # education dates are not work experience
        for match in DATE_RANGE.finditer(line):
            start = int(match.group("y1")) * 12 + _month(match.group("m1"), 1)
            end_year = match.group("y2").lower()
            # Exclusive month bounds: an explicit end month counts in full ("2015 - 2020" is 72 months).
            end = current if end_year in {"present", "current", "now", "today"} else int(end_year) * 12 + _month(match.group("m2"), 12) + 1
            if end_year.isdigit() and int(end_year) <= today.year:
                end = min(end, current + 1)  # "2024 - 2026" written in 2026 means "until now", not December
            if start < end <= current + 1 and end - start <= 50 * 12:
                intervals.append((start, end))
                evidence.append(_snippet(match.group(0)))
    if not intervals:
        return None
    merged: list[list[int]] = []
    for start, end in sorted(intervals):
        if merged and start <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], end)
        else:
            merged.append([start, end])
    months = sum(end - start for start, end in merged)
    years = round(min(80, months / 12), 1)
    if years <= 0:
        return None
    return {"value": years, "method": "date_ranges", "evidence": "; ".join(evidence[:4])}


def extract_details(text: str, *, skill_vocabulary: Iterable[str] = (), today: date | None = None) -> ResumeSuggestions:
    lines = _lines(text)
    return ResumeSuggestions(
        full_name=_guess_name(lines),
        emails=_emails(text),
        phones=_phones(text),
        skills=_skills(text, skill_vocabulary),
        education=_education(text),
        total_experience=_experience(text, today or date.today()),
    )

"""Deterministic normalization for skills and qualifications.

Synonyms are explicit: a skill only matches another spelling when that spelling
is listed below. There is no fuzzy or inferred matching. To add a synonym, add
the alias under its canonical name; the module refuses to load if an alias is
claimed by two canonical names.
"""

import re
from collections.abc import Iterable

# canonical name -> aliases (all lowercase, single-spaced)
SKILL_SYNONYMS: dict[str, tuple[str, ...]] = {
    "javascript": ("js", "ecmascript"),
    "typescript": ("ts",),
    "python": ("py", "python3"),
    "postgresql": ("postgres", "postgres sql", "psql"),
    "microsoft sql server": ("mssql", "sql server"),
    "aws": ("amazon web services",),
    "gcp": ("google cloud platform", "google cloud"),
    "azure": ("microsoft azure",),
    "machine learning": ("ml",),
    "artificial intelligence": ("ai",),
    "kubernetes": ("k8s",),
    "node.js": ("node", "nodejs"),
    "react": ("reactjs", "react.js"),
    "c#": ("csharp", "c sharp"),
    "go": ("golang",),
}

# Whole-phrase replacements applied to qualification text before token matching.
QUALIFICATION_SYNONYMS: dict[str, tuple[str, ...]] = {
    "bsc": ("bachelor of science", "b sc", "bs"),
    "msc": ("master of science", "m sc", "ms"),
    "ba": ("bachelor of arts", "b a"),
    "ma": ("master of arts", "m a"),
    "btech": ("bachelor of technology", "b tech"),
    "mtech": ("master of technology", "m tech"),
    "be": ("bachelor of engineering", "b e"),
    "me": ("master of engineering", "m e"),
    "mba": ("master of business administration",),
    "bca": ("bachelor of computer applications",),
    "mca": ("master of computer applications",),
    "phd": ("doctor of philosophy", "ph d", "doctorate"),
}

# Connecting words ignored when comparing qualification tokens ("BSc in CS" == "BSc CS").
QUALIFICATION_STOPWORDS = frozenset({"in", "of", "and", "the", "a", "an", "&", "with"})


def _build_alias_map(synonyms: dict[str, tuple[str, ...]]) -> dict[str, str]:
    alias_map: dict[str, str] = {}
    for canonical, aliases in synonyms.items():
        for alias in (canonical, *aliases):
            owner = alias_map.setdefault(alias, canonical)
            if owner != canonical:
                raise ValueError(f"Synonym '{alias}' is mapped to both '{owner}' and '{canonical}'")
    return alias_map


_SKILL_ALIASES = _build_alias_map(SKILL_SYNONYMS)
_QUALIFICATION_PATTERNS = [
    (re.compile(rf"(?<!\S){re.escape(alias)}(?!\S)"), canonical)
    for canonical, aliases in QUALIFICATION_SYNONYMS.items()
    for alias in sorted(aliases, key=len, reverse=True)
]
_QUALIFICATION_PATTERNS.sort(key=lambda item: len(item[0].pattern), reverse=True)
_QUALIFICATION_PUNCTUATION = re.compile(r"[.,;:()/\-]+")


def normalize_text(value: str) -> str:
    return " ".join(str(value).lower().split())


def normalize_skill(value: str) -> str:
    """Lowercase, collapse whitespace, and map an explicit alias to its canonical skill."""
    text = normalize_text(value)
    return _SKILL_ALIASES.get(text, text)


def normalize_items(items: Iterable[str] | str | None) -> set[str]:
    """Normalize a collection (or comma/semicolon separated string) of skills into a set."""
    if items is None:
        return set()
    values = items.replace(";", ",").split(",") if isinstance(items, str) else items
    return {normalized for normalized in (normalize_skill(value) for value in values) if normalized}


def qualification_tokens(value: str) -> frozenset[str]:
    """Token set for a qualification or education entry, with degree abbreviations canonicalized."""
    text = normalize_text(_QUALIFICATION_PUNCTUATION.sub(" ", str(value).lower()))
    for pattern, canonical in _QUALIFICATION_PATTERNS:
        text = pattern.sub(canonical, text)
    return frozenset(token for token in text.split() if token not in QUALIFICATION_STOPWORDS)

"""Explainable, job-specific candidate scoring."""

from difflib import SequenceMatcher
from typing import Any


DEFAULT_WEIGHTS = {
    "required_skills": 50.0,
    "preferred_skills": 20.0,
    "experience": 20.0,
    "qualifications": 10.0,
}

SKILL_SYNONYMS = {
    "js": "javascript",
    "py": "python",
    "postgres": "postgresql",
    "postgres sql": "postgresql",
    "amazon web services": "aws",
    "google cloud platform": "gcp",
    "ml": "machine learning",
    "ai": "artificial intelligence",
}


def normalize_items(items: Any) -> set[str]:
    if items is None:
        return set()
    if isinstance(items, str):
        values = items.replace(";", ",").split(",")
    else:
        values = items

    normalized = set()
    for value in values:
        item = " ".join(str(value).strip().lower().split())
        if item:
            normalized.add(SKILL_SYNONYMS.get(item, item))
    return normalized


def _match_items(candidate_items: set[str], target_items: set[str]) -> tuple[list[str], list[str]]:
    matched: list[str] = []
    missing: list[str] = []
    remaining = set(candidate_items)
    for target in sorted(target_items):
        exact_match = next((item for item in remaining if item == target), None)
        if exact_match is None:
            exact_match = next(
                (
                    item
                    for item in remaining
                    if SequenceMatcher(None, item, target).ratio() >= 0.88
                ),
                None,
            )
        if exact_match is None:
            missing.append(target)
        else:
            matched.append(target)
            remaining.remove(exact_match)
    return matched, missing


def _skill_coverage(matched: list[str], targets: set[str], weights: Any) -> float:
    configured = normalize_items(weights.keys()) if isinstance(weights, dict) else set()
    if not configured:
        return len(matched) / len(targets) * 100 if targets else 0.0
    normalized_weights = {
        next(iter(normalize_items([name]))): float(weight)
        for name, weight in weights.items()
        if normalize_items([name])
    }
    total_weight = sum(normalized_weights.get(target, 0.0) for target in targets)
    if total_weight <= 0:
        return 0.0
    return sum(normalized_weights.get(skill, 0.0) for skill in matched) / total_weight * 100


def calculate_match_score(candidate: dict[str, Any], job: dict[str, Any]) -> dict[str, Any]:
    """Return a 0-100 score and the evidence contributing to it.

    Components without job criteria are omitted and the remaining weights are
    normalized to 100. Required skills always remain in the denominator; an
    absent candidate skill list therefore scores zero instead of appearing as
    a perfect match. Missing candidate qualifications are excluded unless the
    job has qualification criteria, in which case they score zero.
    """
    required = normalize_items(job.get("required_skills"))
    preferred = normalize_items(job.get("preferred_skills"))
    candidate_skills = normalize_items(candidate.get("skills"))
    qualifications = normalize_items(job.get("required_qualifications"))
    candidate_qualifications = normalize_items(candidate.get("education"))

    required_matched, required_missing = _match_items(candidate_skills, required)
    preferred_matched, preferred_missing = _match_items(candidate_skills, preferred)

    weights = dict(DEFAULT_WEIGHTS)
    weights.update(job.get("weights") or {})
    components: dict[str, dict[str, Any]] = {}
    active_weights = 0.0

    if required:
        components["required_skills"] = {
            "weight": float(weights["required_skills"]),
            "score": _skill_coverage(required_matched, required, job.get("required_skill_weights")),
            "matched": required_matched,
            "missing": required_missing,
        }
        active_weights += float(weights["required_skills"])
    if preferred:
        components["preferred_skills"] = {
            "weight": float(weights["preferred_skills"]),
            "score": _skill_coverage(preferred_matched, preferred, job.get("preferred_skill_weights")),
            "matched": preferred_matched,
            "missing": preferred_missing,
        }
        active_weights += float(weights["preferred_skills"])

    minimum_experience = max(0.0, float(job.get("min_experience") or 0))
    if minimum_experience > 0:
        years = max(0.0, float(candidate.get("experience") or 0))
        experience_score = min(years / minimum_experience, 1.0) * 100
        components["experience"] = {
            "weight": float(weights["experience"]),
            "score": experience_score,
            "candidate_years": years,
            "required_years": minimum_experience,
        }
        active_weights += float(weights["experience"])

    if qualifications:
        qualification_matched, qualification_missing = _match_items(
            candidate_qualifications, qualifications
        )
        components["qualifications"] = {
            "weight": float(weights["qualifications"]),
            "score": len(qualification_matched) / len(qualifications) * 100,
            "matched": qualification_matched,
            "missing": qualification_missing,
        }
        active_weights += float(weights["qualifications"])

    if active_weights:
        score = sum(
            component["score"] * component["weight"]
            for component in components.values()
        ) / active_weights
    else:
        score = 0.0

    matched_skills = sorted(set(required_matched + preferred_matched))
    missing_skills = sorted(set(required_missing + preferred_missing))
    return {
        "score": round(max(0.0, min(100.0, score)), 1),
        "components": components,
        "matched_skills": matched_skills,
        "missing_skills": missing_skills,
        "incomplete": (
            not bool(candidate_skills)
            or (minimum_experience > 0 and candidate.get("experience") is None)
            or (bool(qualifications) and not bool(candidate_qualifications))
        ),
        "weights_normalized": bool(active_weights and active_weights != 100.0),
    }
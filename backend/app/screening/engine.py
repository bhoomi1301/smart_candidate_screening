"""Explainable, deterministic candidate-to-job screening.

The engine is a pure function of its inputs: no database access, no randomness,
no external services. See README "Screening engine" for the exact formula.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from backend.app.screening.normalization import normalize_skill, qualification_tokens

SCORING_VERSION = "screening-v2"
COMPONENTS = ("required_skills", "preferred_skills", "experience", "qualifications")
DEFAULT_WEIGHTS: dict[str, Decimal] = {
    "required_skills": Decimal("50"),
    "preferred_skills": Decimal("20"),
    "experience": Decimal("20"),
    "qualifications": Decimal("10"),
}
DECISION_NOTICE = (
    "This score ranks applicants to support HR review. It does not make hiring decisions; "
    "application status changes are always made by a person."
)

EVALUATED = "evaluated"
NOT_APPLICABLE = "not_applicable"
MISSING_DATA = "missing_data"

ELIGIBLE = "eligible"
NOT_ELIGIBLE = "not_eligible"
UNDETERMINED = "undetermined"

HUNDRED = Decimal("100")
ZERO = Decimal("0")


class InvalidWeightsError(ValueError):
    pass


@dataclass(frozen=True)
class QualificationCriterion:
    name: str
    is_mandatory: bool = True
    weight: Decimal | None = None


@dataclass(frozen=True)
class JobCriteria:
    required_skills: Sequence[str]
    preferred_skills: Sequence[str] = ()
    required_skill_weights: Mapping[str, Decimal] = field(default_factory=dict)
    preferred_skill_weights: Mapping[str, Decimal] = field(default_factory=dict)
    minimum_experience: Decimal = ZERO
    qualifications: Sequence[QualificationCriterion] = ()
    weights: Mapping[str, Decimal] = field(default_factory=lambda: dict(DEFAULT_WEIGHTS))


@dataclass(frozen=True)
class CandidateEvidence:
    skills: Sequence[str]
    experience_years: Decimal | None
    education: Sequence[str]


@dataclass(frozen=True)
class Assessment:
    score: Decimal
    eligibility: str
    assessment_status: str
    matched_skills: list[str]
    missing_mandatory_skills: list[str]
    breakdown: dict[str, Any]


def _decimal(value: Any) -> Decimal:
    return value if isinstance(value, Decimal) else Decimal(str(value))


def _round(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _number(value: Decimal | None) -> float | None:
    return None if value is None else float(_round(value))


def validate_weights(weights: Mapping[str, Any]) -> dict[str, Decimal]:
    """Weights must name exactly the four components, be 0-100, total 100, and weight required skills above 0."""
    if set(weights) != set(COMPONENTS):
        raise InvalidWeightsError(f"Weights must define exactly: {', '.join(COMPONENTS)}")
    parsed = {key: _decimal(weights[key]) for key in COMPONENTS}
    if any(value < ZERO or value > HUNDRED for value in parsed.values()):
        raise InvalidWeightsError("Each weight must be between 0 and 100")
    if sum(parsed.values()) != HUNDRED:
        raise InvalidWeightsError("Weights must total 100")
    if parsed["required_skills"] <= ZERO:
        raise InvalidWeightsError("Required skills weight must be greater than 0")
    return parsed


def _skill_targets(skills: Sequence[str], weights: Mapping[str, Any]) -> dict[str, Decimal]:
    """Canonical skill -> relative weight. Without explicit weights every skill counts equally."""
    targets = {normalize_skill(name): Decimal("1") for name in skills if normalize_skill(name)}
    if weights:
        explicit = {normalize_skill(name): _decimal(value) for name, value in weights.items()}
        if set(explicit) != set(targets) or sum(explicit.values()) <= ZERO:
            raise InvalidWeightsError("Skill weights must cover each configured skill and total more than 0")
        targets = {name: explicit[name] for name in targets}
    return targets


def _skill_component(targets: dict[str, Decimal], candidate_skills: set[str]) -> dict[str, Any]:
    matched = sorted(name for name in targets if name in candidate_skills)
    missing = sorted(name for name in targets if name not in candidate_skills)
    if not targets:
        return {"status": NOT_APPLICABLE, "score": None, "matched": [], "missing": []}
    if not candidate_skills:
        return {"status": MISSING_DATA, "score": ZERO, "matched": [], "missing": missing}
    score = sum((targets[name] for name in matched), ZERO) / sum(targets.values()) * HUNDRED
    return {"status": EVALUATED, "score": score, "matched": matched, "missing": missing}


def _experience_component(required: Decimal, years: Decimal | None) -> dict[str, Any]:
    details = {
        "candidate_years": _number(years),
        "required_years": _number(required),
        "difference_years": None if years is None else _number(years - required),
        "meets_requirement": None if years is None else years >= required,
        "rule": "100 if candidate_years >= required_years, else 100 * candidate_years / required_years; capped at 100",
    }
    if required <= ZERO:
        return {"status": NOT_APPLICABLE, "score": None, **details}
    if years is None:
        return {"status": MISSING_DATA, "score": ZERO, **details}
    score = HUNDRED if years >= required else years / required * HUNDRED
    return {"status": EVALUATED, "score": score, **details}


def _qualification_component(criteria: Sequence[QualificationCriterion], education: Sequence[str]) -> dict[str, Any]:
    entries = [(entry, qualification_tokens(entry)) for entry in education if qualification_tokens(entry)]
    use_weights = any(item.weight is not None for item in criteria)
    evidence = []
    earned = total = ZERO
    for item in criteria:
        tokens = qualification_tokens(item.name)
        source = next((text for text, entry_tokens in entries if tokens and tokens <= entry_tokens), None)
        # Weights are all-or-none (enforced by the job schema); unweighted criteria count equally.
        weight = (ZERO if item.weight is None else _decimal(item.weight)) if use_weights else Decimal("1")
        total += weight
        earned += weight if source else ZERO
        evidence.append({
            "criterion": item.name,
            "is_mandatory": item.is_mandatory,
            "weight": _number(weight) if use_weights else None,
            "matched": source is not None if entries else None,
            "evidence": source,
        })
    if not criteria:
        return {"status": NOT_APPLICABLE, "score": None, "evidence": []}
    if not entries:
        return {"status": MISSING_DATA, "score": ZERO, "evidence": evidence}
    score = earned / total * HUNDRED if total > ZERO else ZERO
    return {"status": EVALUATED, "score": score, "evidence": evidence}


def evaluate(candidate: CandidateEvidence, job: JobCriteria) -> Assessment:
    weights = validate_weights(job.weights)
    candidate_skills = {normalize_skill(name) for name in candidate.skills if normalize_skill(name)}
    years = None if candidate.experience_years is None else max(ZERO, _decimal(candidate.experience_years))
    required_years = max(ZERO, _decimal(job.minimum_experience))

    raw = {
        "required_skills": _skill_component(_skill_targets(job.required_skills, job.required_skill_weights), candidate_skills),
        "preferred_skills": _skill_component(_skill_targets(job.preferred_skills, job.preferred_skill_weights), candidate_skills),
        "experience": _experience_component(required_years, years),
        "qualifications": _qualification_component(job.qualifications, candidate.education),
    }
    if raw["required_skills"]["status"] == NOT_APPLICABLE:
        raise InvalidWeightsError("A job needs at least one required skill to be screened")

    applicable_total = sum((weights[name] for name, part in raw.items() if part["status"] != NOT_APPLICABLE), ZERO)
    score = upper_bound = ZERO
    components: dict[str, Any] = {}
    for name in COMPONENTS:
        part = dict(raw[name])
        effective = ZERO if part["status"] == NOT_APPLICABLE else weights[name] / applicable_total * HUNDRED
        points = ZERO if part["score"] is None else effective * part["score"] / HUNDRED
        score += points
        upper_bound += effective if part["status"] == MISSING_DATA else points
        part.update(
            configured_weight=_number(weights[name]),
            effective_weight=_number(effective),
            score=_number(part["score"]),
            points=_number(points),
        )
        components[name] = part

    warnings: list[dict[str, str]] = []
    failures: list[str] = []
    undetermined: list[str] = []

    required = raw["required_skills"]
    if required["status"] == MISSING_DATA:
        undetermined.append("required_skills")
        warnings.append({"code": "missing_skill_data", "message": "Candidate has no skills recorded; skill components score 0 until skills are added."})
    elif required["missing"]:
        failures.append("required_skills")
        warnings.append({"code": "missing_mandatory_skills", "message": "Missing required skills: " + ", ".join(required["missing"])})

    experience = raw["experience"]
    if experience["status"] == MISSING_DATA:
        undetermined.append("experience")
        warnings.append({"code": "missing_experience_data", "message": "Candidate experience is not recorded; experience scores 0 until it is added."})
    elif experience["status"] == EVALUATED and not experience["meets_requirement"]:
        failures.append("experience")
        warnings.append({"code": "below_minimum_experience", "message": f"Candidate has {experience['candidate_years']} of {experience['required_years']} required years."})

    qualifications = raw["qualifications"]
    mandatory_missing = [item["criterion"] for item in qualifications["evidence"] if item["is_mandatory"] and item["matched"] is False]
    has_mandatory = any(item["is_mandatory"] for item in qualifications["evidence"])
    if qualifications["status"] == MISSING_DATA:
        if has_mandatory:
            undetermined.append("qualifications")
        warnings.append({"code": "missing_education_data", "message": "Candidate has no education or qualifications recorded; qualifications score 0 until they are added."})
    elif mandatory_missing:
        failures.append("qualifications")
        warnings.append({"code": "missing_mandatory_qualifications", "message": "Missing mandatory qualifications: " + ", ".join(mandatory_missing)})

    not_applicable = [name for name in COMPONENTS if raw[name]["status"] == NOT_APPLICABLE]
    if not_applicable:
        warnings.append({"code": "weights_redistributed", "message": "No job criteria for " + ", ".join(not_applicable) + "; their weight was shared proportionally across the other components."})

    eligibility = NOT_ELIGIBLE if failures else UNDETERMINED if undetermined else ELIGIBLE
    incomplete = any(raw[name]["status"] == MISSING_DATA for name in COMPONENTS)
    final_score = _round(min(HUNDRED, max(ZERO, score)))
    matched_skills = sorted(set(required["matched"]) | set(raw["preferred_skills"]["matched"]))
    breakdown = {
        "scoring_version": SCORING_VERSION,
        "score": float(final_score),
        "score_upper_bound": float(_round(min(HUNDRED, upper_bound))),
        "assessment_status": "incomplete" if incomplete else "complete",
        "eligibility": eligibility,
        "eligibility_failures": failures,
        "undetermined_criteria": undetermined,
        "weights": {name: _number(weights[name]) for name in COMPONENTS},
        "components": components,
        "matched_skills": matched_skills,
        "missing_mandatory_skills": required["missing"],
        "preferred_skills_matched": raw["preferred_skills"]["matched"],
        "preferred_skills_missing": raw["preferred_skills"]["missing"],
        "experience": {key: experience[key] for key in ("candidate_years", "required_years", "difference_years", "meets_requirement")},
        "qualification_evidence": qualifications["evidence"],
        "warnings": warnings,
        "decision_notice": DECISION_NOTICE,
    }
    return Assessment(
        score=final_score,
        eligibility=eligibility,
        assessment_status=breakdown["assessment_status"],
        matched_skills=matched_skills,
        missing_mandatory_skills=required["missing"],
        breakdown=breakdown,
    )

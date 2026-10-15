"""Engine tests. Expected values are calculated by hand in each test's comments.

Formula: effective_weight_i = configured_i * 100 / sum(configured weights of applicable components)
         score = sum(effective_weight_i * component_score_i / 100), rounded half-up to 2 decimals.
"""

from decimal import Decimal

import pytest

from backend.app.screening import normalization
from backend.app.screening.engine import CandidateEvidence, InvalidWeightsError, JobCriteria, QualificationCriterion, evaluate, validate_weights
from backend.app.screening.normalization import normalize_skill, qualification_tokens

D = Decimal


def candidate(skills=(), years=None, education=()):
    return CandidateEvidence(skills=list(skills), experience_years=None if years is None else D(str(years)), education=list(education))


def job(required, preferred=(), min_years=0, qualifications=(), weights=None, **kwargs):
    extra = {"weights": weights} if weights is not None else {}
    return JobCriteria(required_skills=list(required), preferred_skills=list(preferred), minimum_experience=D(str(min_years)), qualifications=list(qualifications), **extra, **kwargs)


def component(result, name):
    return result.breakdown["components"][name]


def test_perfect_match_scores_100_and_is_eligible():
    result = evaluate(
        candidate(["Python", "SQL", "Docker"], 5, ["BSc Computer Science"]),
        job(["Python", "SQL"], ["Docker"], 3, [QualificationCriterion("BSc Computer Science")]),
    )
    # 50*1 + 20*1 + 20*1 + 10*1 = 100
    assert result.score == D("100.00")
    assert result.eligibility == "eligible"
    assert result.assessment_status == "complete"
    assert result.breakdown["warnings"] == []
    assert result.missing_mandatory_skills == []
    assert {name: component(result, name)["points"] for name in ("required_skills", "preferred_skills", "experience", "qualifications")} == {
        "required_skills": 50.0, "preferred_skills": 20.0, "experience": 20.0, "qualifications": 10.0,
    }


def test_partial_match_matches_hand_calculation():
    result = evaluate(
        candidate(["Python", "SQL", "Golang"], 3, ["MSc Data Science"]),
        job(["Python", "SQL", "AWS", "Docker"], ["Kubernetes", "Go"], 4, [QualificationCriterion("BSc")]),
    )
    # required 2/4 = 50% -> 25.00; preferred 1/2 (golang = go) = 50% -> 10.00
    # experience 3/4 = 75% -> 15.00; qualification BSc vs MSc = 0% -> 0.00; total 50.00
    assert result.score == D("50.00")
    assert component(result, "required_skills")["score"] == 50.0
    assert component(result, "preferred_skills")["matched"] == ["go"]
    assert component(result, "experience")["score"] == 75.0
    assert component(result, "qualifications")["score"] == 0.0
    assert result.missing_mandatory_skills == ["aws", "docker"]
    assert result.breakdown["preferred_skills_missing"] == ["kubernetes"]
    assert result.eligibility == "not_eligible"
    assert result.breakdown["eligibility_failures"] == ["required_skills", "experience", "qualifications"]
    assert result.breakdown["experience"] == {"candidate_years": 3.0, "required_years": 4.0, "difference_years": -1.0, "meets_requirement": False}


def test_zero_match_scores_zero_without_being_incomplete():
    result = evaluate(
        candidate(["Excel"], 0, ["BA History"]),
        job(["Python"], ["Java"], 2, [QualificationCriterion("PhD")]),
    )
    assert result.score == D("0.00")
    assert result.assessment_status == "complete"
    assert result.eligibility == "not_eligible"
    assert result.breakdown["score_upper_bound"] == 0.0


def test_missing_mandatory_skills_reduce_score_and_fail_eligibility():
    result = evaluate(candidate(["Python", "SQL"], 10), job(["Python", "SQL", "Docker"], min_years=2))
    # applicable weights: required 50 + experience 20 = 70
    # required effective 50/70*100 = 71.428571..., score 2/3 -> 47.619047...
    # experience effective 20/70*100 = 28.571428..., capped at 100% -> 28.571428...
    # total 76.190476... -> 76.19
    assert result.score == D("76.19")
    assert component(result, "required_skills")["effective_weight"] == 71.43
    assert component(result, "experience")["effective_weight"] == 28.57
    assert result.missing_mandatory_skills == ["docker"]
    assert result.eligibility == "not_eligible"
    codes = [warning["code"] for warning in result.breakdown["warnings"]]
    assert codes == ["missing_mandatory_skills", "weights_redistributed"]


def test_job_without_preferred_skills_redistributes_weight_without_division_by_zero():
    result = evaluate(
        candidate(["Python"], 1, ["BSc Physics"]),
        job(["Python"], [], 2, [QualificationCriterion("BSc")]),
    )
    # applicable 50 + 20 + 10 = 80 -> effective 62.5 / 25 / 12.5
    # required 100% -> 62.5; experience 1/2 -> 12.5; qualification BSc in "BSc Physics" -> 12.5; total 87.5
    assert result.score == D("87.50")
    preferred = component(result, "preferred_skills")
    assert preferred == {**preferred, "status": "not_applicable", "score": None, "effective_weight": 0.0, "points": 0.0}
    assert result.breakdown["qualification_evidence"][0]["evidence"] == "BSc Physics"


def test_missing_candidate_data_is_incomplete_not_failed_or_full_marks():
    result = evaluate(
        candidate([], None, []),
        job(["Python", "SQL"], ["Docker"], 3, [QualificationCriterion("BSc")]),
    )
    assert result.score == D("0.00")
    assert result.breakdown["score_upper_bound"] == 100.0
    assert result.assessment_status == "incomplete"
    assert result.eligibility == "undetermined"
    assert result.breakdown["undetermined_criteria"] == ["required_skills", "experience", "qualifications"]
    assert {component(result, name)["status"] for name in ("required_skills", "preferred_skills", "experience", "qualifications")} == {"missing_data"}
    assert result.breakdown["qualification_evidence"][0]["matched"] is None
    assert {"missing_skill_data", "missing_experience_data", "missing_education_data"} <= {w["code"] for w in result.breakdown["warnings"]}


def test_partially_missing_data_scores_known_evidence_and_reports_upper_bound():
    result = evaluate(
        candidate(["Python"], None, ["BSc Computer Science"]),
        job(["Python", "SQL"], ["Docker"], 3, [QualificationCriterion("BSc")]),
    )
    # required 1/2 -> 25; preferred 0/1 -> 0; experience unknown -> 0 (upper bound +20); qualification -> 10
    assert result.score == D("35.00")
    assert result.breakdown["score_upper_bound"] == 55.0
    assert result.assessment_status == "incomplete"
    # A confirmed failure (missing SQL) outranks undetermined experience.
    assert result.eligibility == "not_eligible"
    assert result.breakdown["undetermined_criteria"] == ["experience"]


def test_experience_rule_is_linear_below_and_capped_above_requirement():
    def experience_score(years, required):
        return component(evaluate(candidate(["Python"], years), job(["Python"], min_years=required)), "experience")

    assert experience_score(1.5, 2)["score"] == 75.0
    assert experience_score(0, 2)["score"] == 0.0
    assert experience_score(2, 2)["score"] == 100.0
    assert experience_score(40, 2)["score"] == 100.0  # no bonus for excess
    assert experience_score(40, 2)["difference_years"] == 38.0
    below = evaluate(candidate(["Python"], 1.5), job(["Python"], min_years=2))
    # required effective 50/70 -> 71.428571; experience 20/70*0.75 -> 21.428571; total 92.857142 -> 92.86
    assert below.score == D("92.86")
    assert below.eligibility == "not_eligible"
    assert "below_minimum_experience" in [w["code"] for w in below.breakdown["warnings"]]


def test_zero_minimum_experience_is_not_applicable():
    result = evaluate(candidate(["Python"], None), job(["Python"], min_years=0))
    assert component(result, "experience")["status"] == "not_applicable"
    assert result.score == D("100.00")
    assert result.assessment_status == "complete"


def test_custom_job_weights_and_per_skill_weights():
    weights = {"required_skills": D("70"), "preferred_skills": D("10"), "experience": D("10"), "qualifications": D("10")}
    result = evaluate(
        candidate(["Python", "Docker"], 2),
        job(["Python", "SQL"], ["Docker"], 4, weights=weights, required_skill_weights={"Python": D("80"), "SQL": D("20")}),
    )
    # applicable 70 + 10 + 10 = 90 -> effective 77.777..., 11.111..., 11.111...
    # required 80% -> 62.2222; preferred 100% -> 11.1111; experience 2/4 -> 5.5556; total 78.8889 -> 78.89
    assert result.score == D("78.89")
    assert component(result, "required_skills")["score"] == 80.0


def test_rounding_is_half_up_to_two_decimals():
    result = evaluate(candidate(["A"]), job(["A", "B", "C"]))
    assert result.score == D("33.33")
    result = evaluate(candidate(["A", "B"]), job(["A", "B", "C"]))
    assert result.score == D("66.67")


@pytest.mark.parametrize("weights, message", [
    ({"required_skills": 50, "preferred_skills": 20, "experience": 20, "qualifications": 0}, "total 100"),
    ({"required_skills": 110, "preferred_skills": -10, "experience": 0, "qualifications": 0}, "between 0 and 100"),
    ({"required_skills": 0, "preferred_skills": 40, "experience": 40, "qualifications": 20}, "greater than 0"),
    ({"required_skills": 80, "preferred_skills": 20}, "exactly"),
    ({"required_skills": 50, "preferred_skills": 20, "experience": 20, "qualifications": 10, "bonus": 0}, "exactly"),
])
def test_invalid_weights_are_rejected(weights, message):
    with pytest.raises(InvalidWeightsError, match=message):
        validate_weights(weights)
    with pytest.raises(InvalidWeightsError):
        evaluate(candidate(["Python"]), job(["Python"], weights=weights))


def test_job_without_required_skills_cannot_be_screened():
    with pytest.raises(InvalidWeightsError, match="required skill"):
        evaluate(candidate(["Python"]), job([]))


def test_skill_normalization_uses_explicit_synonyms_only():
    assert normalize_skill("  PYTHON  ") == "python"
    assert normalize_skill("Machine   Learning") == "machine learning"
    assert normalize_skill("JS") == "javascript"
    assert normalize_skill("k8s") == "kubernetes"
    assert normalize_skill("pythn") == "pythn"  # no fuzzy matching
    result = evaluate(candidate(["pythn", "Postgres", "js"]), job(["Python", "PostgreSQL", "JavaScript"]))
    assert result.missing_mandatory_skills == ["python"]
    assert result.matched_skills == ["javascript", "postgresql"]


def test_conflicting_synonyms_are_rejected():
    with pytest.raises(ValueError, match="mapped to both"):
        normalization._build_alias_map({"go": ("golang",), "golang language": ("golang",)})


def test_qualifications_match_explicit_evidence_only():
    assert qualification_tokens("Bachelor of Science in Computer Science") == qualification_tokens("B.Sc. Computer Science")
    criteria = [
        QualificationCriterion("Bachelor of Science in Computer Science", True),
        QualificationCriterion("MBA", False),
    ]
    result = evaluate(candidate(["Python"], education=["B.Sc. Computer Science"]), job(["Python"], qualifications=criteria))
    evidence = result.breakdown["qualification_evidence"]
    assert [item["matched"] for item in evidence] == [True, False]
    assert evidence[0]["evidence"] == "B.Sc. Computer Science"
    # Optional qualification missing: score drops (1/2 -> 50%) but eligibility holds.
    # applicable 50 + 10 = 60 -> required 83.333 + qualification 16.667*0.5 = 91.666 -> 91.67
    assert result.score == D("91.67")
    assert result.eligibility == "eligible"
    # A higher degree is not inferred to satisfy a different one.
    higher = evaluate(candidate(["Python"], education=["MSc Computer Science"]), job(["Python"], qualifications=[QualificationCriterion("BSc Computer Science")]))
    assert higher.breakdown["qualification_evidence"][0]["matched"] is False
    assert higher.eligibility == "not_eligible"


def test_weighted_qualifications():
    criteria = [QualificationCriterion("BSc", False, D("70")), QualificationCriterion("AWS Certified", False, D("30"))]
    result = evaluate(candidate(["Python"], education=["AWS Certified Developer"]), job(["Python"], qualifications=criteria))
    assert component(result, "qualifications")["score"] == 30.0
    # 83.333 + 16.667 * 0.3 = 88.333 -> 88.33
    assert result.score == D("88.33")


def test_equal_inputs_produce_equal_scores():
    first = evaluate(candidate(["Python", "SQL"], 2), job(["Python", "SQL", "Go"], min_years=3))
    second = evaluate(candidate(["sql", "PYTHON"], 2), job(["Python", "SQL", "Go"], min_years=3))
    assert first.score == second.score
    assert first.breakdown == second.breakdown

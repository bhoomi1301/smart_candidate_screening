from scoring import calculate_match_score


def test_default_weights_produce_explainable_job_specific_score():
    result = calculate_match_score(
        {
            "skills": ["Python", "JS"],
            "experience": 3,
            "education": ["BSc Computer Science"],
        },
        {
            "required_skills": ["Python", "JavaScript"],
            "preferred_skills": ["PostgreSQL"],
            "min_experience": 4,
            "required_qualifications": ["BSc Computer Science"],
        },
    )

    assert result["score"] == 75.0
    assert result["matched_skills"] == ["javascript", "python"]
    assert result["missing_skills"] == ["postgresql"]
    assert result["components"]["experience"]["score"] == 75.0
    assert result["incomplete"] is False


def test_missing_candidate_data_is_not_scored_as_a_match():
    result = calculate_match_score(
        {"skills": [], "experience": None, "education": []},
        {
            "required_skills": ["Python"],
            "preferred_skills": [],
            "min_experience": 3,
            "required_qualifications": ["BSc"],
        },
    )

    assert result["score"] == 0.0
    assert result["missing_skills"] == ["python"]
    assert result["incomplete"] is True


def test_unconfigured_components_are_excluded_and_weights_normalized():
    result = calculate_match_score(
        {"skills": ["Python"], "experience": 0, "education": []},
        {"required_skills": ["Python"], "preferred_skills": [], "min_experience": 0},
    )

    assert result["score"] == 100.0
    assert set(result["components"]) == {"required_skills"}
    assert result["weights_normalized"] is True


def test_skill_aliases_and_fuzzy_matching():
    result = calculate_match_score(
        {"skills": ["Postgres", "pythn"], "experience": 0},
        {"required_skills": ["PostgreSQL", "Python"]},
    )

    assert result["score"] == 100.0


def test_missing_required_experience_is_reported_as_incomplete():
    result = calculate_match_score(
        {"skills": ["Python"], "experience": None},
        {"required_skills": ["Python"], "min_experience": 3},
    )

    assert result["incomplete"] is True
    assert result["components"]["experience"]["score"] == 0.0
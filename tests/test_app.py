import os
import tempfile

import pytest

from app import app, init_db


@pytest.fixture(autouse=True)
def reset_database():
    _temp_db_path = tempfile.mktemp(suffix='.db')
    app.config['DATABASE'] = _temp_db_path
    init_db()
    yield


def test_login_page_loads():
    client = app.test_client()
    response = client.get('/login')
    assert response.status_code == 200
    assert b'Login' in response.data


def test_dashboard_requires_login():
    client = app.test_client()
    response = client.get('/dashboard')
    assert response.status_code == 302


def test_login_success_redirects_to_dashboard():
    client = app.test_client()
    response = client.post(
        '/login',
        data={'email': 'admin@company.com', 'password': 'admin123'},
        follow_redirects=True,
    )
    assert response.status_code == 200
    assert b'Dashboard' in response.data


def test_invalid_email_is_rejected():
    client = app.test_client()
    response = client.post(
        '/login',
        data={'email': 'not-an-email', 'password': 'admin123'},
        follow_redirects=True,
    )
    assert response.status_code == 200
    assert b'valid email' in response.data.lower()


def test_invalid_candidate_experience_is_rejected():
    client = app.test_client()
    response = client.post(
        '/login',
        data={'email': 'admin@company.com', 'password': 'admin123'},
        follow_redirects=True,
    )
    assert response.status_code == 200

    response = client.post(
        '/candidates/add',
        data={
            'name': 'Test User',
            'email': 'test@example.com',
            'experience': 'not-a-number',
            'skills': 'Python, SQL',
        },
        follow_redirects=True,
    )
    assert response.status_code == 200
    assert b'valid number' in response.data.lower()


def test_dashboard_can_filter_by_status():
    client = app.test_client()
    client.post('/login', data={'email': 'admin@company.com', 'password': 'admin123'}, follow_redirects=True)

    response = client.get('/dashboard?status=Pending', follow_redirects=True)
    assert response.status_code == 200
    assert b'Ava Patel' not in response.data
    assert b'Noah Johnson' in response.data


def test_jobs_can_add_and_edit_multiple_jobs():
    client = app.test_client()
    client.post('/login', data={'email': 'admin@company.com', 'password': 'admin123'}, follow_redirects=True)

    response = client.post(
        '/jobs',
        data={
            'action': 'add',
            'title': 'Data Analyst',
            'description': 'Analyze reporting data and dashboards.',
            'required_skills': 'Python, SQL, Data Analysis',
            'min_experience': '3',
        },
        follow_redirects=True,
    )
    assert response.status_code == 200
    assert b'Data Analyst' in response.data

    job_id = 2
    response = client.post(
        '/jobs',
        data={
            'action': 'edit',
            'job_id': str(job_id),
            'title': 'Senior Data Analyst',
            'description': 'Lead reporting and business intelligence.',
            'required_skills': 'Python, SQL, Data Analysis, Communication',
            'min_experience': '5',
        },
        follow_redirects=True,
    )
    assert response.status_code == 200
    assert b'Senior Data Analyst' in response.data


def test_activate_job_does_not_require_title_field():
    client = app.test_client()
    client.post('/login', data={'email': 'admin@company.com', 'password': 'admin123'}, follow_redirects=True)

    response = client.post(
        '/jobs',
        data={'action': 'activate', 'job_id': '1'},
        follow_redirects=True,
    )
    assert response.status_code == 200
    assert b'Job activated successfully' in response.data


def test_candidates_can_be_deleted():
    client = app.test_client()
    client.post('/login', data={'email': 'admin@company.com', 'password': 'admin123'}, follow_redirects=True)

    response = client.post(
        '/candidates/add',
        data={
            'name': 'Delete Me User',
            'email': 'delete-me-user@example.com',
            'experience': '4',
            'skills': 'Python, SQL',
        },
        follow_redirects=True,
    )
    assert response.status_code == 200

    candidate = client.get('/candidates').data.decode()
    candidate_id = candidate.split('delete-me-user@example.com')[0].rfind('candidate_id')
    # Use a deterministic lookup from the database instead of parsing HTML.
    with app.app_context():
        from app import get_db_connection

        row = get_db_connection().execute(
            'SELECT id FROM candidates WHERE email = ?',
            ('delete-me-user@example.com',),
        ).fetchone()
        assert row is not None
        candidate_id = row['id']

    response = client.post(f'/candidates/{candidate_id}/delete', follow_redirects=True)
    assert response.status_code == 200
    assert b'candidate deleted successfully' in response.data.lower()

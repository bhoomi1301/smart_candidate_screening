import os

from app import app


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

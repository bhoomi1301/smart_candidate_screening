import os
import re
import sqlite3
from functools import wraps

from flask import Flask, redirect, render_template, request, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'smart-candidate-secret-key')
app.config['DATABASE'] = os.path.join(os.path.dirname(__file__), 'candidate_screening.db')


def get_db_connection():
    connection = sqlite3.connect(app.config['DATABASE'])
    connection.row_factory = sqlite3.Row
    return connection


def init_db():
    with get_db_connection() as connection:
        connection.execute(
            '''
            CREATE TABLE IF NOT EXISTS admin_users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                email TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL
            )
            '''
        )
        connection.execute(
            '''
            CREATE TABLE IF NOT EXISTS job_requirements (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                required_skills TEXT NOT NULL,
                min_experience INTEGER NOT NULL
            )
            '''
        )
        connection.execute(
            '''
            CREATE TABLE IF NOT EXISTS candidates (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                email TEXT UNIQUE NOT NULL,
                experience INTEGER NOT NULL,
                skills TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'Pending',
                match_score INTEGER NOT NULL DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            '''
        )

        admin_count = connection.execute('SELECT COUNT(*) FROM admin_users').fetchone()[0]
        if admin_count == 0:
            connection.execute(
                'INSERT INTO admin_users (email, password_hash) VALUES (?, ?)',
                ('admin@company.com', generate_password_hash('admin123')),
            )

        job_row = connection.execute('SELECT COUNT(*) FROM job_requirements').fetchone()[0]
        if job_row == 0:
            connection.execute(
                'INSERT INTO job_requirements (id, required_skills, min_experience) VALUES (?, ?, ?)',
                (1, 'Python, SQL, Communication, Teamwork', 3),
            )

        candidate_count = connection.execute('SELECT COUNT(*) FROM candidates').fetchone()[0]
        if candidate_count == 0:
            seed_candidates = [
                ('Ava Patel', 'ava.patel@example.com', 5, 'Python, SQL, Communication, Teamwork', 'Shortlisted'),
                ('Noah Johnson', 'noah.johnson@example.com', 2, 'JavaScript, HTML, CSS', 'Pending'),
                ('Mia Chen', 'mia.chen@example.com', 4, 'Python, SQL, Data Analysis, Communication', 'Pending'),
                ('Liam Rodriguez', 'liam.rodriguez@example.com', 7, 'Leadership, Communication, Teamwork', 'Rejected'),
            ]
            connection.executemany(
                'INSERT INTO candidates (name, email, experience, skills, status) VALUES (?, ?, ?, ?, ?)',
                seed_candidates,
            )

        connection.commit()

    sync_candidate_scores()


def normalize_skills(skills_text):
    return {item.strip().lower() for item in str(skills_text).split(',') if item.strip()}


def calculate_match_score(candidate_skills, required_skills, experience, minimum_experience):
    required = normalize_skills(required_skills)
    candidate = normalize_skills(candidate_skills)
    if not required:
        return 0

    overlap = len(candidate & required)
    base_score = round((overlap / len(required)) * 100)
    if experience >= minimum_experience:
        base_score = min(100, base_score + 10)
    return max(0, min(100, base_score))


def sync_candidate_scores():
    job_record = get_job_requirements()
    if not job_record:
        return

    required_skills = job_record['required_skills']
    minimum_experience = job_record['min_experience']
    with get_db_connection() as connection:
        candidates = connection.execute('SELECT * FROM candidates').fetchall()
        for candidate in candidates:
            score = calculate_match_score(candidate['skills'], required_skills, candidate['experience'], minimum_experience)
            connection.execute(
                'UPDATE candidates SET match_score = ? WHERE id = ?',
                (score, candidate['id']),
            )
        connection.commit()


def get_job_requirements():
    with get_db_connection() as connection:
        return connection.execute('SELECT * FROM job_requirements WHERE id = 1').fetchone()


def is_valid_email(email):
    return bool(email) and re.fullmatch(r'^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$', email) is not None


def parse_non_negative_int(value, field_name):
    try:
        parsed_value = int(value)
    except (TypeError, ValueError):
        raise ValueError(f'{field_name} must be a valid number.') from None

    if parsed_value < 0:
        raise ValueError(f'{field_name} must be 0 or greater.')
    return parsed_value


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if 'user_id' not in session:
            return redirect(url_for('login'))
        return view(*args, **kwargs)

    return wrapped


@app.route('/')
def index():
    if 'user_id' in session:
        return redirect(url_for('dashboard'))
    return redirect(url_for('login'))


@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form.get('email', '').strip().lower()
        password = request.form.get('password', '')

        if not email or not password or not is_valid_email(email):
            return render_template('login.html', error='Please enter a valid email and password.')

        with get_db_connection() as connection:
            user = connection.execute(
                'SELECT * FROM admin_users WHERE email = ?',
                (email,),
            ).fetchone()

        if user and check_password_hash(user['password_hash'], password):
            session['user_id'] = user['id']
            return redirect(url_for('dashboard'))

        return render_template('login.html', error='Invalid email or password.')

    return render_template('login.html')


@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))


@app.route('/dashboard')
@login_required
def dashboard():
    with get_db_connection() as connection:
        candidates = connection.execute(
            'SELECT * FROM candidates ORDER BY created_at DESC'
        ).fetchall()
        total_candidates = len(candidates)
        shortlisted = sum(1 for candidate in candidates if candidate['status'] == 'Shortlisted')
        rejected = sum(1 for candidate in candidates if candidate['status'] == 'Rejected')
        pending = sum(1 for candidate in candidates if candidate['status'] == 'Pending')
        avg_score = round(sum(candidate['match_score'] for candidate in candidates) / total_candidates, 1) if total_candidates else 0

    job_record = get_job_requirements()
    return render_template(
        'dashboard.html',
        candidates=candidates,
        total_candidates=total_candidates,
        shortlisted=shortlisted,
        rejected=rejected,
        pending=pending,
        avg_score=avg_score,
        job_requirements=job_record,
    )


@app.route('/candidates')
@login_required
def candidates():
    search_term = request.args.get('q', '').strip().lower()
    with get_db_connection() as connection:
        if search_term:
            candidates_list = connection.execute(
                '''
                SELECT * FROM candidates
                WHERE lower(name) LIKE ? OR lower(email) LIKE ? OR lower(skills) LIKE ?
                ORDER BY created_at DESC
                ''',
                (f'%{search_term}%', f'%{search_term}%', f'%{search_term}%'),
            ).fetchall()
        else:
            candidates_list = connection.execute('SELECT * FROM candidates ORDER BY created_at DESC').fetchall()

    job_record = get_job_requirements()
    return render_template('candidates.html', candidates=candidates_list, job_requirements=job_record, search_term=search_term)


@app.route('/candidates/add', methods=['POST'])
@login_required
def add_candidate():
    name = request.form.get('name', '').strip()
    email = request.form.get('email', '').strip().lower()
    skills = request.form.get('skills', '').strip()

    if not name or not email or not skills:
        return render_template(
            'candidates.html',
            candidates=get_candidates_for_view(),
            job_requirements=get_job_requirements(),
            search_term='',
            error='Name, email, and skills are required.',
        )

    if not is_valid_email(email):
        return render_template(
            'candidates.html',
            candidates=get_candidates_for_view(),
            job_requirements=get_job_requirements(),
            search_term='',
            error='Please enter a valid email address.',
        )

    try:
        experience = parse_non_negative_int(request.form.get('experience', ''), 'Experience')
    except ValueError as exc:
        return render_template(
            'candidates.html',
            candidates=get_candidates_for_view(),
            job_requirements=get_job_requirements(),
            search_term='',
            error=str(exc),
        )

    job_record = get_job_requirements()
    match_score = calculate_match_score(skills, job_record['required_skills'], experience, job_record['min_experience'])

    with get_db_connection() as connection:
        connection.execute(
            'INSERT INTO candidates (name, email, experience, skills, status, match_score) VALUES (?, ?, ?, ?, ?, ?)',
            (name, email, experience, skills, 'Pending', match_score),
        )
        connection.commit()

    return redirect(url_for('candidates'))


@app.route('/candidates/<int:candidate_id>/status', methods=['POST'])
@login_required
def update_candidate_status(candidate_id):
    status = request.form.get('status', 'Pending')
    with get_db_connection() as connection:
        connection.execute('UPDATE candidates SET status = ? WHERE id = ?', (status, candidate_id))
        connection.commit()
    return redirect(url_for('candidates'))


@app.route('/jobs', methods=['GET', 'POST'])
@login_required
def jobs():
    if request.method == 'POST':
        required_skills = request.form.get('required_skills', '').strip()
        if not required_skills:
            return render_template('jobs.html', job_requirements=get_job_requirements(), error='Required skills cannot be empty.')

        try:
            min_experience = parse_non_negative_int(request.form.get('min_experience', ''), 'Minimum experience')
        except ValueError as exc:
            return render_template('jobs.html', job_requirements=get_job_requirements(), error=str(exc))

        with get_db_connection() as connection:
            connection.execute(
                'UPDATE job_requirements SET required_skills = ?, min_experience = ? WHERE id = 1',
                (required_skills, min_experience),
            )
            connection.commit()
        sync_candidate_scores()
        return redirect(url_for('jobs'))

    job_record = get_job_requirements()
    return render_template('jobs.html', job_requirements=job_record)


def get_candidates_for_view():
    with get_db_connection() as connection:
        return connection.execute('SELECT * FROM candidates ORDER BY created_at DESC').fetchall()


init_db()


if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)

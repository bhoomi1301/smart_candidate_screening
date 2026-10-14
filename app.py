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


def ensure_job_requirements_table(connection):
    connection.execute(
        '''
        CREATE TABLE IF NOT EXISTS job_requirements (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL DEFAULT 'Job Opening',
            description TEXT NOT NULL DEFAULT '',
            required_skills TEXT NOT NULL,
            min_experience INTEGER NOT NULL DEFAULT 0,
            is_active INTEGER NOT NULL DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        '''
    )

    columns = [row['name'] for row in connection.execute('PRAGMA table_info(job_requirements)').fetchall()]
    if 'title' not in columns or 'description' not in columns or 'is_active' not in columns:
        existing_rows = connection.execute('SELECT * FROM job_requirements ORDER BY id').fetchall()
        connection.execute('ALTER TABLE job_requirements RENAME TO job_requirements_legacy')
        connection.execute(
            '''
            CREATE TABLE job_requirements (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL DEFAULT 'Job Opening',
                description TEXT NOT NULL DEFAULT '',
                required_skills TEXT NOT NULL,
                min_experience INTEGER NOT NULL DEFAULT 0,
                is_active INTEGER NOT NULL DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            '''
        )

        for row in existing_rows:
            legacy_title = row['title'] if 'title' in row.keys() else 'Legacy Job'
            legacy_description = row['description'] if 'description' in row.keys() else 'Legacy role requirements.'
            required_skills = row['required_skills'] if 'required_skills' in row.keys() else ''
            min_experience = row['min_experience'] if 'min_experience' in row.keys() else 0
            legacy_created_at = row['created_at'] if 'created_at' in row.keys() else None
            is_active = 1 if row['id'] == 1 else 0
            connection.execute(
                'INSERT INTO job_requirements (id, title, description, required_skills, min_experience, is_active, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)',
                (row['id'], legacy_title, legacy_description, required_skills, min_experience, is_active, legacy_created_at),
            )

        connection.execute('DROP TABLE job_requirements_legacy')


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
        ensure_job_requirements_table(connection)
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

        job_rows = connection.execute('SELECT * FROM job_requirements ORDER BY id').fetchall()
        if not job_rows:
            connection.execute(
                'INSERT INTO job_requirements (title, description, required_skills, min_experience, is_active) VALUES (?, ?, ?, ?, ?)',
                ('Senior Python Developer', 'Build robust backend features and mentor the team.', 'Python, SQL, Communication, Teamwork', 3, 1),
            )
        else:
            active_jobs = [job for job in job_rows if job['is_active'] == 1]
            if not active_jobs:
                connection.execute('UPDATE job_requirements SET is_active = 1 WHERE id = ?', (job_rows[0]['id'],))

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


def sync_candidate_scores(job_record=None):
    if job_record is None:
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


def get_all_job_requirements():
    with get_db_connection() as connection:
        return connection.execute(
            'SELECT * FROM job_requirements ORDER BY is_active DESC, created_at DESC, id DESC'
        ).fetchall()


def get_job_requirements(job_id=None):
    with get_db_connection() as connection:
        if job_id is not None:
            return connection.execute('SELECT * FROM job_requirements WHERE id = ?', (job_id,)).fetchone()
        return connection.execute(
            'SELECT * FROM job_requirements WHERE is_active = 1 ORDER BY id ASC LIMIT 1'
        ).fetchone() or connection.execute('SELECT * FROM job_requirements ORDER BY id ASC LIMIT 1').fetchone()


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
    status_filter = request.args.get('status', 'All').strip()
    valid_statuses = {'All', 'Pending', 'Shortlisted', 'Rejected'}
    status_filter = status_filter.title() if status_filter else 'All'
    if status_filter not in valid_statuses:
        status_filter = 'All'

    with get_db_connection() as connection:
        if status_filter == 'All':
            candidates = connection.execute('SELECT * FROM candidates ORDER BY created_at DESC').fetchall()
        else:
            candidates = connection.execute(
                'SELECT * FROM candidates WHERE status = ? ORDER BY created_at DESC',
                (status_filter,),
            ).fetchall()

        total_candidates = connection.execute('SELECT COUNT(*) FROM candidates').fetchone()[0]
        shortlisted = connection.execute("SELECT COUNT(*) FROM candidates WHERE status = 'Shortlisted'").fetchone()[0]
        rejected = connection.execute("SELECT COUNT(*) FROM candidates WHERE status = 'Rejected'").fetchone()[0]
        pending = connection.execute("SELECT COUNT(*) FROM candidates WHERE status = 'Pending'").fetchone()[0]
        avg_score = round(sum(candidate['match_score'] for candidate in connection.execute('SELECT * FROM candidates').fetchall()) / total_candidates, 1) if total_candidates else 0

    job_record = get_job_requirements()
    return render_template(
        'dashboard.html',
        candidates=candidates,
        total_candidates=total_candidates,
        shortlisted=shortlisted,
        rejected=rejected,
        pending=pending,
        avg_score=avg_score,
        active_status=status_filter,
        job_requirements=job_record,
    )


@app.route('/candidates')
@login_required
def candidates():
    search_term = request.args.get('q', '').strip().lower()
    success_message = request.args.get('success', '')
    error_message = request.args.get('error', '')
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
    return render_template(
        'candidates.html',
        candidates=candidates_list,
        job_requirements=job_record,
        search_term=search_term,
        error=error_message,
        success=success_message,
    )


@app.route('/candidates/add', methods=['POST'])
@login_required
def add_candidate():
    name = request.form.get('name', '').strip()
    email = request.form.get('email', '').strip().lower()
    skills = request.form.get('skills', '').strip()

    if not name or not email or not skills:
        return redirect(url_for('candidates', error='Name, email, and skills are required.'))

    if not is_valid_email(email):
        return redirect(url_for('candidates', error='Please enter a valid email address.'))

    try:
        experience = parse_non_negative_int(request.form.get('experience', ''), 'Experience')
    except ValueError as exc:
        return redirect(url_for('candidates', error=str(exc)))

    job_record = get_job_requirements()
    if not job_record:
        return redirect(url_for('candidates', error='Please create at least one job requirement before adding candidates.'))

    match_score = calculate_match_score(skills, job_record['required_skills'], experience, job_record['min_experience'])

    try:
        with get_db_connection() as connection:
            connection.execute(
                'INSERT INTO candidates (name, email, experience, skills, status, match_score) VALUES (?, ?, ?, ?, ?, ?)',
                (name, email, experience, skills, 'Pending', match_score),
            )
            connection.commit()
    except sqlite3.IntegrityError:
        return redirect(url_for('candidates', error='A candidate with this email already exists.'))
    except sqlite3.Error:
        app.logger.exception('Unable to add candidate.')
        return redirect(url_for('candidates', error='Unable to add candidate right now. Please try again.'))

    return redirect(url_for('candidates', success='Candidate added successfully.'))


@app.route('/candidates/<int:candidate_id>/status', methods=['POST'])
@login_required
def update_candidate_status(candidate_id):
    status = request.form.get('status', 'Pending')
    valid_statuses = {'Pending', 'Shortlisted', 'Rejected'}
    if status not in valid_statuses:
        return redirect(url_for('candidates', error='Please choose a valid candidate status.'))

    try:
        with get_db_connection() as connection:
            connection.execute('UPDATE candidates SET status = ? WHERE id = ?', (status, candidate_id))
            updated = get_changes(connection)
            connection.commit()
    except sqlite3.Error:
        app.logger.exception('Unable to update candidate status.')
        return redirect(url_for('candidates', error='Unable to update the candidate status.'))

    if updated == 0:
        return redirect(url_for('candidates', error='Candidate not found.'))
    return redirect(url_for('candidates', success='Candidate status updated successfully.'))


@app.route('/candidates/<int:candidate_id>/delete', methods=['POST'])
@login_required
def delete_candidate(candidate_id):
    try:
        with get_db_connection() as connection:
            connection.execute('DELETE FROM candidates WHERE id = ?', (candidate_id,))
            deleted = get_changes(connection)
            connection.commit()
    except sqlite3.Error:
        app.logger.exception('Unable to delete candidate.')
        return redirect(url_for('candidates', error='Unable to delete candidate right now.'))

    if deleted == 0:
        return redirect(url_for('candidates', error='Candidate not found.'))
    return redirect(url_for('candidates', success='Candidate deleted successfully.'))


@app.route('/jobs', methods=['GET', 'POST'])
@login_required
def jobs():
    success_message = request.args.get('success', '')
    error_message = request.args.get('error', '')

    if request.method == 'POST':
        action = request.form.get('action', '').strip().lower()
        try:
            if action == 'activate':
                job_id = request.form.get('job_id', type=int)
                if job_id is None:
                    raise ValueError('Job ID is required to activate a role.')
                with get_db_connection() as connection:
                    existing_job = connection.execute('SELECT * FROM job_requirements WHERE id = ?', (job_id,)).fetchone()
                    if existing_job is None:
                        raise ValueError('The selected job could not be found.')
                    connection.execute('UPDATE job_requirements SET is_active = 0')
                    connection.execute('UPDATE job_requirements SET is_active = 1 WHERE id = ?', (job_id,))
                    connection.commit()
                sync_candidate_scores(get_job_requirements(job_id))
                return redirect(url_for('jobs', success='Job activated successfully.'))

            if action == 'delete':
                job_id = request.form.get('job_id', type=int)
                if job_id is None:
                    raise ValueError('Job ID is required to delete a role.')

                with get_db_connection() as connection:
                    total_jobs = connection.execute('SELECT COUNT(*) FROM job_requirements').fetchone()[0]
                    if total_jobs <= 1:
                        raise ValueError('At least one job requirement must remain.')

                    job = connection.execute('SELECT * FROM job_requirements WHERE id = ?', (job_id,)).fetchone()
                    if job is None:
                        raise ValueError('The selected job could not be found.')

                    connection.execute('DELETE FROM job_requirements WHERE id = ?', (job_id,))
                    deleted = get_changes(connection)
                    if job['is_active'] == 1:
                        next_job = connection.execute(
                            'SELECT * FROM job_requirements ORDER BY id ASC LIMIT 1'
                        ).fetchone()
                        if next_job:
                            connection.execute('UPDATE job_requirements SET is_active = 1 WHERE id = ?', (next_job['id'],))
                    connection.commit()

                if deleted == 0:
                    raise ValueError('The selected job could not be deleted.')
                sync_candidate_scores(get_job_requirements())
                return redirect(url_for('jobs', success='Job deleted successfully.'))

            title = request.form.get('title', '').strip()
            description = request.form.get('description', '').strip()
            required_skills = request.form.get('required_skills', '').strip()
            if not title:
                raise ValueError('Job title is required.')
            if not required_skills:
                raise ValueError('Required skills cannot be empty.')
            if not description:
                description = f'{title} role responsibilities.'
            min_experience = parse_non_negative_int(request.form.get('min_experience', ''), 'Minimum experience')

            if action == 'edit':
                job_id = request.form.get('job_id', type=int)
                if job_id is None:
                    raise ValueError('Job ID is required to update a role.')
                with get_db_connection() as connection:
                    existing_job = connection.execute('SELECT * FROM job_requirements WHERE id = ?', (job_id,)).fetchone()
                    if existing_job is None:
                        raise ValueError('The selected job could not be found.')
                    connection.execute(
                        'UPDATE job_requirements SET title = ?, description = ?, required_skills = ?, min_experience = ? WHERE id = ?',
                        (title, description, required_skills, min_experience, job_id),
                    )
                    connection.commit()
                sync_candidate_scores(get_job_requirements(job_id))
                return redirect(url_for('jobs', success='Job updated successfully.'))

            if action == 'add':
                with get_db_connection() as connection:
                    connection.execute(
                        'INSERT INTO job_requirements (title, description, required_skills, min_experience, is_active) VALUES (?, ?, ?, ?, ?)',
                        (title, description, required_skills, min_experience, 1),
                    )
                    connection.execute('UPDATE job_requirements SET is_active = 0 WHERE id != ?', (connection.execute('SELECT last_insert_rowid()').fetchone()[0],))
                    connection.commit()
                sync_candidate_scores(get_job_requirements())
                return redirect(url_for('jobs', success='Job added successfully.'))

            raise ValueError('Unsupported job action.')
        except ValueError as exc:
            error_message = str(exc)
        except sqlite3.Error:
            app.logger.exception('A database error occurred while managing jobs.')
            error_message = 'Unable to save the job requirement right now. Please try again.'

    jobs_list = get_all_job_requirements()
    return render_template(
        'jobs.html',
        jobs=jobs_list,
        job_requirements=get_job_requirements(),
        error=error_message,
        success=success_message,
    )


def get_changes(connection):
    return connection.execute('SELECT changes()').fetchone()[0]


@app.errorhandler(404)
def page_not_found(error):
    if 'user_id' in session:
        return redirect(url_for('dashboard'))
    return redirect(url_for('login'))


@app.errorhandler(Exception)
def handle_unexpected_error(error):
    app.logger.exception('Unhandled application error: %s', error)
    if 'user_id' in session:
        return redirect(url_for('dashboard'))
    return redirect(url_for('login'))


def get_candidates_for_view():
    with get_db_connection() as connection:
        return connection.execute('SELECT * FROM candidates ORDER BY created_at DESC').fetchall()


init_db()


if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)

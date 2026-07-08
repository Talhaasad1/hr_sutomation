"""
db.py
MongoDB data-access layer for the ATS Portal.

Collections:
 - users            : HR / Recruiter / Admin accounts
 - departments       : department names
 - jobs              : job postings
 - candidates        : applicant profile + parsed resume data
 - applications      : a candidate applying to a specific job (ATS pipeline lives here)
 - interviews        : scheduled interviews linked to an application
 - email_templates   : editable templates per pipeline stage
 - emails            : sent-email log
 - notifications     : in-app notifications for HR/Recruiters
 - offers            : generated offer letters
 - system_logs       : admin-visible audit trail
 - sessions          : login tokens so refreshing the browser doesn't log the user out
 - login_attempts    : failed-login tracking for brute-force lockout
 - employees         : payroll/HRIS-style record created once a candidate reaches 'Joined'
 - background_tasks  : queue for the standalone worker process (bulk resume import, etc.)
"""

from datetime import datetime, timedelta, date
import uuid
from bson.objectid import ObjectId
from pymongo import MongoClient, DESCENDING

import config

_client = MongoClient(config.MONGO_URI)
db = _client[config.DB_NAME]

users = db.users
departments = db.departments
jobs = db.jobs
candidates = db.candidates
applications = db.applications
interviews = db.interviews
email_templates = db.email_templates
emails = db.emails
notifications = db.notifications
offers = db.offers
system_logs = db.system_logs
settings = db.settings
sessions = db.sessions
login_attempts = db.login_attempts
employees = db.employees
background_tasks = db.background_tasks
password_reset_codes = db.password_reset_codes

SESSION_LIFETIME_HOURS = 24 * 7  # 7 days
MAX_LOGIN_ATTEMPTS = 5
LOCKOUT_MINUTES = 15
MAX_RESUME_SIZE_MB = 8
PASSWORD_RESET_CODE_LIFETIME_MINUTES = 15

ATS_STAGES = [
    "Applied", "Screening", "Shortlisted", "Interview Scheduled",
    "Technical Round", "HR Round", "Selected", "Offer Sent", "Joined", "Rejected",
]

DEFAULT_EMAIL_TEMPLATES = {
    "Application Received": {
        "subject": "We've received your application - {job_title}",
        "body": "Dear {candidate_name},\n\nThank you for applying for {job_title}. "
                "Our team will review your resume and get back to you soon.\n\nBest regards,\nHR Team",
    },
    "Shortlisted": {
        "subject": "You've been shortlisted - {job_title}",
        "body": "Dear {candidate_name},\n\nCongratulations! You have been shortlisted for {job_title}. "
                "We will contact you soon regarding next steps.\n\nBest regards,\nHR Team",
    },
    "Interview Scheduled": {
        "subject": "Interview Scheduled - {job_title}",
        "body": "Dear {candidate_name},\n\nYour interview for {job_title} has been scheduled on "
                "{interview_date} at {interview_time}. A calendar invite is attached.\n\nBest regards,\nHR Team",
    },
    "Rejected": {
        "subject": "Update on your application - {job_title}",
        "body": "Dear {candidate_name},\n\nThank you for your interest in {job_title}. "
                "After careful consideration, we will not be moving forward with your application at this time.\n\nBest regards,\nHR Team",
    },
    "Offer Sent": {
        "subject": "Job Offer - {job_title}",
        "body": "Dear {candidate_name},\n\nWe are pleased to offer you the position of {job_title}. "
                "Please find your offer letter attached.\n\nBest regards,\nHR Team",
    },
    "Joined": {
        "subject": "Welcome aboard, {candidate_name}!",
        "body": "Dear {candidate_name},\n\nWelcome to the team! We're delighted to confirm your joining "
                "for the position of {job_title}. Our HR team will be in touch with your onboarding details.\n\n"
                "Best regards,\nHR Team",
    },
}

EMPLOYEE_STATUS_OPTIONS = ["Active", "On Leave", "Transferred", "Resigned", "Terminated", "Retired"]


def init_db():
    """Create default admin user, default email templates, seed data (idempotent)."""
    import auth  # local import to avoid circular import

    if users.count_documents({}) == 0:
        users.insert_one({
            "username": "admin", "password_hash": auth.hash_password("admin123"),
            "role": "Admin", "department": "Administration", "created_at": datetime.now(),
            "force_password_change": True,  # must be changed on first login
        })

    # TTL indexes — MongoDB automatically deletes documents once their date
    # field is in the past. This keeps expired sessions and old login-attempt
    # records from accumulating forever without needing a separate cleanup job.
    try:
        sessions.create_index("expires_at", expireAfterSeconds=0)
        login_attempts.create_index("last_attempt_at", expireAfterSeconds=LOCKOUT_MINUTES * 60)
        password_reset_codes.create_index("expires_at", expireAfterSeconds=0)
    except Exception:
        pass  # index creation is best-effort (e.g. mongomock in tests may not support all options)

    if email_templates.count_documents({}) == 0:
        for stage, tpl in DEFAULT_EMAIL_TEMPLATES.items():
            email_templates.insert_one({"stage": stage, **tpl})

    if departments.count_documents({}) == 0:
        departments.insert_many([{"name": d} for d in
                                  ["Engineering", "Sales", "Marketing", "HR", "Finance", "Operations"]])

    if settings.count_documents({}) == 0:
        settings.insert_many([
            {"key": "company_name", "value": "Your Company"},
            {"key": "logo_path", "value": ""},
        ])


def get_setting_value(key: str, default: str = "") -> str:
    doc = settings.find_one({"key": key})
    return doc["value"] if doc else default


def set_setting_value(key: str, value: str):
    settings.update_one({"key": key}, {"$set": {"value": value}}, upsert=True)


def get_ai_config():
    """Returns (provider, api_key) for whichever AI provider the Admin has
    configured, or (None, None) if nothing is set up yet — in which case
    resume screening automatically falls back to the rule-based evaluator."""
    provider = get_setting_value("ai_provider", "")
    if not provider:
        return None, None
    key_setting = {
        "Claude": "anthropic_api_key", "OpenAI": "openai_api_key",
        "Gemini": "gemini_api_key", "Grok": "grok_api_key",
    }.get(provider)
    api_key = get_setting_value(key_setting, "") if key_setting else ""
    if not api_key:
        return None, None
    return provider, api_key


def log_action(username: str, action: str, details: str = ""):
    system_logs.insert_one({
        "username": username, "action": action, "details": details, "timestamp": datetime.now(),
    })


def notify(role_or_username: str, message: str, notif_type: str = "info"):
    notifications.insert_one({
        "target": role_or_username, "message": message, "type": notif_type,
        "is_read": False, "created_at": datetime.now(),
    })


def oid(id_str):
    return ObjectId(id_str) if not isinstance(id_str, ObjectId) else id_str


# ---------------------------------------------------------------------------
# Jobs
# ---------------------------------------------------------------------------
def create_job(data: dict, created_by: str) -> str:
    data["status"] = "Open"
    data["created_by"] = created_by
    data["created_at"] = datetime.now()
    result = jobs.insert_one(data)
    notify("HR", f"New job posted: {data.get('title')}", "job")
    return str(result.inserted_id)


def update_job(job_id: str, data: dict):
    jobs.update_one({"_id": oid(job_id)}, {"$set": data})


def delete_job(job_id: str):
    jobs.delete_one({"_id": oid(job_id)})


def get_jobs(status=None):
    query = {"status": status} if status else {}
    return list(jobs.find(query).sort("created_at", DESCENDING))


def get_job(job_id: str):
    return jobs.find_one({"_id": oid(job_id)})


def auto_close_expired_jobs():
    """Any 'Open' job whose 'Apply Before' (last_date) has passed gets
    automatically flipped to 'Closed'. last_date is stored as an ISO date
    string (YYYY-MM-DD), which compares correctly against today's ISO string
    without needing to parse it. Safe to call often — it's a no-op once a
    job is already closed."""
    today_str = date.today().isoformat()
    result = jobs.update_many(
        {"status": "Open", "last_date": {"$lt": today_str}},
        {"$set": {"status": "Closed"}},
    )
    return result.modified_count


def auto_close_expired_jobs_throttled(min_interval_seconds=120):
    """Session-throttled wrapper around auto_close_expired_jobs() so it
    doesn't add a database write to every single page rerun/interaction —
    at most once per `min_interval_seconds` per browser session. Only call
    this from inside a running Streamlit page (it needs st.session_state);
    worker.py calls the plain auto_close_expired_jobs() directly instead,
    on its own schedule, independent of any session."""
    import time
    import streamlit as st
    key = "_last_auto_close_check"
    now = time.time()
    last = st.session_state.get(key, 0)
    if now - last >= min_interval_seconds:
        st.session_state[key] = now
        return auto_close_expired_jobs()
    return 0


def get_department_names() -> list:
    return [d["name"] for d in departments.find().sort("name", 1)]


# ---------------------------------------------------------------------------
# Candidates
# ---------------------------------------------------------------------------
def create_candidate(data: dict) -> str:
    data["created_at"] = datetime.now()
    result = candidates.insert_one(data)
    return str(result.inserted_id)


def get_candidate(candidate_id: str):
    return candidates.find_one({"_id": oid(candidate_id)})


def find_candidate_by_email(email: str):
    return candidates.find_one({"email": email})


def get_all_candidates():
    return list(candidates.find().sort("created_at", DESCENDING))


def update_candidate(candidate_id: str, data: dict):
    candidates.update_one({"_id": oid(candidate_id)}, {"$set": data})


# ---------------------------------------------------------------------------
# Applications (ATS pipeline lives here)
# ---------------------------------------------------------------------------
def create_application(candidate_id: str, job_id: str, screening: dict) -> str:
    app_doc = {
        "candidate_id": oid(candidate_id),
        "job_id": oid(job_id),
        "match_score": screening.get("match_score", 0),
        "missing_skills": screening.get("missing_skills", []),
        "strong_skills": screening.get("strong_skills", []),
        "weak_areas": screening.get("weak_areas", []),
        "recommendation": screening.get("recommendation", ""),
        "status": "Applied",
        "status_history": [{"status": "Applied", "timestamp": datetime.now()}],
        "applied_at": datetime.now(),
    }
    result = applications.insert_one(app_doc)
    job = get_job(job_id)
    notify("HR", f"New application for {job['title'] if job else 'a job'}", "application")
    return str(result.inserted_id)


def get_applications(job_id=None, status=None):
    query = {}
    if job_id:
        query["job_id"] = oid(job_id)
    if status:
        query["status"] = status
    return list(applications.find(query).sort("match_score", DESCENDING))


def get_application(application_id: str):
    return applications.find_one({"_id": oid(application_id)})


def update_application_status(application_id: str, new_status: str):
    applications.update_one(
        {"_id": oid(application_id)},
        {"$set": {"status": new_status},
         "$push": {"status_history": {"status": new_status, "timestamp": datetime.now()}}},
    )


def get_applications_for_candidate(candidate_id: str):
    return list(applications.find({"candidate_id": oid(candidate_id)}))


def check_duplicate_application(candidate_id: str, job_id: str) -> bool:
    return applications.find_one({"candidate_id": oid(candidate_id), "job_id": oid(job_id)}) is not None


# ---------------------------------------------------------------------------
# Interviews
# ---------------------------------------------------------------------------
def schedule_interview(application_id: str, date_str: str, time_str: str, round_type: str, scheduled_by: str) -> str:
    doc = {
        "application_id": oid(application_id), "date": date_str, "time": time_str,
        "round_type": round_type, "scheduled_by": scheduled_by,
        "calendar_invite_sent": False, "created_at": datetime.now(),
    }
    result = interviews.insert_one(doc)
    return str(result.inserted_id)


def get_interviews(application_id=None):
    query = {"application_id": oid(application_id)} if application_id else {}
    return list(interviews.find(query).sort("date", DESCENDING))


def get_todays_interviews(today_str: str):
    return list(interviews.find({"date": today_str}))


# ---------------------------------------------------------------------------
# Email templates & log
# ---------------------------------------------------------------------------
def get_email_template(stage: str):
    return email_templates.find_one({"stage": stage})


def update_email_template(stage: str, subject: str, body: str):
    email_templates.update_one({"stage": stage}, {"$set": {"subject": subject, "body": body}}, upsert=True)


def get_all_email_templates():
    return list(email_templates.find())


def log_email(application_id, stage, subject, status):
    emails.insert_one({
        "application_id": oid(application_id) if application_id else None,
        "stage": stage, "subject": subject, "status": status, "sent_at": datetime.now(),
    })


def get_email_log(application_id=None):
    query = {"application_id": oid(application_id)} if application_id else {}
    return list(emails.find(query).sort("sent_at", DESCENDING))


def has_email_been_sent(application_id: str, stage: str) -> bool:
    return emails.find_one({
        "application_id": oid(application_id), "stage": stage, "status": "Sent",
    }) is not None


# ---------------------------------------------------------------------------
# Notifications
# ---------------------------------------------------------------------------
def get_notifications(target="HR", unread_only=False):
    query = {"target": target}
    if unread_only:
        query["is_read"] = False
    return list(notifications.find(query).sort("created_at", DESCENDING).limit(50))


def mark_notifications_read(target="HR"):
    notifications.update_many({"target": target}, {"$set": {"is_read": True}})


# ---------------------------------------------------------------------------
# Offers
# ---------------------------------------------------------------------------
def create_offer(application_id: str, salary: str, designation: str, joining_date: str, pdf_path: str) -> str:
    doc = {
        "application_id": oid(application_id), "salary": salary, "designation": designation,
        "joining_date": joining_date, "pdf_path": pdf_path, "generated_at": datetime.now(),
    }
    result = offers.insert_one(doc)
    return str(result.inserted_id)


def get_offer(application_id: str):
    return offers.find_one({"application_id": oid(application_id)})


# ---------------------------------------------------------------------------
# Users (Admin panel)
# ---------------------------------------------------------------------------
def get_all_users():
    return list(users.find())


def deactivate_user(user_id: str):
    users.update_one({"_id": oid(user_id)}, {"$set": {"active": False}})


def get_system_logs(limit=200):
    return list(system_logs.find().sort("timestamp", DESCENDING).limit(limit))


# ---------------------------------------------------------------------------
# Sessions (persistent login across browser refresh)
# ---------------------------------------------------------------------------
def create_session(username: str, role: str) -> str:
    """Create a login token and store it server-side so a browser refresh
    (which starts a fresh Streamlit session) can restore the login by
    looking up the token carried in the URL query parameter."""
    token = uuid.uuid4().hex
    sessions.insert_one({
        "token": token, "username": username, "role": role,
        "created_at": datetime.now(),
        "expires_at": datetime.now() + timedelta(hours=SESSION_LIFETIME_HOURS),
    })
    return token


def get_session(token: str):
    if not token:
        return None
    doc = sessions.find_one({"token": token})
    if not doc:
        return None
    if doc["expires_at"] < datetime.now():
        sessions.delete_one({"token": token})
        return None
    return doc


def delete_session(token: str):
    if token:
        sessions.delete_one({"token": token})


# ---------------------------------------------------------------------------
# Login rate limiting (brute-force protection)
# ---------------------------------------------------------------------------
def record_failed_login(username: str):
    login_attempts.insert_one({"username": username, "last_attempt_at": datetime.now()})


def is_locked_out(username: str):
    """Returns (locked: bool, minutes_remaining: float)."""
    cutoff = datetime.now() - timedelta(minutes=LOCKOUT_MINUTES)
    recent = list(login_attempts.find({"username": username, "last_attempt_at": {"$gte": cutoff}}))
    if len(recent) >= MAX_LOGIN_ATTEMPTS:
        oldest = min(a["last_attempt_at"] for a in recent)
        unlock_at = oldest + timedelta(minutes=LOCKOUT_MINUTES)
        remaining = max(0, (unlock_at - datetime.now()).total_seconds() / 60)
        return True, round(remaining, 1)
    return False, 0


def clear_login_attempts(username: str):
    login_attempts.delete_many({"username": username})


def set_password(username: str, new_password_hash: str):
    users.update_one({"username": username},
                      {"$set": {"password_hash": new_password_hash, "force_password_change": False}})


# ---------------------------------------------------------------------------
# Forgot Password (self-service, via email — reuses the SMTP settings already
# configured for the portal's other automatic emails, so no new external
# integration is required beyond what's already set up in Branding & AI).
# ---------------------------------------------------------------------------
def create_password_reset_code(username: str):
    """Generates a 6-digit reset code for an existing user. Returns None if
    the username doesn't exist (caller should show a generic message either
    way, so this can't be used to enumerate valid usernames)."""
    import random
    user = users.find_one({"username": username})
    if not user:
        return None
    code = f"{random.randint(0, 999999):06d}"
    password_reset_codes.delete_many({"username": username})  # invalidate any earlier codes
    password_reset_codes.insert_one({
        "username": username, "code": code,
        "expires_at": datetime.now() + timedelta(minutes=PASSWORD_RESET_CODE_LIFETIME_MINUTES),
        "created_at": datetime.now(),
    })
    return code


def verify_password_reset_code(username: str, code: str) -> bool:
    doc = password_reset_codes.find_one({"username": username, "code": code})
    if not doc:
        return False
    if doc["expires_at"] < datetime.now():
        password_reset_codes.delete_one({"_id": doc["_id"]})
        return False
    return True


def consume_password_reset_code(username: str):
    password_reset_codes.delete_many({"username": username})


def admin_reset_password(username: str) -> str:
    """Zero-dependency fallback: Admin generates a random temporary password
    for any user directly (no email required), and the user is forced to
    change it on their next login."""
    import secrets
    temp_password = secrets.token_urlsafe(9)  # ~12 readable characters
    users.update_one({"username": username},
                      {"$set": {"password_hash": _hash_for_reset(temp_password), "force_password_change": True}})
    return temp_password


def _hash_for_reset(password: str) -> str:
    import auth  # local import to avoid circular import
    return auth.hash_password(password)


# ---------------------------------------------------------------------------
# Employees (created once a candidate's application reaches 'Joined')
# ---------------------------------------------------------------------------
def generate_employee_id() -> str:
    count = employees.count_documents({})
    return f"EMP-{count + 1:04d}"


def create_employee(data: dict) -> str:
    data["employee_id"] = generate_employee_id()
    data["created_at"] = datetime.now()
    data["status"] = "Active"
    result = employees.insert_one(data)
    return str(result.inserted_id)


def get_employee_by_application(application_id: str):
    return employees.find_one({"application_id": oid(application_id)})


def get_all_employees():
    return list(employees.find().sort("created_at", DESCENDING))


def update_employee(employee_id: str, data: dict):
    employees.update_one({"_id": oid(employee_id)}, {"$set": data})


# ---------------------------------------------------------------------------
# Background tasks (lightweight Mongo-backed queue for the worker process —
# no Redis/Celery needed at this scale, which also means fewer exposed
# services/ports for someone to attack)
# ---------------------------------------------------------------------------
def create_background_task(task_type: str, payload: dict) -> str:
    doc = {
        "type": task_type, "payload": payload, "status": "queued",
        "progress": 0, "total": payload.get("total", 0), "result": {},
        "created_at": datetime.now(), "updated_at": datetime.now(),
    }
    result = background_tasks.insert_one(doc)
    return str(result.inserted_id)


def get_background_task(task_id: str):
    return background_tasks.find_one({"_id": oid(task_id)})


def update_background_task(task_id: str, **fields):
    fields["updated_at"] = datetime.now()
    background_tasks.update_one({"_id": oid(task_id)}, {"$set": fields})


def claim_next_task():
    """Atomically claim the oldest queued task (used by worker.py)."""
    return background_tasks.find_one_and_update(
        {"status": "queued"},
        {"$set": {"status": "processing", "updated_at": datetime.now()}},
        sort=[("created_at", 1)],
    )


# ---------------------------------------------------------------------------
# Pagination helpers (so large candidate/job lists stay fast and responsive)
# ---------------------------------------------------------------------------
def count_jobs(status=None) -> int:
    query = {"status": status} if status else {}
    return jobs.count_documents(query)


def get_jobs_paginated(page: int = 1, page_size: int = 20, status=None):
    query = {"status": status} if status else {}
    skip = (page - 1) * page_size
    return list(jobs.find(query).sort("created_at", DESCENDING).skip(skip).limit(page_size))


def count_candidates() -> int:
    return candidates.count_documents({})


def get_candidates_paginated(page: int = 1, page_size: int = 20):
    skip = (page - 1) * page_size
    return list(candidates.find().sort("created_at", DESCENDING).skip(skip).limit(page_size))


def count_applications(job_id=None, status=None) -> int:
    query = {}
    if job_id:
        query["job_id"] = oid(job_id)
    if status:
        query["status"] = status
    return applications.count_documents(query)


def get_applications_paginated(job_id=None, status=None, page: int = 1, page_size: int = 20):
    query = {}
    if job_id:
        query["job_id"] = oid(job_id)
    if status:
        query["status"] = status
    skip = (page - 1) * page_size
    return list(applications.find(query).sort("match_score", DESCENDING).skip(skip).limit(page_size))

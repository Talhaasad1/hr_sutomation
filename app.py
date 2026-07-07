"""
ATS Portal — Industry-Level HR Automation System
Public Career Portal (apply with name/phone/email + resume) +
HR/Recruiter/Admin backend with AI resume screening, ranking, ATS pipeline,
interview scheduling, email automation, analytics, and an admin panel.

Run with: streamlit run app.py
(Requires a running MongoDB instance — see README.md)
"""

import io
import os
from datetime import datetime, timedelta

import streamlit as st

import db
import auth
import ui
import config
import resume_parser
import matching
import email_service
import hr_pages
import admin_pages

st.set_page_config(page_title="ATS Portal", page_icon="🧑‍💼", layout="wide")
db.init_db()
ui.inject_custom_css()

import streamlit as st

# 1. Page config (agar pehle se add hai toh theek hai)
st.set_page_config(page_title="My App", layout="wide")

# 2. Top right options aur bottom footer/manage app ko hide karne ke liye CSS
hide_elements_css = """
    <style>
    /* Top right par hamburger menu aur buttons ko hide karne ke liye */
    #MainMenu {visibility: hidden;}
    header {visibility: hidden;}
    
    /* Bottom right footer aur 'Manage app' button ko hide karne ke liye */
    footer {visibility: hidden;}
    div[data-testid="stDecoration"] {display: none;}
    </style>
"""

st.markdown(hide_elements_css, unsafe_allow_html=True)

defaults = {
    "mode": "career",       # "career" (public) or "staff" (logged-in backend)
    "logged_in": False,
    "user": None,
    "active_page": "dashboard",
    "logo_bytes": None,
    "applied_success": False,
    "pending_set_cookie": None,
    "pending_clear_cookie": False,
}
for k, v in defaults.items():
    if k not in st.session_state:
        st.session_state[k] = v

if st.session_state.logo_bytes is None:
    logo_path = db.get_setting_value("logo_path", "")
    if logo_path:
        try:
            with open(logo_path, "rb") as f:
                st.session_state.logo_bytes = f.read()
        except FileNotFoundError:
            pass


def _write_cookie(name: str, value: str, max_age_seconds: int):
    """Set a browser cookie via a tiny inline script — this uses Streamlit's
    own built-in st.iframe (raw HTML string mode), no third-party package,
    so it doesn't have the version-compatibility problems a full custom
    component can have. The cookie is private to this browser; it is NOT
    part of the URL, so copying/sharing the page link never logs anyone else in."""
    st.iframe(
        f"<script>document.cookie = '{name}={value}; path=/; max-age={max_age_seconds}; SameSite=Lax';</script>",
        height=1,
    )


def _clear_cookie(name: str):
    st.iframe(
        f"<script>document.cookie = '{name}=; path=/; max-age=0';</script>",
        height=1,
    )


# Restore login from the browser cookie, if present, so a refresh doesn't log
# the user out — but pasting the URL into a different browser will NOT be
# logged in, since the token lives in a cookie, not the URL.
if not st.session_state.logged_in:
    token = st.context.cookies.get("ats_token")
    if token:
        session_doc = db.get_session(token)
        if session_doc:
            user = db.users.find_one({"username": session_doc["username"]})
            if user:
                st.session_state.logged_in = True
                st.session_state.user = user
                st.session_state.mode = "staff"

# Apply any pending cookie write/clear queued by a login/logout action on the
# previous rerun. Doing this once, up front, keeps the cookie logic in one
# place regardless of which page ends up rendering below.
if st.session_state.pending_set_cookie:
    tok, max_age = st.session_state.pending_set_cookie
    _write_cookie("ats_token", tok, max_age)
    st.session_state.pending_set_cookie = None
if st.session_state.pending_clear_cookie:
    _clear_cookie("ats_token")
    st.session_state.pending_clear_cookie = False


# ---------------------------------------------------------------------------
# CAREER PORTAL (public — no login required)
# ---------------------------------------------------------------------------
def career_portal():
    db.auto_close_expired_jobs()
    company_name = db.get_setting_value("company_name", "Your Company")
    ui.render_header(company_name, st.session_state.logo_bytes)

    top_l, top_r = st.columns([5, 1.3])
    with top_r:
        if st.button("HR / Staff Login", width="stretch"):
            st.session_state.mode = "staff"
            st.rerun()

    st.markdown("## Open Positions")
    jobs = db.get_jobs(status="Open")
    if not jobs:
        st.info("There are no open positions right now. Please check back later.")
        return

    job_titles = {f"{j['title']} — {j.get('location','')}": j for j in jobs}
    choice = st.selectbox("Select a job to view details & apply", list(job_titles.keys()))
    job = job_titles[choice]

    st.markdown(f"""<div class="job-card">
        <h3>{ui.esc(job['title'])}</h3>
        <span class="hr-badge">{ui.esc(job.get('department',''))}</span>
        &nbsp;<span class="hr-badge">{ui.esc(job.get('location',''))}</span>
        &nbsp;<span class="hr-badge">{ui.esc(job.get('experience_required','N/A'))}</span><br><br>
        <b>Salary Range:</b> {ui.esc(job.get('salary_range','N/A'))}<br>
        <b>Skills Required:</b> {ui.esc(', '.join(job.get('skills_required', [])) or 'N/A')}<br>
        <b>Apply Before:</b> {ui.esc(job.get('last_date','N/A'))}<br><br>
        {ui.esc(job['description']).replace(chr(10), '<br>')}
        </div>""", unsafe_allow_html=True)

    st.markdown("### Apply for this Job")
    if st.session_state.applied_success:
        st.success("✅ Your application has been submitted successfully! You will hear back from us via email.")
        if st.button("Submit another application"):
            st.session_state.applied_success = False
            st.rerun()
        return

    with st.form("apply_form"):
        c1, c2, c3 = st.columns(3)
        name = c1.text_input("Full Name *")
        email = c2.text_input("Email *")
        phone = c3.text_input("Phone *")
        resume_file = st.file_uploader("Upload Resume (PDF or DOCX) *", type=["pdf", "docx"])
        submitted = st.form_submit_button("Submit Application", type="primary")

    if submitted:
        if not name.strip() or not email.strip() or not phone.strip() or resume_file is None:
            st.error("Name, Email, Phone, and Resume are all required — you cannot apply without them.")
            return

        import re as _re
        if not _re.match(r"^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+$", email.strip()):
            st.error("Please enter a valid email address.")
            return
        if not _re.match(r"^[0-9+\-\s()]{7,20}$", phone.strip()):
            st.error("Please enter a valid phone number.")
            return

        raw_bytes = resume_file.getvalue()

        # File size limit (defends against denial-of-service via huge uploads)
        if len(raw_bytes) > db.MAX_RESUME_SIZE_MB * 1024 * 1024:
            st.error(f"File is too large. Please upload a resume under {db.MAX_RESUME_SIZE_MB} MB.")
            return

        # Magic-byte check: verify the file content actually matches its extension,
        # rather than trusting the filename alone (a common way to smuggle disguised files)
        ext = resume_file.name.rsplit(".", 1)[-1].lower()
        is_valid_pdf = ext == "pdf" and raw_bytes[:4] == b"%PDF"
        is_valid_docx = ext == "docx" and raw_bytes[:2] == b"PK"  # docx is a zip archive
        if not (is_valid_pdf or is_valid_docx):
            st.error("The uploaded file doesn't look like a valid PDF or DOCX. Please re-export and try again.")
            return

        # Read the raw file bytes once (so we can both parse it AND save the
        # original file to disk for later download from the candidate profile).
        resume_data = resume_parser.parse_resume(io.BytesIO(raw_bytes), resume_file.name)
        if not resume_data["email"]:
            resume_data["email"] = email

        # Duplicate resume detection
        dup = matching.check_duplicate_resume(resume_data["text_hash"])
        is_duplicate = dup is not None

        # Save the actual CV file to disk so HR can download the original later
        safe_email = email.replace("@", "_at_").replace(".", "_")
        resume_filename = f"{safe_email}_{int(datetime.now().timestamp())}.{ext}"
        resume_file_path = os.path.join(config.RESUME_DIR, resume_filename)
        with open(resume_file_path, "wb") as f:
            f.write(raw_bytes)

        existing = db.find_candidate_by_email(email)
        candidate_fields = {
            "name": name, "phone": phone, "resume_data": resume_data, "is_duplicate": is_duplicate,
            "resume_file_path": resume_file_path, "resume_filename": resume_file.name,
        }
        if existing:
            candidate_id = str(existing["_id"])
            db.update_candidate(candidate_id, candidate_fields)
        else:
            candidate_id = db.create_candidate({"email": email, **candidate_fields})

        if db.check_duplicate_application(candidate_id, str(job["_id"])):
            st.warning("You have already applied for this job with this email address.")
            return

        # AI-driven evaluation (match score, skills, experience) — falls back
        # to the deterministic TF-IDF evaluator if no AI provider is configured.
        jd_skills = job.get("skills_required", [])
        ai_provider, ai_key = db.get_ai_config()
        screening = matching.evaluate_resume(
            job["description"], jd_skills, resume_data["raw_text"], resume_data["skills"],
            name, provider=ai_provider, api_key=ai_key,
        )

        application_id = db.create_application(candidate_id, str(job["_id"]), screening)
        db.log_action(name, "Applied for Job", job["title"])

        # Automatic "Application Received" email (uses saved SMTP settings, if configured)
        smtp_server = db.get_setting_value("smtp_server")
        sender_email = db.get_setting_value("sender_email")
        sender_password = db.get_setting_value("sender_password")
        if smtp_server and sender_email and sender_password:
            email_service.send_stage_email(
                {"smtp_server": smtp_server, "smtp_port": int(db.get_setting_value("smtp_port", "587") or 587),
                 "sender_email": sender_email, "sender_password": sender_password},
                application_id, "Application Received",
                {"candidate_name": name, "candidate_email": email, "job_title": job["title"]},
            )

        st.session_state.applied_success = True
        st.rerun()


# ---------------------------------------------------------------------------
# STAFF LOGIN
# ---------------------------------------------------------------------------
def login_page():
    company_name = db.get_setting_value("company_name", "Your Company")
    left, right = st.columns([1, 1])
    with left:
        st.markdown("<br>", unsafe_allow_html=True)
        st.markdown(f"### 👋 Welcome to **{company_name}**")
        st.markdown("#### HR / Recruiter / Admin Login")
        with st.form("login_form"):
            username = st.text_input("Username")
            password = st.text_input("Password", type="password")
            submitted = st.form_submit_button("Login", width="stretch")
            if submitted:
                locked, minutes_left = db.is_locked_out(username)
                if locked:
                    st.error(f"Too many failed attempts. Try again in {minutes_left} minute(s).")
                else:
                    user = auth.login(username, password)
                    if user:
                        db.clear_login_attempts(username)
                        token = db.create_session(user["username"], user["role"])
                        st.session_state.logged_in = True
                        st.session_state.user = user
                        st.session_state.pending_set_cookie = (token, db.SESSION_LIFETIME_HOURS * 3600)
                        st.rerun()
                    else:
                        db.record_failed_login(username)
                        st.error("Invalid username or password.")
        st.caption("Demo credentials → username: `admin` | password: `admin123`")
        if st.button("← Back to Career Portal"):
            st.session_state.mode = "career"
            st.rerun()
    with right:
        st.markdown(ui.login_illustration_svg(), unsafe_allow_html=True)


# ---------------------------------------------------------------------------
# STAFF PORTAL (role-based dashboard)
# ---------------------------------------------------------------------------
PAGES = {
    "dashboard": hr_pages.dashboard_page,
    "jobs": hr_pages.jobs_page,
    "applications": hr_pages.applications_page,
    "profiles": hr_pages.candidate_profiles_page,
    "interviews": hr_pages.interviews_page,
    "onboarding": hr_pages.onboarding_page,
    "emails": hr_pages.emails_page,
    "search": hr_pages.search_page,
    "notifications": hr_pages.notifications_page,
    "admin": admin_pages.admin_panel_page,
}


def staff_portal():
    company_name = db.get_setting_value("company_name", "Your Company")
    ui.render_header(company_name, st.session_state.logo_bytes)
    hr_pages.notification_toast_fragment()

    top_l, top_r = st.columns([5, 1.3])
    with top_r:
        role = st.session_state.user["role"]
        st.markdown(f"👋 **{st.session_state.user['username']}** ({role})")
        c1, c2 = st.columns(2)
        if c1.button("Career Portal", width="stretch"):
            st.session_state.mode = "career"
            st.rerun()
        if c2.button("Logout", width="stretch"):
            token = st.context.cookies.get("ats_token")
            db.delete_session(token)
            st.session_state.pending_clear_cookie = True
            st.session_state.logged_in = False
            st.session_state.user = None
            st.rerun()

    nav_items = ui.ADMIN_NAV_ITEMS if role == "Admin" else ui.HR_NAV_ITEMS

    col_main, col_nav = st.columns([5, 1.3])
    with col_nav:
        with st.container(border=True):
            unread = len(db.get_notifications("HR", unread_only=True))
            if unread:
                st.markdown(f"🔔 **{unread} new notification(s)**")
            selected = ui.render_right_nav(st.session_state.active_page, nav_items)
    if selected != st.session_state.active_page:
        st.session_state.active_page = selected
        st.rerun()

    with col_main:
        PAGES[st.session_state.active_page]()


def force_password_change_page():
    st.markdown("## 🔒 Set a New Password")
    st.warning("You're using the default seeded account. For security, please set a new password before continuing.")
    with st.form("force_pw_form"):
        new_pw = st.text_input("New Password", type="password")
        confirm_pw = st.text_input("Confirm New Password", type="password")
        submitted = st.form_submit_button("Set Password", type="primary")
        if submitted:
            if len(new_pw) < 8:
                st.error("Password must be at least 8 characters long.")
            elif new_pw != confirm_pw:
                st.error("Passwords do not match.")
            else:
                db.set_password(st.session_state.user["username"], auth.hash_password(new_pw))
                st.session_state.user["force_password_change"] = False
                st.success("Password updated. Reloading...")
                st.rerun()


# ---------------------------------------------------------------------------
# MAIN
# ---------------------------------------------------------------------------
def main():
    if st.session_state.mode == "career" and not st.session_state.logged_in:
        career_portal()
    elif st.session_state.logged_in:
        if st.session_state.user.get("force_password_change"):
            force_password_change_page()
        else:
            staff_portal()
    else:
        login_page()


if __name__ == "__main__":
    main()

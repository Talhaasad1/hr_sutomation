import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from datetime import date, timedelta

import db


def setup_function():
    import config
    db._client.drop_database(config.DB_NAME)
    db.init_db()


def test_auto_close_expired_jobs():
    yesterday = (date.today() - timedelta(days=1)).isoformat()
    tomorrow = (date.today() + timedelta(days=1)).isoformat()

    expired_id = db.create_job({
        "title": "Expired Job", "department": "Engineering", "location": "Lahore",
        "salary_range": "100-200", "experience_required": "2y", "skills_required": ["python"],
        "last_date": yesterday, "description": "test",
    }, "admin")
    active_id = db.create_job({
        "title": "Active Job", "department": "Engineering", "location": "Lahore",
        "salary_range": "100-200", "experience_required": "2y", "skills_required": ["python"],
        "last_date": tomorrow, "description": "test",
    }, "admin")

    assert db.get_job(expired_id)["status"] == "Open"
    assert db.get_job(active_id)["status"] == "Open"

    closed_count = db.auto_close_expired_jobs()
    assert closed_count == 1
    assert db.get_job(expired_id)["status"] == "Closed"
    assert db.get_job(active_id)["status"] == "Open"

    # idempotent
    assert db.auto_close_expired_jobs() == 0


def test_employee_creation_and_id_generation():
    job_id = db.create_job({
        "title": "Developer", "department": "Engineering", "location": "Lahore",
        "salary_range": "100-200", "experience_required": "2y", "skills_required": [],
        "last_date": "2099-01-01", "description": "test",
    }, "admin")
    cand_id = db.create_candidate({
        "name": "Ahmed", "email": "ahmed@x.com", "phone": "0300",
        "resume_data": {}, "is_duplicate": False,
    })
    app_id = db.create_application(cand_id, job_id, {
        "match_score": 90, "missing_skills": [], "strong_skills": [], "weak_areas": [], "recommendation": "Shortlist",
    })

    emp_id = db.create_employee({
        "application_id": db.oid(app_id), "candidate_id": db.oid(cand_id),
        "name": "Ahmed", "email": "ahmed@x.com", "phone": "0300",
        "designation": "Developer", "department": "Engineering", "salary": "120000",
        "joining_date": "2026-08-01", "employment_type": "Full-time", "manager": "Sana",
        "bank_account": "123", "tax_id": "CNIC-1",
    })
    emp = db.get_employee_by_application(app_id)
    assert emp["employee_id"] == "EMP-0001"
    assert emp["status"] == "Active"

    # editing works and preserves employee_id
    db.update_employee(emp_id, {"status": "Resigned", "designation": "Senior Developer"})
    updated = db.get_employee_by_application(app_id)
    assert updated["status"] == "Resigned"
    assert updated["designation"] == "Senior Developer"
    assert updated["employee_id"] == "EMP-0001"


def test_employee_status_options_include_expected_values():
    for expected in ["Active", "Resigned", "Transferred", "Terminated"]:
        assert expected in db.EMPLOYEE_STATUS_OPTIONS


def test_joined_email_template_exists_and_renders():
    import email_service
    tpl = db.get_email_template("Joined")
    assert tpl is not None
    subject, body = email_service.render_template(tpl, {"candidate_name": "Ahmed", "job_title": "Developer"})
    assert "Ahmed" in subject
    assert "Developer" in body


def test_department_names_helper():
    names = db.get_department_names()
    assert "Engineering" in names
    assert names == sorted(names)


def test_offer_and_status_transition_flow():
    job_id = db.create_job({
        "title": "Developer", "department": "Engineering", "location": "Lahore",
        "salary_range": "100-200", "experience_required": "2y", "skills_required": [],
        "last_date": "2099-01-01", "description": "test",
    }, "admin")
    cand_id = db.create_candidate({
        "name": "Ahmed", "email": "ahmed@x.com", "phone": "0300",
        "resume_data": {}, "is_duplicate": False,
    })
    app_id = db.create_application(cand_id, job_id, {
        "match_score": 90, "missing_skills": [], "strong_skills": [], "weak_areas": [], "recommendation": "Shortlist",
    })
    db.update_application_status(app_id, "Selected")
    assert db.get_application(app_id)["status"] == "Selected"

    db.create_offer(app_id, "120000", "Developer", "2026-08-01", "/tmp/fake_offer.pdf")
    db.update_application_status(app_id, "Offer Sent")
    assert db.get_application(app_id)["status"] == "Offer Sent"
    assert db.get_offer(app_id)["salary"] == "120000"

    db.update_application_status(app_id, "Joined")
    assert db.get_application(app_id)["status"] == "Joined"

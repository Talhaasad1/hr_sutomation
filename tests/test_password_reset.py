import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from datetime import datetime, timedelta

import db
import auth


def setup_function():
    import config
    db._client.drop_database(config.DB_NAME)
    db.init_db()


def test_admin_reset_password_zero_dependency():
    temp_password = db.admin_reset_password("admin")
    assert temp_password
    user = auth.login("admin", temp_password)
    assert user is not None
    assert user["force_password_change"] is True
    # old password no longer works
    assert auth.login("admin", "admin123") is None


def test_create_user_with_email_for_self_service_reset():
    ok, msg = auth.create_user("recruiter1", "pass123", "Recruiter", email="r1@example.com")
    assert ok is True
    user = db.users.find_one({"username": "recruiter1"})
    assert user["email"] == "r1@example.com"
    assert user["force_password_change"] is True  # new accounts must set their own password too


def test_password_reset_code_lifecycle():
    auth.create_user("recruiter1", "pass123", "Recruiter", email="r1@example.com")
    code = db.create_password_reset_code("recruiter1")
    assert len(code) == 6

    assert db.verify_password_reset_code("recruiter1", "000000") is False
    assert db.verify_password_reset_code("recruiter1", code) is True

    db.set_password("recruiter1", auth.hash_password("NewPass456"))
    db.consume_password_reset_code("recruiter1")
    assert auth.login("recruiter1", "NewPass456") is not None

    # code can't be reused after consumption
    assert db.verify_password_reset_code("recruiter1", code) is False


def test_password_reset_code_expires():
    auth.create_user("recruiter1", "pass123", "Recruiter", email="r1@example.com")
    db.password_reset_codes.insert_one({
        "username": "recruiter1", "code": "999999",
        "expires_at": datetime.now() - timedelta(minutes=1), "created_at": datetime.now(),
    })
    assert db.verify_password_reset_code("recruiter1", "999999") is False


def test_create_password_reset_code_invalidates_previous_codes():
    auth.create_user("recruiter1", "pass123", "Recruiter", email="r1@example.com")
    code1 = db.create_password_reset_code("recruiter1")
    code2 = db.create_password_reset_code("recruiter1")
    assert db.verify_password_reset_code("recruiter1", code1) is False
    assert db.verify_password_reset_code("recruiter1", code2) is True


def test_ai_failure_is_logged_for_admin_visibility():
    import matching
    result = matching._call_provider("Gemini", "fake-invalid-key", "test prompt")
    assert result is None
    logs = db.get_system_logs()
    ai_logs = [l for l in logs if "AI Screening Failed" in l["action"]]
    assert len(ai_logs) > 0

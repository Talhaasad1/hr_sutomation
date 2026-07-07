import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import db
import auth


def setup_function():
    """Reset the in-memory database before every test."""
    import config
    db._client.drop_database(config.DB_NAME)
    db.init_db()


def test_default_admin_seeded_with_force_password_change():
    admin = db.users.find_one({"username": "admin"})
    assert admin is not None
    assert admin["force_password_change"] is True


def test_login_success():
    user = auth.login("admin", "admin123")
    assert user is not None
    assert user["role"] == "Admin"


def test_login_wrong_password_fails():
    assert auth.login("admin", "wrongpassword") is None


def test_password_hashing_is_not_plaintext():
    h = auth.hash_password("mypassword")
    assert h != "mypassword"
    assert auth.verify_password("mypassword", h) is True
    assert auth.verify_password("wrong", h) is False


def test_login_lockout_after_max_attempts():
    for _ in range(db.MAX_LOGIN_ATTEMPTS):
        db.record_failed_login("admin")
    locked, minutes = db.is_locked_out("admin")
    assert locked is True
    assert minutes > 0


def test_login_not_locked_before_max_attempts():
    for _ in range(db.MAX_LOGIN_ATTEMPTS - 1):
        db.record_failed_login("someuser")
    locked, _ = db.is_locked_out("someuser")
    assert locked is False


def test_clear_login_attempts():
    for _ in range(db.MAX_LOGIN_ATTEMPTS):
        db.record_failed_login("admin")
    db.clear_login_attempts("admin")
    locked, _ = db.is_locked_out("admin")
    assert locked is False


def test_password_change_clears_force_flag():
    db.set_password("admin", auth.hash_password("NewPass123"))
    admin = db.users.find_one({"username": "admin"})
    assert admin["force_password_change"] is False
    assert auth.login("admin", "NewPass123") is not None
    assert auth.login("admin", "admin123") is None


def test_create_user_rejects_duplicate_username():
    ok1, _ = auth.create_user("recruiter1", "pass123", "Recruiter")
    ok2, msg2 = auth.create_user("recruiter1", "otherpass", "Recruiter")
    assert ok1 is True
    assert ok2 is False
    assert "already exists" in msg2.lower()

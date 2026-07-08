"""
auth.py
Authentication helpers: password hashing (bcrypt) and login verification
against the `users` collection. Roles: Admin, HR, Recruiter.
"""

import bcrypt


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("utf-8"))
    except (ValueError, AttributeError):
        return False


def login(username: str, password: str):
    """Returns the user document (dict) if credentials are valid, else None."""
    import db  # local import to avoid circular import at module load time

    user = db.users.find_one({"username": username})
    if user and user.get("active", True) and verify_password(password, user["password_hash"]):
        return user
    return None


def create_user(username: str, password: str, role: str, department: str = "", email: str = ""):
    import db

    if db.users.find_one({"username": username}):
        return False, "Username already exists."
    db.users.insert_one({
        "username": username, "password_hash": hash_password(password),
        "role": role, "department": department, "email": email, "active": True,
        "force_password_change": True,
    })
    return True, "User created successfully."

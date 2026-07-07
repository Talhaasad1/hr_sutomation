import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import db
import resume_parser
import matching
import ui


def setup_function():
    import config
    db._client.drop_database(config.DB_NAME)
    db.init_db()


def test_extract_email():
    assert resume_parser.extract_email("Contact me at jane@example.com please") == "jane@example.com"


def test_extract_skills():
    text = "Experienced in Python, SQL, and Docker."
    skills = resume_parser.extract_skills(text)
    assert "python" in skills
    assert "sql" in skills
    assert "docker" in skills


def test_extract_linkedin_and_github():
    text = "linkedin.com/in/janedoe github.com/janedoe"
    assert resume_parser.extract_linkedin(text) != ""
    assert resume_parser.extract_github(text) != ""


def test_resume_hash_is_deterministic():
    h1 = resume_parser.resume_text_hash("Some resume text")
    h2 = resume_parser.resume_text_hash("Some resume text")
    h3 = resume_parser.resume_text_hash("Different text")
    assert h1 == h2
    assert h1 != h3


def test_evaluate_resume_fallback_without_ai_key():
    jd = "Need a Python developer with SQL and Docker skills."
    jd_skills = ["python", "sql", "docker"]
    resume = "I know python, sql, and docker very well. 5 years experience."
    resume_skills = resume_parser.extract_skills(resume)
    result = matching.evaluate_resume(jd, jd_skills, resume, resume_skills, "Jane Doe", provider=None, api_key=None)
    assert result["match_score"] > 0
    assert "TF-IDF" in result["screening_method"]


def test_evaluate_resume_falls_back_on_invalid_provider():
    jd = "Need a Python developer."
    jd_skills = ["python"]
    resume = "I know python."
    resume_skills = resume_parser.extract_skills(resume)
    result = matching.evaluate_resume(jd, jd_skills, resume, resume_skills, "Jane", provider="NotARealProvider", api_key="fake")
    assert "TF-IDF" in result["screening_method"]


def test_ai_screen_resume_returns_none_without_key():
    assert matching.ai_screen_resume("Claude", "", "jd", [], "resume", [], "Jane") is None
    assert matching.ai_screen_resume(None, "fake-key", "jd", [], "resume", [], "Jane") is None


def test_strong_match_scores_higher_than_weak_match():
    jd = "Need a Python developer with SQL and Docker skills."
    jd_skills = ["python", "sql", "docker"]
    strong_resume = "Expert in python, sql, docker."
    weak_resume = "I only know marketing and sales."
    strong = matching.evaluate_resume(jd, jd_skills, strong_resume, resume_parser.extract_skills(strong_resume), "A", api_key=None)
    weak = matching.evaluate_resume(jd, jd_skills, weak_resume, resume_parser.extract_skills(weak_resume), "B", api_key=None)
    assert strong["match_score"] > weak["match_score"]


def test_rank_applications_sorts_descending():
    apps = [{"match_score": 40}, {"match_score": 90}, {"match_score": 60}]
    ranked = matching.rank_applications(apps)
    scores = [a["match_score"] for a in ranked]
    assert scores == sorted(scores, reverse=True)


def test_duplicate_resume_detection():
    text_hash = resume_parser.resume_text_hash("identical resume content")
    db.create_candidate({
        "name": "First", "email": "first@x.com", "phone": "0300",
        "resume_data": {"text_hash": text_hash}, "is_duplicate": False,
    })
    dup = matching.check_duplicate_resume(text_hash)
    assert dup is not None
    no_dup = matching.check_duplicate_resume(resume_parser.resume_text_hash("totally different content"))
    assert no_dup is None


def test_html_escaping_prevents_script_injection():
    malicious = '<script>alert("xss")</script>'
    escaped = ui.esc(malicious)
    assert "<script>" not in escaped
    assert "&lt;script&gt;" in escaped

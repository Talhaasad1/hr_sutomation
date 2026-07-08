"""
matching.py
AI Resume Screening engine:
 - Match Score (%) via TF-IDF + Cosine Similarity between resume and JD
 - Missing Skills / Strong Skills / Weak Areas
 - Recommendation (rule-based; optionally enriched by an LLM — Claude,
   OpenAI, Gemini, or Grok, whichever the Admin has configured)
 - Resume ranking (sort by score — no manual sorting)
 - Duplicate resume detection (via resume text hash)
"""
 
import json
import time
 
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity
 
import db
 
# Supported AI providers for resume screening. Update these model names here
# if a provider releases a newer model — this is the only place they're set.
AI_PROVIDERS = ["Claude", "OpenAI", "Gemini", "Grok", "Groq"]
CLAUDE_MODEL = "claude-sonnet-5"
OPENAI_MODEL = "gpt-4o-mini"
GEMINI_MODEL = "gemini-2.0-flash"
GROK_MODEL = "grok-beta"       # xAI's Grok API is OpenAI-compatible
GROQ_MODEL = "llama-3.3-70b-versatile" 
AI_CALL_TIMEOUT_SECONDS = 20   # hard cap so a slow/unreachable AI API never freezes the portal
AI_RATE_LIMIT_BACKOFF_SECONDS = 3  # short pause before the single retry on a 429
 
 
def compute_match_score(jd_text: str, resume_text: str) -> float:
    if not jd_text.strip() or not resume_text.strip():
        return 0.0
    try:
        vectorizer = TfidfVectorizer(stop_words="english")
        matrix = vectorizer.fit_transform([jd_text, resume_text])
        score = cosine_similarity(matrix[0:1], matrix[1:2])[0][0]
        return round(float(score) * 100, 2)
    except ValueError:
        return 0.0
 
 
def screen_resume(jd_text: str, jd_skills: list, resume_text: str, resume_skills: list) -> dict:
    """
    Rule-based fallback screening (no AI): compares resume to job description
    using TF-IDF + skill overlap and returns match score, missing/strong
    skills, weak areas, and a recommendation. Always available, never
    depends on any external API.
    """
    jd_skills_set = set(s.lower() for s in jd_skills)
    resume_skills_set = set(s.lower() for s in resume_skills)
 
    tfidf_score = compute_match_score(jd_text, resume_text)
    skill_overlap_pct = (
        round(len(resume_skills_set & jd_skills_set) / len(jd_skills_set) * 100, 2)
        if jd_skills_set else 0
    )
    final_score = round((tfidf_score * 0.7) + (skill_overlap_pct * 0.3), 2)
 
    missing_skills = sorted(jd_skills_set - resume_skills_set)
    strong_skills = sorted(jd_skills_set & resume_skills_set)
    weak_areas = missing_skills[:5]  # simple heuristic: unmet requirements are the weak areas
 
    if final_score >= 80:
        recommendation = "Shortlist Candidate"
    elif final_score >= 60:
        recommendation = "Consider for Screening Call"
    elif final_score >= 40:
        recommendation = "Weak Match - Review Manually"
    else:
        recommendation = "Not Recommended"
 
    return {
        "match_score": final_score,
        "tfidf_score": tfidf_score,
        "skill_match_score": skill_overlap_pct,
        "missing_skills": missing_skills,
        "strong_skills": strong_skills,
        "weak_areas": weak_areas,
        "recommendation": recommendation,
    }
 
 
def _build_screening_prompt(jd_text, jd_skills, resume_text, resume_skills, candidate_name) -> str:
    return f"""You are an expert HR resume screener. Evaluate this candidate's resume
against the job description below, considering skills, experience level, and overall fit.
 
Job Description:
{jd_text[:3500]}
 
Required Skills (from job posting): {', '.join(jd_skills) if jd_skills else 'Not specified'}
 
Candidate Name: {candidate_name}
Resume Text:
{resume_text[:3500]}
 
Detected resume skills (keyword-based, may be incomplete): {', '.join(resume_skills) if resume_skills else 'None detected'}
 
Respond with ONLY a valid JSON object (no markdown fences, no preamble) in exactly this shape:
{{
  "match_score": <integer 0-100, overall fit considering skills AND experience>,
  "strong_skills": [<list of the candidate's strongest matching skills/qualifications>],
  "missing_skills": [<list of important skills/requirements from the JD the candidate lacks>],
  "weak_areas": [<list of 1-4 short phrases describing weak areas, e.g. "Limited cloud experience">],
  "recommendation": "<one of: 'Shortlist Candidate', 'Consider for Screening Call', 'Weak Match - Review Manually', 'Not Recommended'>"
}}"""
 
 
def _parse_ai_json_response(raw_text: str):
    """Shared, defensive JSON parsing for whichever provider answered —
    strips markdown code fences some models add despite instructions."""
    if not raw_text:
        return None
    cleaned = raw_text.replace("```json", "").replace("```", "").strip()
    try:
        parsed = json.loads(cleaned)
        return {
            "match_score": round(float(parsed.get("match_score", 0)), 2),
            "strong_skills": list(parsed.get("strong_skills", [])),
            "missing_skills": list(parsed.get("missing_skills", [])),
            "weak_areas": list(parsed.get("weak_areas", [])),
            "recommendation": str(parsed.get("recommendation", "Weak Match - Review Manually")),
        }
    except (json.JSONDecodeError, ValueError, TypeError):
        return None
 
 
def _raw_call_claude(api_key: str, prompt: str):
    import anthropic
    client = anthropic.Anthropic(api_key=api_key, timeout=AI_CALL_TIMEOUT_SECONDS)
    response = client.messages.create(
        model=CLAUDE_MODEL, max_tokens=600,
        messages=[{"role": "user", "content": prompt}],
    )
    return "".join(b.text for b in response.content if getattr(b, "type", "") == "text").strip()
 
 
def _raw_call_openai(api_key: str, prompt: str):
    import openai
    client = openai.OpenAI(api_key=api_key, timeout=AI_CALL_TIMEOUT_SECONDS)
    response = client.chat.completions.create(
        model=OPENAI_MODEL, max_tokens=600,
        response_format={"type": "json_object"},
        messages=[{"role": "user", "content": prompt}],
    )
    return response.choices[0].message.content.strip()
 
 
def _raw_call_gemini(api_key: str, prompt: str):
    # Uses the new unified `google-genai` SDK (the older `google-generativeai`
    # package is deprecated by Google AND uses a low-level gRPC transport whose
    # internal retry loop can ignore per-call timeouts on flaky networks).
    from google import genai
    from google.genai import types
    client = genai.Client(
        api_key=api_key,
        http_options=types.HttpOptions(timeout=AI_CALL_TIMEOUT_SECONDS * 1000),  # milliseconds
    )
    response = client.models.generate_content(model=GEMINI_MODEL, contents=prompt)
    return response.text.strip()
 
 
def _raw_call_grok(api_key: str, prompt: str):
    # xAI's Grok API speaks the OpenAI-compatible protocol, so we reuse the
    # `openai` package with a different base_url instead of a separate SDK.
    import openai
    client = openai.OpenAI(api_key=api_key, base_url="https://api.x.ai/v1", timeout=AI_CALL_TIMEOUT_SECONDS)
    response = client.chat.completions.create(
        model=GROK_MODEL, max_tokens=600,
        messages=[{"role": "user", "content": prompt}],
    )
    return response.choices[0].message.content.strip()

def _raw_call_groq(api_key: str, prompt: str):
    # Groq Cloud's API is also OpenAI-compatible, so we reuse the `openai`
    # package with a different base_url instead of a separate SDK/dependency.
    import openai
    client = openai.OpenAI(api_key=api_key, base_url="https://api.groq.com/openai/v1", timeout=AI_CALL_TIMEOUT_SECONDS)
    response = client.chat.completions.create(
        model=GROQ_MODEL, max_tokens=600,
        response_format={"type": "json_object"},
        messages=[{"role": "user", "content": prompt}],
    )
    return response.choices[0].message.content.strip()
 
 
_RAW_CALLERS = {
    "Claude": _raw_call_claude,
    "OpenAI": _raw_call_openai,
    "Gemini": _raw_call_gemini,
    "Grok": _raw_call_grok,
    "Groq": _raw_call_groq,
}
 
 
def _is_rate_limit_error(e: Exception) -> bool:
    msg = str(e).lower()
    return any(s in msg for s in ("429", "rate limit", "toomanyrequests", "resourceexhausted", "quota"))
 
 
def _call_provider(provider: str, api_key: str, prompt: str):
    """
    Calls the given provider's raw function with ONE retry-with-backoff if
    the failure looks like a rate-limit (HTTP 429 / quota exceeded) error —
    since those are often transient (e.g. free-tier per-minute limits) and
    succeed a few seconds later.
 
    Unlike a bare try/except that silently swallows the reason, every
    failure here is logged to System Logs (Admin Panel) so you can actually
    see *why* AI screening fell back to TF-IDF — e.g. "Gemini: 429 Resource
    has been exhausted (check quota)" — instead of it just quietly not working.
    """
    raw_caller = _RAW_CALLERS.get(provider)
    if not raw_caller:
        return None
 
    last_error = None
    for attempt in range(2):  # initial attempt + 1 retry
        try:
            return raw_caller(api_key, prompt)
        except ImportError as e:
            last_error = f"'{provider}' Python package not installed: {e}"
            break  # retrying won't fix a missing package
        except Exception as e:
            last_error = str(e)
            if _is_rate_limit_error(e) and attempt == 0:
                time.sleep(AI_RATE_LIMIT_BACKOFF_SECONDS)
                continue
            break
 
    if last_error:
        db.log_action("system", "AI Screening Failed", f"{provider}: {last_error}"[:500])
    return None
 
 
def test_ai_connection(provider: str, api_key: str):
    """
    Makes one minimal, cheap call to the given provider to verify the API key
    and connectivity actually work — used by the 'Test AI Connection' button
    in Admin Panel → Branding & AI, so a 429/quota/auth problem shows up
    immediately with the real error message instead of silently falling back
    to TF-IDF on the next real application and leaving HR guessing why.
    Returns (success: bool, message: str).
    """
    if not provider or not api_key:
        return False, "Please select a provider and enter an API key first."
    if provider not in _RAW_CALLERS:
        return False, f"Unknown provider: {provider}"
 
    raw_caller = _RAW_CALLERS[provider]
    try:
        result = raw_caller(api_key, "Reply with exactly the word: OK")
        return True, f"✅ Connected successfully. Sample response: {result[:100]!r}"
    except ImportError as e:
        return False, f"'{provider}' Python package not installed: {e}"
    except Exception as e:
        error_str = str(e)
        if _is_rate_limit_error(e):
            return False, (f"❌ Rate limit / quota exceeded (HTTP 429): {error_str}\n\n"
                            f"This usually means your {provider} account has hit its free-tier or "
                            f"billing quota. Check your usage dashboard on the provider's site, "
                            f"or wait and try again later.")
        return False, f"❌ Connection failed: {error_str}"
 
 
def ai_screen_resume(provider: str, api_key: str, jd_text: str, jd_skills: list,
                      resume_text: str, resume_skills: list, candidate_name: str):
    """
    Primary AI-driven evaluation: asks the configured provider (Claude,
    OpenAI, Gemini, or Grok) to evaluate the resume against the job
    description and return a structured Match Score / Missing Skills /
    Strong Skills / Weak Areas / Recommendation. Returns None if no API key
    is configured, the provider/package is unavailable, or the call/parsing
    fails for any reason — the caller then falls back to the rule-based
    TF-IDF evaluator, so screening never hard-depends on any one AI vendor.
    """
    if not api_key or not provider:
        return None
    if provider not in _RAW_CALLERS:
        return None
 
    prompt = _build_screening_prompt(jd_text, jd_skills, resume_text, resume_skills, candidate_name)
    raw_text = _call_provider(provider, api_key, prompt)
    return _parse_ai_json_response(raw_text)
 
 
def evaluate_resume(jd_text: str, jd_skills: list, resume_text: str, resume_skills: list,
                     candidate_name: str, provider: str = None, api_key: str = None) -> dict:
    """
    Main entry point used by the Career Portal apply flow (and bulk import).
    Tries AI-based evaluation first (skills, experience, and overall fit
    judged by whichever LLM provider is configured); falls back to the
    deterministic TF-IDF + skill-overlap evaluator if no provider/key is
    configured or the AI call fails.
    """
    if provider and api_key:
        result = ai_screen_resume(provider, api_key, jd_text, jd_skills, resume_text, resume_skills, candidate_name)
        if result:
            result["screening_method"] = f"AI ({provider})"
            return result
 
    result = screen_resume(jd_text, jd_skills, resume_text, resume_skills)
    result["screening_method"] = "Rule-based (TF-IDF) - no AI configured or AI call failed"
    return result
 
 
def rank_applications(applications: list) -> list:
    """Sort applications by match_score descending — automatic ranking, no manual sorting."""
    return sorted(applications, key=lambda a: a.get("match_score", 0), reverse=True)
 
 
def check_duplicate_resume(text_hash: str, exclude_candidate_id=None):
    """
    Returns the existing candidate document if a resume with an identical
    text hash already exists in the system (duplicate resume detection).
    """
    if not text_hash:
        return None
    query = {"resume_data.text_hash": text_hash}
    candidate = db.candidates.find_one(query)
    if candidate and exclude_candidate_id and str(candidate["_id"]) == str(exclude_candidate_id):
        return None
    return candidate
 
 
def recommend_candidates_for_job(job_id: str, top_n: int = 5) -> list:
    """Candidate Recommendation: top-N ranked applications for a given job."""
    apps = db.get_applications(job_id=job_id)
    return rank_applications(apps)[:top_n]
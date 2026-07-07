"""
resume_parser.py
Extracts raw text from PDF/DOCX resumes and automatically parses:
 - Skills
 - Education
 - Experience (years, heuristic)
 - Certifications
 - LinkedIn URL
 - GitHub URL
 - Email / Phone

No manual data entry required from the candidate beyond name/email/phone.
"""

import re
import io
import hashlib

import pdfplumber
import docx  # python-docx

SKILLS_LIST = [
    "python", "java", "javascript", "typescript", "c++", "c#", "go", "rust", "sql", "html", "css",
    "react", "angular", "vue", "node.js", "django", "flask", "fastapi", "spring boot",
    "machine learning", "deep learning", "nlp", "computer vision", "data analysis",
    "data science", "data engineering", "excel", "power bi", "tableau", "aws", "azure", "gcp",
    "docker", "kubernetes", "git", "github", "ci/cd", "jenkins", "agile", "scrum",
    "project management", "communication", "leadership", "teamwork", "problem solving",
    "time management", "customer service", "sales", "marketing", "accounting", "finance",
    "hr management", "recruitment", "negotiation", "presentation skills", "analytical skills",
    "creativity", "adaptability", "critical thinking", "mongodb", "mysql", "postgresql",
    "rest api", "graphql", "software testing", "devops", "cloud computing", "cybersecurity",
    "network security", "ui/ux design", "figma", "photoshop", "illustrator", "content writing",
    "seo", "digital marketing", "social media marketing", "terraform", "linux", "bash",
]

DEGREE_KEYWORDS = [
    "bachelor", "b.sc", "bsc", "b.tech", "btech", "b.e.", "bs ", "master", "m.sc", "msc",
    "m.tech", "mtech", "mba", "phd", "ph.d", "associate degree", "high school diploma",
]

CERT_KEYWORDS = [
    "certified", "certification", "certificate", "aws certified", "pmp", "scrum master",
    "azure fundamentals", "google cloud certified", "comptia", "cisco", "ccna", "oracle certified",
]


def extract_text(uploaded_file, filename: str) -> str:
    """Extract text from a PDF or DOCX uploaded file (Streamlit UploadedFile)."""
    ext = filename.rsplit(".", 1)[-1].lower()
    text = ""
    try:
        if ext == "pdf":
            with pdfplumber.open(uploaded_file) as pdf:
                for page in pdf.pages:
                    page_text = page.extract_text()
                    if page_text:
                        text += page_text + "\n"
        elif ext == "docx":
            document = docx.Document(io.BytesIO(uploaded_file.read()))
            text = "\n".join(p.text for p in document.paragraphs)
        else:
            text = ""
    except Exception:
        text = ""
    return text.strip()


def extract_email(text: str) -> str:
    m = re.search(r"[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+", text)
    return m.group(0) if m else ""


def extract_phone(text: str) -> str:
    m = re.search(r"(\+?\d[\d\s\-()]{8,14}\d)", text)
    return m.group(0).strip() if m else ""


def extract_linkedin(text: str) -> str:
    m = re.search(r"(https?://)?(www\.)?linkedin\.com/in/[A-Za-z0-9_\-/]+", text, re.IGNORECASE)
    return m.group(0) if m else ""


def extract_github(text: str) -> str:
    m = re.search(r"(https?://)?(www\.)?github\.com/[A-Za-z0-9_\-]+", text, re.IGNORECASE)
    return m.group(0) if m else ""


def extract_skills(text: str, skills_list=None) -> list:
    if skills_list is None:
        skills_list = SKILLS_LIST
    text_lower = text.lower()
    found = [s for s in skills_list if s.lower() in text_lower]
    return sorted(set(found))


def extract_education(text: str) -> list:
    lines = text.split("\n")
    found = []
    for line in lines:
        line_lower = line.lower()
        if any(k in line_lower for k in DEGREE_KEYWORDS):
            found.append(line.strip())
    return found[:5]


def extract_certifications(text: str) -> list:
    lines = text.split("\n")
    found = []
    for line in lines:
        line_lower = line.lower()
        if any(k in line_lower for k in CERT_KEYWORDS):
            found.append(line.strip())
    return found[:5]


def extract_experience_years(text: str) -> str:
    """Heuristic: look for patterns like '5 years', '3+ years of experience'."""
    m = re.search(r"(\d{1,2})\s*\+?\s*years?", text, re.IGNORECASE)
    return f"{m.group(1)} years" if m else "Not specified"


def resume_text_hash(text: str) -> str:
    """Used for duplicate-resume detection."""
    normalized = re.sub(r"\s+", " ", text.strip().lower())
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def parse_resume(uploaded_file, filename: str) -> dict:
    """Full parse pipeline — returns a dict of structured resume data."""
    text = extract_text(uploaded_file, filename)
    return {
        "raw_text": text,
        "email": extract_email(text),
        "phone": extract_phone(text),
        "linkedin": extract_linkedin(text),
        "github": extract_github(text),
        "skills": extract_skills(text),
        "education": extract_education(text),
        "certifications": extract_certifications(text),
        "experience": extract_experience_years(text),
        "text_hash": resume_text_hash(text) if text else "",
    }

"""
config.py
Central configuration for the ATS Portal. Reads from environment variables
(or a .env file) so credentials are never hardcoded in source.
"""

import os
from dotenv import load_dotenv

load_dotenv()

MONGO_URI = os.getenv("MONGO_URI", "mongodb://localhost:27017")
DB_NAME = os.getenv("DB_NAME", "ats_portal")

ASSETS_DIR = os.path.join(os.path.dirname(__file__), "assets")
RESUME_DIR = os.path.join(ASSETS_DIR, "resumes")
LOGO_DIR = os.path.join(ASSETS_DIR, "logos")
OFFER_DIR = os.path.join(ASSETS_DIR, "offers")

for _dir in (ASSETS_DIR, RESUME_DIR, LOGO_DIR, OFFER_DIR):
    os.makedirs(_dir, exist_ok=True)

# Anthropic API key for optional AI resume screening (can also be set per-session in the UI)
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")

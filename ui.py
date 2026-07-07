"""
ui.py
Visual layer: white + purple theme, branded header with company logo,
an original animated SVG illustration, and right-aligned navigation menus
for the HR/Recruiter/Admin portals.
"""

import base64
import html
import streamlit as st

PRIMARY = "#7C3AED"
PRIMARY_DARK = "#5B21B6"
PRIMARY_LIGHT = "#EDE9FE"
ACCENT = "#A78BFA"


def esc(value) -> str:
    """Escape any value before embedding it in an unsafe_allow_html block.
    Every job title/description, company name, candidate name, etc. that
    gets interpolated into raw HTML anywhere in the app should be passed
    through this first — otherwise a job description or company name
    containing '<script>...' would execute in every HR/Admin's browser
    (stored XSS)."""
    return html.escape(str(value), quote=True)


def inject_custom_css():
    st.markdown(f"""
    <style>
        .stApp {{ background-color: #FFFFFF; }}
        h1, h2, h3 {{ color: {PRIMARY_DARK}; font-family: 'Segoe UI', sans-serif; }}
        .stButton > button {{
            background: linear-gradient(135deg, {PRIMARY} 0%, {PRIMARY_DARK} 100%);
            color: white; border: none; border-radius: 8px; padding: 0.5rem 1.2rem;
            font-weight: 600; transition: all 0.2s ease-in-out;
        }}
        .stButton > button:hover {{
            transform: translateY(-1px); box-shadow: 0 4px 14px rgba(124, 58, 237, 0.35);
        }}
        .hr-card {{
            background-color: {PRIMARY_LIGHT}; border-radius: 14px; padding: 1.2rem 1.4rem;
            margin-bottom: 1rem; border: 1px solid #E9D5FF;
        }}
        .job-card {{
            background-color: #FFFFFF; border: 1px solid #E9D5FF; border-radius: 14px;
            padding: 1.1rem 1.3rem; margin-bottom: 1rem; box-shadow: 0 2px 8px rgba(124,58,237,0.06);
        }}
        .hr-header {{
            display: flex; align-items: center; gap: 14px; padding: 0.6rem 0 1.2rem 0;
            border-bottom: 2px solid {PRIMARY_LIGHT}; margin-bottom: 1.2rem;
        }}
        .hr-header img {{ height: 46px; border-radius: 8px; }}
        .hr-header .company-name {{ font-size: 1.4rem; font-weight: 700; color: {PRIMARY_DARK}; }}
        .hr-badge {{
            display: inline-block; background: {PRIMARY_LIGHT}; color: {PRIMARY_DARK};
            padding: 2px 10px; border-radius: 999px; font-size: 0.75rem; font-weight: 600;
        }}
        .nav-title {{
            font-size: 0.8rem; text-transform: uppercase; letter-spacing: 1px;
            color: #6B7280; margin-bottom: 0.4rem;
        }}
        @keyframes floatY {{ 0% {{transform:translateY(0px);}} 50% {{transform:translateY(-12px);}} 100% {{transform:translateY(0px);}} }}
        .float-illustration {{ animation: floatY 3.5s ease-in-out infinite; }}
        @keyframes pulseDot {{ 0% {{opacity:0.3;}} 50% {{opacity:1;}} 100% {{opacity:0.3;}} }}
        .pulse-dot {{ animation: pulseDot 1.8s ease-in-out infinite; }}
        div[data-testid="stMetric"] {{
            background-color: {PRIMARY_LIGHT}; border-radius: 12px; padding: 0.8rem; border: 1px solid #E9D5FF;
        }}
        .status-pill {{
            display:inline-block; padding: 3px 10px; border-radius: 999px; font-size: 0.75rem;
            font-weight: 600; background: {PRIMARY_LIGHT}; color:{PRIMARY_DARK};
        }}
    </style>
    """, unsafe_allow_html=True)


def render_header(company_name: str, logo_bytes: bytes = None):
    logo_html = ""
    if logo_bytes:
        b64 = base64.b64encode(logo_bytes).decode()
        logo_html = f'<img src="data:image/jpeg;base64,{b64}" />'
    else:
        logo_html = (
            f'<div style="height:46px;width:46px;border-radius:8px;'
            f'background:linear-gradient(135deg,{PRIMARY},{PRIMARY_DARK});'
            f'display:flex;align-items:center;justify-content:center;color:white;font-weight:700;">HR</div>'
        )
    st.markdown(f"""
        <div class="hr-header">
            {logo_html}
            <div>
                <div class="company-name">{esc(company_name)}</div>
                <span class="hr-badge">Applicant Tracking System</span>
            </div>
        </div>
    """, unsafe_allow_html=True)


def login_illustration_svg() -> str:
    """Original SVG illustration — no copyrighted/stock imagery."""
    return f"""
    <div class="float-illustration" style="text-align:center;">
    <svg width="320" height="260" viewBox="0 0 320 260" xmlns="http://www.w3.org/2000/svg">
        <defs>
            <linearGradient id="g1" x1="0%" y1="0%" x2="100%" y2="100%">
                <stop offset="0%" stop-color="{ACCENT}"/><stop offset="100%" stop-color="{PRIMARY_DARK}"/>
            </linearGradient>
        </defs>
        <ellipse cx="160" cy="235" rx="120" ry="14" fill="{PRIMARY_LIGHT}"/>
        <rect x="90" y="120" width="140" height="90" rx="10" fill="url(#g1)"/>
        <rect x="104" y="134" width="112" height="62" rx="4" fill="#FFFFFF"/>
        <rect x="114" y="144" width="40" height="8" rx="2" fill="{PRIMARY_LIGHT}"/>
        <rect x="114" y="158" width="70" height="6" rx="2" fill="#E5E7EB"/>
        <rect x="114" y="170" width="55" height="6" rx="2" fill="#E5E7EB"/>
        <circle cx="190" cy="150" r="10" fill="{ACCENT}" class="pulse-dot"/>
        <g><circle cx="60" cy="90" r="16" fill="{PRIMARY_DARK}"/><rect x="42" y="108" width="36" height="46" rx="14" fill="{ACCENT}"/></g>
        <g><circle cx="260" cy="86" r="16" fill="{PRIMARY}"/><rect x="242" y="104" width="36" height="46" rx="14" fill="{PRIMARY_DARK}"/></g>
        <g><circle cx="160" cy="60" r="18" fill="{ACCENT}"/><rect x="140" y="80" width="40" height="50" rx="15" fill="{PRIMARY}"/></g>
        <circle cx="40" cy="50" r="10" fill="{PRIMARY_LIGHT}" stroke="{PRIMARY}" stroke-width="2"/>
        <text x="40" y="55" font-size="12" text-anchor="middle" fill="{PRIMARY_DARK}">check</text>
        <circle cx="285" cy="40" r="10" fill="{PRIMARY_LIGHT}" stroke="{PRIMARY}" stroke-width="2"/>
        <text x="285" y="45" font-size="12" text-anchor="middle" fill="{PRIMARY_DARK}">check</text>
    </svg>
    <div style="color:{PRIMARY_DARK};font-weight:600;margin-top:6px;">Smarter hiring, powered by your team + AI</div>
    </div>
    """


HR_NAV_ITEMS = [
    ("dashboard", "Dashboard"),
    ("jobs", "Job Management"),
    ("applications", "Candidate Pipeline"),
    ("profiles", "Candidate Profiles"),
    ("interviews", "Interview Scheduler"),
    ("onboarding", "Onboarding / Payroll"),
    ("emails", "Email Templates"),
    ("search", "Search & Filters"),
    ("notifications", "Notifications"),
]

ADMIN_NAV_ITEMS = HR_NAV_ITEMS + [
    ("admin", "Admin Panel"),
]


def render_right_nav(active_page: str, items) -> str:
    st.markdown('<div class="nav-title">Navigate</div>', unsafe_allow_html=True)
    selected = active_page
    for key, label in items:
        is_active = key == active_page
        if st.button(label, key=f"nav_{key}", width="stretch",
                     type="primary" if is_active else "secondary"):
            selected = key
    return selected


def pagination_controls(total_items: int, page_size: int, key: str) -> int:
    """Renders Prev / page-indicator / Next controls and returns the current
    1-indexed page number. Keeps large candidate/job lists fast and
    responsive instead of rendering thousands of rows at once."""
    total_pages = max(1, -(-total_items // page_size))  # ceil division
    page_key = f"page_{key}"
    if page_key not in st.session_state:
        st.session_state[page_key] = 1
    st.session_state[page_key] = min(st.session_state[page_key], total_pages)

    c1, c2, c3 = st.columns([1, 2, 1])
    with c1:
        if st.button("⬅ Prev", key=f"{key}_prev", disabled=st.session_state[page_key] <= 1):
            st.session_state[page_key] -= 1
            st.rerun()
    with c2:
        st.markdown(
            f"<div style='text-align:center;padding-top:6px;'>Page {st.session_state[page_key]} "
            f"of {total_pages} &nbsp;({total_items} total)</div>",
            unsafe_allow_html=True,
        )
    with c3:
        if st.button("Next ➡", key=f"{key}_next", disabled=st.session_state[page_key] >= total_pages):
            st.session_state[page_key] += 1
            st.rerun()
    return st.session_state[page_key]

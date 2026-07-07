"""
admin_pages.py
Admin Panel: manage users (HR/Recruiters), manage jobs, manage candidates,
analytics, and system logs.
"""

import pandas as pd
import streamlit as st
import plotly.express as px

import db
import auth
import hr_pages
import ui


def admin_panel_page():
    # Defense-in-depth: even though the nav button is hidden for non-Admins,
    # explicitly refuse to render this page's contents unless the logged-in
    # user's role is actually Admin.
    if st.session_state.user.get("role") != "Admin":
        st.error("Access denied. This page is restricted to Admin accounts.")
        return

    st.subheader("Admin Panel")
    tabs = st.tabs(["Manage Users", "Manage Jobs", "Manage Candidates", "Analytics", "System Logs", "Branding & AI"])

    with tabs[0]:
        st.markdown("#### Create HR / Recruiter / Admin Account")
        with st.form("create_user_form"):
            c1, c2, c3 = st.columns(3)
            username = c1.text_input("Username")
            password = c2.text_input("Password", type="password")
            role = c3.selectbox("Role", ["HR", "Recruiter", "Admin"])
            department = st.text_input("Department (optional)")
            if st.form_submit_button("Create Account"):
                success, msg = auth.create_user(username, password, role, department)
                st.success(msg) if success else st.error(msg)

        st.markdown("#### All Staff Accounts")
        users = db.get_all_users()
        df = pd.DataFrame([{
            "Username": u["username"], "Role": u["role"],
            "Department": u.get("department", ""), "Active": u.get("active", True),
        } for u in users])
        st.dataframe(df, hide_index=True, width="stretch")

    with tabs[1]:
        st.markdown("#### All Jobs")
        jobs = db.get_jobs()
        if jobs:
            df = pd.DataFrame([{
                "Title": j["title"], "Department": j.get("department", ""),
                "Location": j.get("location", ""), "Status": j.get("status", "Open"),
                "Applications": len(db.get_applications(job_id=str(j["_id"]))),
                "Posted By": j.get("created_by", ""),
            } for j in jobs])
            st.dataframe(df, hide_index=True, width="stretch")
        else:
            st.info("No jobs posted yet.")

    with tabs[2]:
        st.markdown("#### All Candidates")
        total_candidates = db.count_candidates()
        if total_candidates:
            PAGE_SIZE = 25
            page = ui.pagination_controls(total_candidates, PAGE_SIZE, key="admin_candidates")
            candidates = db.get_candidates_paginated(page=page, page_size=PAGE_SIZE)
            df = pd.DataFrame([{
                "Name": c["name"], "Email": c["email"], "Phone": c.get("phone", ""),
                "Skills": ", ".join(c.get("resume_data", {}).get("skills", [])),
                "Applications": len(db.get_applications_for_candidate(str(c["_id"]))),
            } for c in candidates])
            st.dataframe(df, hide_index=True, width="stretch")
        else:
            st.info("No candidates yet.")

    with tabs[3]:
        st.markdown("#### Company-wide Analytics")
        apps = list(db.applications.find())
        if apps:
            df = pd.DataFrame(apps)
            fig = px.histogram(df, x="match_score", nbins=10, color_discrete_sequence=["#7C3AED"],
                               title="Match Score Distribution (All Applications)")
            st.plotly_chart(fig, width="stretch")
            status_df = df["status"].value_counts().reset_index()
            status_df.columns = ["Status", "Count"]
            fig2 = px.pie(status_df, names="Status", values="Count", hole=0.4,
                          title="Overall Pipeline Status", color_discrete_sequence=px.colors.sequential.Purples_r)
            st.plotly_chart(fig2, width="stretch")
        else:
            st.info("No application data yet.")

    with tabs[4]:
        st.markdown("#### System Logs")
        logs = db.get_system_logs()
        if logs:
            df = pd.DataFrame([{
                "User": l["username"], "Action": l["action"],
                "Details": l.get("details", ""), "Timestamp": l["timestamp"],
            } for l in logs])
            st.dataframe(df, hide_index=True, width="stretch")
        else:
            st.info("No system logs yet.")

    with tabs[5]:
        hr_pages.settings_page()

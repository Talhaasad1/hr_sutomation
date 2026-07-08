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
            c4, c5 = st.columns(2)
            department = c4.text_input("Department (optional)")
            email = c5.text_input("Email (optional — enables self-service 'Forgot Password')")
            if st.form_submit_button("Create Account"):
                success, msg = auth.create_user(username, password, role, department, email)
                st.success(msg + " They'll be asked to set their own password on first login.") if success else st.error(msg)

        st.markdown("#### All Staff Accounts")
        users = db.get_all_users()
        df = pd.DataFrame([{
            "Username": u["username"], "Role": u["role"], "Department": u.get("department", ""),
            "Email": u.get("email", ""), "Active": u.get("active", True),
        } for u in users])
        st.dataframe(df, hide_index=True, width="stretch")

        st.markdown("##### Reset a User's Password")
        st.caption("Zero-dependency reset: generates a temporary password shown only to you here — "
                   "share it with the user through any channel you like (WhatsApp, in person, etc.). "
                   "They'll be forced to set their own new password on next login.")
        usernames = [u["username"] for u in users]
        reset_target = st.selectbox("Select user", usernames, key="reset_pw_user")
        if st.button("🔑 Reset Password"):
            temp_password = db.admin_reset_password(reset_target)
            db.log_action(st.session_state.user["username"], "Admin Password Reset", reset_target)
            st.success(f"Temporary password for **{reset_target}**: `{temp_password}`")
            st.caption("This will only be shown once — copy it now.")

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

"""
hr_pages.py
Page functions for the HR / Recruiter portal.
"""

from datetime import datetime, date
import os
import pandas as pd
import streamlit as st
import plotly.express as px

import db
import config
import matching
import email_service
import offer_letter
import ui

ATS_STAGES = db.ATS_STAGES


@st.fragment(run_every="10s")
def notification_toast_fragment():
    """Auto-refreshing fragment: pops up a toast the moment a new application
    (or other notification) comes in — no manual refresh needed. Each
    notification is marked 'toasted' in the database so it only pops up once,
    even across browser refreshes or multiple HR users."""
    pending = list(db.notifications.find({"target": "HR", "toasted": {"$ne": True}}))
    for n in pending:
        icon = "📥" if n.get("type") == "application" else "🔔"
        st.toast(n["message"], icon=icon)
        db.notifications.update_one({"_id": n["_id"]}, {"$set": {"toasted": True}})


def _candidate_label(app):
    cand = db.get_candidate(app["candidate_id"])
    return cand["name"] if cand else "Unknown"


def dashboard_page():
    st.subheader("Dashboard")
    jobs = db.get_jobs()
    apps = db.applications.find()
    apps = list(apps)
    df = pd.DataFrame(apps)

    today_str = date.today().isoformat()
    applications_today = len([a for a in apps if a["applied_at"].date().isoformat() == today_str])

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Applications Today", applications_today)
    c2.metric("Jobs Posted", len(jobs))
    selected_count = len([a for a in apps if a["status"] == "Selected"])
    rejected_count = len([a for a in apps if a["status"] == "Rejected"])
    c3.metric("Selected Candidates", selected_count)
    c4.metric("Rejected", rejected_count)

    if not apps:
        st.info("No applications yet. Once candidates apply via the Career Portal, analytics will appear here.")
        return

    df["status"] = df["status"].astype(str)
    col1, col2 = st.columns(2)
    with col1:
        funnel_df = df["status"].value_counts().reindex(ATS_STAGES).fillna(0).reset_index()
        funnel_df.columns = ["Status", "Count"]
        fig = px.funnel(funnel_df, x="Count", y="Status", title="Hiring Funnel",
                         color_discrete_sequence=["#7C3AED"])
        st.plotly_chart(fig, width="stretch")
    with col2:
        df["date"] = df["applied_at"].apply(lambda d: d.date().isoformat())
        trend = df.groupby("date").size().reset_index(name="Applications")
        fig2 = px.line(trend, x="date", y="Applications", markers=True,
                        title="Hiring Trend (Applications Over Time)",
                        color_discrete_sequence=["#7C3AED"])
        st.plotly_chart(fig2, width="stretch")

    job_map = {str(j["_id"]): j.get("department", "N/A") for j in jobs}
    df["department"] = df["job_id"].apply(lambda jid: job_map.get(str(jid), "N/A"))
    dept_df = df.groupby("department").size().reset_index(name="Applications")
    fig3 = px.bar(dept_df, x="department", y="Applications", title="Department-wise Hiring Activity",
                  color_discrete_sequence=["#7C3AED"])
    st.plotly_chart(fig3, width="stretch")


@st.fragment(run_every="2s")
def _bulk_import_progress():
    """Auto-refreshing progress display for the active bulk import task."""
    task_id = st.session_state.get("active_bulk_task_id")
    if not task_id:
        return
    task = db.get_background_task(task_id)
    if not task:
        return

    status = task["status"]
    total = task.get("total", 0)
    progress = task.get("progress", 0)

    if status == "queued":
        st.info("⏳ Waiting for the worker process to pick this up... "
                "(make sure `python worker.py` is running)")
    elif status == "processing":
        pct = (progress / total) if total else 0
        st.progress(pct, text=f"Processing {progress}/{total} resumes...")
    elif status == "done":
        r = task.get("result", {})
        st.success(f"✅ Import complete — Created: {r.get('created',0)} | "
                   f"Duplicates flagged: {r.get('duplicates',0)} | "
                   f"Skipped: {r.get('skipped',0)} | Errors: {r.get('errors',0)}")
        if r.get("error_details"):
            with st.expander("Error details"):
                for e in r["error_details"]:
                    st.write(f"- {e}")
    elif status == "failed":
        st.error(f"Import failed: {task.get('result', {}).get('error', 'Unknown error')}")


def bulk_import_section():
    st.markdown("---")
    st.markdown("#### 📦 Bulk Resume Import (ZIP)")
    st.caption("Upload a .zip of existing PDF/DOCX resumes to process them all against a job at once. "
               "This runs in the background (via `worker.py`), so the portal stays responsive while it works.")

    jobs = db.get_jobs()
    if not jobs:
        st.info("Create a job first before bulk-importing resumes.")
        return

    job_options = {j["title"]: str(j["_id"]) for j in jobs}
    job_choice = st.selectbox("Import resumes for job", list(job_options.keys()), key="bulk_job_choice")
    zip_file = st.file_uploader("Upload ZIP of resumes", type=["zip"], key="bulk_zip_upload")

    if zip_file and st.button("Start Bulk Import", type="primary"):
        raw = zip_file.getvalue()
        if raw[:2] != b"PK":
            st.error("That doesn't look like a valid ZIP file.")
        elif len(raw) > 200 * 1024 * 1024:  # 200MB cap on the whole archive
            st.error("ZIP file is too large (max 200 MB).")
        else:
            zip_path = os.path.join(config.RESUME_DIR, f"bulk_upload_{int(datetime.now().timestamp())}.zip")
            with open(zip_path, "wb") as f:
                f.write(raw)
            task_id = db.create_background_task("bulk_resume_import", {
                "job_id": job_options[job_choice], "zip_path": zip_path,
                "uploaded_by": st.session_state.user["username"],
            })
            st.session_state["active_bulk_task_id"] = task_id
            st.success("Import queued!")
            st.rerun()

    _bulk_import_progress()


def jobs_page():
    st.subheader("Job Management")
    db.auto_close_expired_jobs()
    depts = db.get_department_names()

    with st.expander("Create New Job", expanded=len(db.get_jobs()) == 0):
        c1, c2 = st.columns(2)
        title = c1.text_input("Job Title")
        department = c2.selectbox("Department", depts if depts else ["General"])
        c3, c4 = st.columns(2)
        location = c3.text_input("Location")
        last_date = c4.date_input("Last Date to Apply")
        c5, c6 = st.columns(2)
        salary_min = c5.number_input("Salary Range - Min", min_value=0, step=1000)
        salary_max = c6.number_input("Salary Range - Max", min_value=0, step=1000)
        experience_required = st.text_input("Experience Required (e.g. '2-4 years')")
        skills_required = st.text_input("Skills Required (comma-separated)")
        description = st.text_area("Job Description", height=180)

        if st.button("Post Job", type="primary"):
            if not title.strip() or not description.strip():
                st.error("Job Title and Description are required.")
            else:
                job_data = {
                    "title": title.strip(), "department": department, "location": location,
                    "salary_range": f"{salary_min:,.0f} - {salary_max:,.0f}",
                    "experience_required": experience_required,
                    "skills_required": [s.strip() for s in skills_required.split(",") if s.strip()],
                    "last_date": last_date.isoformat(), "description": description.strip(),
                }
                db.create_job(job_data, st.session_state.user["username"])
                db.log_action(st.session_state.user["username"], "Created Job", title)
                st.success(f"Job '{title}' posted successfully.")
                st.rerun()

    st.markdown("---")
    st.markdown("#### All Job Postings")
    total_jobs = db.count_jobs()
    if not total_jobs:
        st.info("No jobs posted yet.")
        return

    PAGE_SIZE = 15
    page = ui.pagination_controls(total_jobs, PAGE_SIZE, key="jobs")
    jobs = db.get_jobs_paginated(page=page, page_size=PAGE_SIZE)

    for job in jobs:
        with st.container():
            st.markdown(f"""<div class="job-card">
                <b>{ui.esc(job['title'])}</b> — {ui.esc(job.get('department',''))} | {ui.esc(job.get('location',''))}<br>
                <span style="color:#6B7280;font-size:0.85rem;">
                Salary: {ui.esc(job.get('salary_range','N/A'))} | Experience: {ui.esc(job.get('experience_required','N/A'))} |
                Last Date: {ui.esc(job.get('last_date','N/A'))} | Status: {ui.esc(job.get('status','Open'))}
                </span><br>
                <span style="color:#6B7280;font-size:0.85rem;">
                Skills: {ui.esc(', '.join(job.get('skills_required', [])) or 'N/A')}</span>
                </div>""", unsafe_allow_html=True)
            c1, c2, c3 = st.columns(3)
            n_apps = len(db.get_applications(job_id=str(job["_id"])))
            c1.caption(f"📥 {n_apps} application(s)")
            new_status = "Closed" if job.get("status") == "Open" else "Open"
            if c2.button(f"Mark as {new_status}", key=f"toggle_{job['_id']}"):
                db.update_job(str(job["_id"]), {"status": new_status})
                st.rerun()
            if c3.button("Delete", key=f"del_{job['_id']}"):
                db.delete_job(str(job["_id"]))
                db.log_action(st.session_state.user["username"], "Deleted Job", job["title"])
                st.rerun()

    bulk_import_section()


def candidate_profile_view(candidate_id: str):
    cand = db.get_candidate(candidate_id)
    if not cand:
        st.warning("Candidate not found.")
        return
    resume = cand.get("resume_data", {})

    st.markdown(f"### {cand['name']}")
    st.caption(f"📧 {cand['email']} | 📱 {cand.get('phone','N/A')}")
    if resume.get("linkedin"):
        st.markdown(f"🔗 [LinkedIn]({resume['linkedin']})")
    if resume.get("github"):
        st.markdown(f"🔗 [GitHub]({resume['github']})")

    c1, c2 = st.columns(2)
    with c1:
        st.markdown("**Skills**")
        st.write(", ".join(resume.get("skills", [])) or "None detected")
        st.markdown("**Education**")
        for e in resume.get("education", []) or ["Not detected"]:
            st.write(f"- {e}")
    with c2:
        st.markdown("**Experience**")
        st.write(resume.get("experience", "Not specified"))
        st.markdown("**Certifications**")
        for cert in resume.get("certifications", []) or ["None detected"]:
            st.write(f"- {cert}")

    st.markdown("---")
    st.markdown("#### Application History")
    apps = db.get_applications_for_candidate(candidate_id)
    for app in apps:
        job = db.get_job(str(app["job_id"]))
        st.markdown(f"**{ui.esc(job['title'] if job else 'Unknown Job')}** — "
                    f"<span class='status-pill'>{ui.esc(app['status'])}</span> — "
                    f"Match Score: {app['match_score']}%", unsafe_allow_html=True)

    if apps:
        st.markdown("##### Change Status")
        app_options = {}
        for app in apps:
            job = db.get_job(str(app["job_id"]))
            app_options[f"{job['title'] if job else 'Unknown Job'} (currently: {app['status']})"] = app
        app_choice = st.selectbox("Select application to update", list(app_options.keys()), key=f"status_app_{candidate_id}")
        selected_app = app_options[app_choice]
        new_status = st.selectbox(
            "New Status", ATS_STAGES,
            index=ATS_STAGES.index(selected_app["status"]) if selected_app["status"] in ATS_STAGES else 0,
            key=f"status_select_{candidate_id}",
        )
        if st.button("Update Status", key=f"status_update_{candidate_id}"):
            db.update_application_status(str(selected_app["_id"]), new_status)
            db.log_action(st.session_state.user["username"], "Status Change (Profile)",
                          f"{cand['name']} -> {new_status}")
            st.success(f"Status updated to '{new_status}'.")
            st.rerun()

    st.markdown("#### Interview History")
    for app in apps:
        for iv in db.get_interviews(str(app["_id"])):
            st.write(f"- {iv['round_type']} on {iv['date']} at {iv['time']}")

    st.markdown("---")
    resume_path = cand.get("resume_file_path")
    if resume_path:
        try:
            with open(resume_path, "rb") as f:
                st.download_button(
                    "⬇️ Download Original CV", f,
                    file_name=cand.get("resume_filename", "resume.pdf"),
                    key=f"dl_{candidate_id}",
                )
        except FileNotFoundError:
            st.caption("Original CV file not found on disk.")
    else:
        st.caption("No original CV file stored for this candidate.")


def applications_page():
    st.subheader("Candidate Pipeline (ATS)")
    jobs = db.get_jobs()
    if not jobs:
        st.info("No jobs posted yet.")
        return

    job_options = {j["title"]: str(j["_id"]) for j in jobs}
    job_choice = st.selectbox("Select Job", list(job_options.keys()))
    job_id = job_options[job_choice]
    job = db.get_job(job_id)

    apps = db.get_applications(job_id=job_id)
    apps = matching.rank_applications(apps)  # automatic ranking, no manual sorting
    if not apps:
        st.info("No applications for this job yet.")
        return

    rows = []
    for i, app in enumerate(apps, start=1):
        cand = db.get_candidate(str(app["candidate_id"]))
        rows.append({
            "Rank": i, "app_id": str(app["_id"]), "candidate_id": str(app["candidate_id"]),
            "Name": cand["name"] if cand else "Unknown",
            "Email": cand["email"] if cand else "",
            "Phone": cand.get("phone", "") if cand else "",
            "Match Score": app["match_score"],
            "Strong Skills": ", ".join(app.get("strong_skills", [])),
            "Missing Skills": ", ".join(app.get("missing_skills", [])),
            "Recommendation": app.get("recommendation", ""),
            "Status": app["status"],
        })
    df = pd.DataFrame(rows)

    st.markdown("#### Score Filter")
    score_threshold = st.slider(
        "Score Threshold — drag to filter candidates by Match Score", 0, 100, 50,
        help="Candidates below this score are considered weak matches; at/above it, strong matches.",
    )
    view_df = df[df["Match Score"] >= score_threshold].reset_index(drop=True)
    st.caption(f"Showing {len(view_df)} of {len(df)} candidate(s) at or above {score_threshold}%.")

    c1, c2 = st.columns(2)
    with c1:
        if st.button(f"⚡ Auto-Screen 'Applied' Candidates at {score_threshold}% Threshold", type="primary"):
            promoted, rejected = 0, 0
            for _, row in df.iterrows():
                orig_app = next(a for a in apps if str(a["_id"]) == row["app_id"])
                if orig_app["status"] != "Applied":
                    continue  # only touch candidates whose current status is 'Applied'
                if row["Match Score"] >= score_threshold:
                    db.update_application_status(row["app_id"], "Shortlisted")
                    promoted += 1
                else:
                    db.update_application_status(row["app_id"], "Rejected")
                    rejected += 1
            db.log_action(st.session_state.user["username"], "Auto-Screen",
                          f"{job['title']}: {promoted} shortlisted, {rejected} rejected @ {score_threshold}%")
            st.success(f"Auto-screening complete: {promoted} candidate(s) shortlisted, "
                       f"{rejected} candidate(s) rejected. (Only 'Applied' candidates were affected.)")
            st.rerun()
    with c2:
        st.caption("This only changes candidates whose **current status is 'Applied'** — "
                   "anyone already Shortlisted, Rejected, in Interview, etc. is left untouched.")

    st.markdown("---")
    PAGE_SIZE = 25
    page = ui.pagination_controls(len(view_df), PAGE_SIZE, key=f"pipeline_{job_id}")
    page_df = view_df.iloc[(page - 1) * PAGE_SIZE: page * PAGE_SIZE].reset_index(drop=True)

    edited = st.data_editor(
        page_df, column_config={
            "app_id": None, "candidate_id": None,
            "Match Score": st.column_config.ProgressColumn("Match Score", min_value=0, max_value=100, format="%.1f%%"),
            "Status": st.column_config.SelectboxColumn("Status", options=ATS_STAGES),
        },
        disabled=["Rank", "Name", "Email", "Phone", "Match Score", "Strong Skills", "Missing Skills", "Recommendation"],
        hide_index=True, width="stretch", key="pipeline_editor",
    )

    if st.button("Save Pipeline Changes", type="primary"):
        for _, row in edited.iterrows():
            orig = df[df["app_id"] == row["app_id"]].iloc[0]
            if row["Status"] != orig["Status"]:
                db.update_application_status(row["app_id"], row["Status"])
                db.log_action(st.session_state.user["username"], "Status Change",
                              f"{row['Name']} -> {row['Status']}")
        st.success("Pipeline updated.")
        st.rerun()


def candidate_profiles_page():
    st.subheader("Candidate Profiles")
    st.caption("Browse all candidates with filters, then open a profile for full details and CV download.")

    jobs = {str(j["_id"]): j["title"] for j in db.get_jobs()}
    apps = list(db.applications.find())
    if not apps:
        st.info("No candidates have applied yet.")
        return

    rows = []
    for app in apps:
        cand = db.get_candidate(str(app["candidate_id"]))
        if not cand:
            continue
        rows.append({
            "candidate_id": str(cand["_id"]), "Name": cand["name"], "Email": cand["email"],
            "Phone": cand.get("phone", ""), "Job Applied": jobs.get(str(app["job_id"]), "Unknown"),
            "Status": app["status"], "Match Score": app["match_score"],
        })
    df = pd.DataFrame(rows)

    c1, c2, c3 = st.columns(3)
    job_filter = c1.selectbox("Job Applied", ["All"] + sorted(df["Job Applied"].unique().tolist()))
    name_filter = c2.text_input("Name contains")
    status_filter = c3.multiselect("Status", ATS_STAGES)

    filtered = df.copy()
    if job_filter != "All":
        filtered = filtered[filtered["Job Applied"] == job_filter]
    if name_filter:
        filtered = filtered[filtered["Name"].str.contains(name_filter, case=False)]
    if status_filter:
        filtered = filtered[filtered["Status"].isin(status_filter)]

    if filtered.empty:
        st.info("No candidates match the current filters.")
        return

    PAGE_SIZE = 25
    page = ui.pagination_controls(len(filtered), PAGE_SIZE, key="profiles")
    page_df = filtered.iloc[(page - 1) * PAGE_SIZE: page * PAGE_SIZE]

    st.dataframe(page_df.drop(columns=["candidate_id"]), hide_index=True, width="stretch")

    st.markdown("---")
    st.markdown("#### Open a Candidate Profile")
    options = {f"{r['Name']} — {r['Job Applied']} ({r['Status']})": r["candidate_id"]
               for _, r in page_df.iterrows()}
    choice = st.selectbox("Select candidate to view full profile", ["-- Select --"] + list(options.keys()))
    if choice != "-- Select --":
        candidate_profile_view(options[choice])


def onboarding_page():
    st.subheader("🧾 Onboarding / Payroll")
    st.caption("Once a candidate's status becomes 'Joined', create their employee record here — "
               "this is the hand-off point from recruiting to payroll/HRIS.")

    joined_apps = list(db.applications.find({"status": "Joined"}))
    pending = [a for a in joined_apps if not db.get_employee_by_application(str(a["_id"]))]

    st.markdown("#### Pending Onboarding")
    if not pending:
        st.info("No newly-joined candidates waiting for an employee record.")
    else:
        options = {}
        for a in pending:
            cand = db.get_candidate(str(a["candidate_id"]))
            job = db.get_job(str(a["job_id"]))
            options[f"{cand['name']} — {job['title']}"] = (a, cand, job)
        choice = st.selectbox("Select a joined candidate to onboard", list(options.keys()))
        app, cand, job = options[choice]

        offer = db.get_offer(str(app["_id"]))
        dept_names = db.get_department_names() or ["General"]
        with st.form("onboard_form"):
            c1, c2 = st.columns(2)
            designation = c1.text_input("Designation", value=offer.get("designation", job["title"]) if offer else job["title"])
            job_dept = job.get("department", "")
            dept_index = dept_names.index(job_dept) if job_dept in dept_names else 0
            department = c2.selectbox("Department", dept_names, index=dept_index)
            c3, c4 = st.columns(2)
            salary = c3.text_input("Salary", value=offer.get("salary", "") if offer else job.get("salary_range", ""))
            joining_date = c4.date_input("Joining Date")
            c5, c6 = st.columns(2)
            employment_type = c5.selectbox("Employment Type", ["Full-time", "Part-time", "Contract", "Internship"])
            manager = c6.text_input("Reporting Manager")
            c7, c8 = st.columns(2)
            bank_account = c7.text_input("Bank Account Number")
            tax_id = c8.text_input("CNIC / Tax ID")

            if st.form_submit_button("Create Employee Record", type="primary"):
                employee_id = db.create_employee({
                    "application_id": app["_id"], "candidate_id": cand["_id"],
                    "name": cand["name"], "email": cand["email"], "phone": cand.get("phone", ""),
                    "designation": designation, "department": department, "salary": salary,
                    "joining_date": joining_date.isoformat(), "employment_type": employment_type,
                    "manager": manager, "bank_account": bank_account, "tax_id": tax_id,
                })
                db.log_action(st.session_state.user["username"], "Onboarded Employee", cand["name"])
                st.success(f"Employee record created for {cand['name']}.")
                st.rerun()

    st.markdown("---")
    st.markdown("#### Employee Roster")
    employees = db.get_all_employees()
    if not employees:
        st.info("No employee records yet.")
        return

    PAGE_SIZE = 25
    page = ui.pagination_controls(len(employees), PAGE_SIZE, key="employees")
    page_items = employees[(page - 1) * PAGE_SIZE: page * PAGE_SIZE]

    df = pd.DataFrame([{
        "Employee ID": e["employee_id"], "Name": e["name"], "Designation": e["designation"],
        "Department": e.get("department", ""), "Salary": e.get("salary", ""),
        "Joining Date": e.get("joining_date", ""), "Employment Type": e.get("employment_type", ""),
        "Manager": e.get("manager", ""), "Status": e.get("status", "Active"),
    } for e in page_items])
    st.dataframe(df, hide_index=True, width="stretch")

    st.markdown("##### Edit Employee Record")
    emp_choice = st.selectbox("Select employee to view/edit", [e["employee_id"] for e in page_items], key="emp_edit_choice")
    emp = next(e for e in page_items if e["employee_id"] == emp_choice)
    dept_names = db.get_department_names() or ["General"]

    with st.form(f"edit_emp_{emp['employee_id']}"):
        st.caption(f"Employee ID: **{emp['employee_id']}** (cannot be changed)")
        c1, c2 = st.columns(2)
        name = c1.text_input("Name", value=emp["name"])
        email = c2.text_input("Email", value=emp["email"])
        c3, c4 = st.columns(2)
        phone = c3.text_input("Phone", value=emp.get("phone", ""))
        designation = c4.text_input("Designation", value=emp["designation"])
        c5, c6 = st.columns(2)
        emp_dept = emp.get("department", "")
        dept_index = dept_names.index(emp_dept) if emp_dept in dept_names else 0
        department = c5.selectbox("Department", dept_names, index=dept_index, key=f"dept_{emp['employee_id']}")
        salary = c6.text_input("Salary", value=emp.get("salary", ""))
        c7, c8 = st.columns(2)
        employment_type = c7.selectbox(
            "Employment Type", ["Full-time", "Part-time", "Contract", "Internship"],
            index=["Full-time", "Part-time", "Contract", "Internship"].index(emp.get("employment_type", "Full-time"))
            if emp.get("employment_type") in ["Full-time", "Part-time", "Contract", "Internship"] else 0,
        )
        manager = c8.text_input("Reporting Manager", value=emp.get("manager", ""))
        c9, c10 = st.columns(2)
        bank_account = c9.text_input("Bank Account Number", value=emp.get("bank_account", ""))
        tax_id = c10.text_input("CNIC / Tax ID", value=emp.get("tax_id", ""))
        status = st.selectbox(
            "Employment Status", db.EMPLOYEE_STATUS_OPTIONS,
            index=db.EMPLOYEE_STATUS_OPTIONS.index(emp.get("status", "Active"))
            if emp.get("status") in db.EMPLOYEE_STATUS_OPTIONS else 0,
        )

        if st.form_submit_button("Save Changes", type="primary"):
            db.update_employee(str(emp["_id"]), {
                "name": name, "email": email, "phone": phone, "designation": designation,
                "department": department, "salary": salary, "employment_type": employment_type,
                "manager": manager, "bank_account": bank_account, "tax_id": tax_id, "status": status,
            })
            db.log_action(st.session_state.user["username"], "Updated Employee Record",
                          f"{emp['employee_id']} ({name})")
            st.success(f"Employee record for {name} updated.")
            st.rerun()


def interviews_page():
    st.subheader("Interview Scheduler")
    jobs = {str(j["_id"]): j["title"] for j in db.get_jobs()}
    apps = db.applications.find({"status": {"$in": ["Shortlisted", "Screening", "Interview Scheduled"]}})
    apps = list(apps)

    if not apps:
        st.info("No shortlisted candidates ready for interview scheduling yet.")
    else:
        options = {}
        for app in apps:
            cand = db.get_candidate(str(app["candidate_id"]))
            label = f"{cand['name']} - {jobs.get(str(app['job_id']), '')}"
            options[label] = app

        choice = st.selectbox("Select Candidate", list(options.keys()))
        app = options[choice]
        cand = db.get_candidate(str(app["candidate_id"]))
        job = db.get_job(str(app["job_id"]))

        c1, c2, c3 = st.columns(3)
        interview_date = c1.date_input("Date")
        interview_time = c2.time_input("Time")
        round_type = c3.selectbox("Round", ["Technical Round", "HR Round"])

        with st.expander("SMTP Settings (for sending invite email)"):
            s1, s2 = st.columns(2)
            smtp_server = s1.text_input("SMTP Server", value=db.get_setting_value("smtp_server", "smtp.gmail.com"))
            smtp_port = s2.number_input("SMTP Port", value=int(db.get_setting_value("smtp_port", "587") or 587))
            sender_email = s1.text_input("Sender Email", value=db.get_setting_value("sender_email", ""))
            sender_password = s2.text_input("Sender Password / App Password", type="password",
                                            value=db.get_setting_value("sender_password", ""))

        if st.button("Schedule Interview & Notify Candidate", type="primary"):
            date_str = interview_date.isoformat()
            time_str = interview_time.strftime("%H:%M")
            db.schedule_interview(str(app["_id"]), date_str, time_str, round_type,
                                  st.session_state.user["username"])
            db.update_application_status(str(app["_id"]), "Interview Scheduled")

            ics_bytes = email_service.build_ics_invite(cand["name"], job["title"], date_str, time_str)
            context = {
                "candidate_name": cand["name"], "candidate_email": cand["email"],
                "job_title": job["title"], "interview_date": date_str, "interview_time": time_str,
            }
            if sender_email and sender_password:
                success, msg = email_service.send_stage_email(
                    {"smtp_server": smtp_server, "smtp_port": int(smtp_port),
                     "sender_email": sender_email, "sender_password": sender_password},
                    str(app["_id"]), "Interview Scheduled", context,
                    attachment_bytes=ics_bytes, attachment_name="interview_invite.ics",
                )
                st.success("Interview scheduled and email + calendar invite sent.") if success else st.warning(f"Interview scheduled, but email failed: {msg}")
            else:
                st.success("Interview scheduled. (Add SMTP credentials above to auto-send the invite email.)")
            st.rerun()

        st.markdown("---")
        st.markdown("#### Today's Interviews")
        todays = db.get_todays_interviews(date.today().isoformat())
        for iv in todays:
            app2 = db.get_application(str(iv["application_id"]))
            cand2 = db.get_candidate(str(app2["candidate_id"])) if app2 else None
            st.write(f"- {cand2['name'] if cand2 else 'Unknown'} at {iv['time']} ({iv['round_type']})")

    st.markdown("---")
    st.markdown("### 📬 Status-based Email Queue")
    st.caption("Candidates are automatically classified by their current pipeline status, so you always "
               "know exactly which email needs to go out to whom.")

    templates = {t["stage"]: t for t in db.get_all_email_templates()}
    # These stages have dedicated flows elsewhere (Application Received at apply-time,
    # Offer Sent from the offer-letter generator) — everything else is queued here.
    queueable_stages = [s for s in ATS_STAGES if s in templates and s not in ("Applied", "Offer Sent")]

    status_choice = st.selectbox("Classify by Status", queueable_stages)
    pending_apps = db.get_applications(status=status_choice)
    pending_apps = [a for a in pending_apps if not db.has_email_been_sent(str(a["_id"]), status_choice)]

    if not pending_apps:
        st.info(f"No pending '{status_choice}' emails — everyone in this stage has already been emailed.")
    else:
        st.write(f"**{len(pending_apps)} candidate(s)** in '{status_choice}' are waiting for their email:")
        labels = []
        app_by_label = {}
        for a in pending_apps:
            c = db.get_candidate(str(a["candidate_id"]))
            j = db.get_job(str(a["job_id"]))
            label = f"{c['name'] if c else 'Unknown'} — {j['title'] if j else ''}"
            labels.append(label)
            app_by_label[label] = a

        selected_labels = st.multiselect("Select candidates to email", labels, default=labels, key="queue_select")

        with st.expander("SMTP Settings (defaults come from Admin's saved settings)"):
            q1, q2 = st.columns(2)
            q_smtp_server = q1.text_input("SMTP Server", value=db.get_setting_value("smtp_server", "smtp.gmail.com"), key="q_smtp_server")
            q_smtp_port = q2.number_input("SMTP Port", value=int(db.get_setting_value("smtp_port", "587") or 587), key="q_smtp_port")
            q_sender_email = q1.text_input("Sender Email", value=db.get_setting_value("sender_email", ""), key="q_sender_email")
            q_sender_password = q2.text_input("Sender Password", type="password", value=db.get_setting_value("sender_password", ""), key="q_sender_password")

        if st.button(f"📤 Send '{status_choice}' Email to Selected", type="primary"):
            if not q_sender_email or not q_sender_password:
                st.error("Please provide sender email and password.")
            else:
                sent, failed = 0, 0
                for label in selected_labels:
                    a = app_by_label[label]
                    c = db.get_candidate(str(a["candidate_id"]))
                    j = db.get_job(str(a["job_id"]))
                    context = {"candidate_name": c["name"], "candidate_email": c["email"], "job_title": j["title"]}
                    success, msg = email_service.send_stage_email(
                        {"smtp_server": q_smtp_server, "smtp_port": int(q_smtp_port),
                         "sender_email": q_sender_email, "sender_password": q_sender_password},
                        str(a["_id"]), status_choice, context,
                    )
                    sent += 1 if success else 0
                    failed += 0 if success else 1
                st.success(f"Sent {sent} email(s)." + (f" {failed} failed." if failed else ""))
                st.rerun()

    st.markdown("---")
    st.markdown("### 🎉 Offer & Joining Actions")
    st.caption("Generate + send the offer letter (auto-moves status to 'Offer Sent'), and later confirm "
               "joining (auto-moves status to 'Joined') — each with a confirmation once the email is sent.")

    with st.expander("SMTP Settings (defaults come from Admin's saved settings)", expanded=False):
        o1, o2 = st.columns(2)
        o_smtp_server = o1.text_input("SMTP Server", value=db.get_setting_value("smtp_server", "smtp.gmail.com"), key="offer_smtp_server")
        o_smtp_port = o2.number_input("SMTP Port", value=int(db.get_setting_value("smtp_port", "587") or 587), key="offer_smtp_port")
        o_sender_email = o1.text_input("Sender Email", value=db.get_setting_value("sender_email", ""), key="offer_sender_email")
        o_sender_password = o2.text_input("Sender Password", type="password", value=db.get_setting_value("sender_password", ""), key="offer_sender_password")

    tab_offer, tab_joined = st.tabs(["📄 Send Offer Letter", "✅ Confirm Joining"])

    with tab_offer:
        offer_candidates = list(db.applications.find({"status": {"$in": ["Selected", "HR Round"]}}))
        if not offer_candidates:
            st.info("No candidates in 'Selected' or 'HR Round' status yet.")
        else:
            options = {}
            for a in offer_candidates:
                c = db.get_candidate(str(a["candidate_id"]))
                j = db.get_job(str(a["job_id"]))
                options[f"{c['name']} — {j['title']} ({a['status']})"] = (a, c, j)
            choice = st.selectbox("Select candidate", list(options.keys()), key="offer_choice")
            app, cand, job = options[choice]

            c1, c2, c3 = st.columns(3)
            designation = c1.text_input("Designation", value=job["title"], key="offer_designation")
            salary = c2.text_input("Salary", value=job.get("salary_range", ""), key="offer_salary")
            joining_date = c3.date_input("Joining Date", key="offer_joining_date")

            if st.button("📤 Generate Offer Letter & Send Email", type="primary", key="send_offer_btn"):
                if not o_sender_email or not o_sender_password:
                    st.error("Please provide sender email and password above.")
                else:
                    company_name = db.get_setting_value("company_name", "Your Company")
                    pdf_path = offer_letter.generate_offer_letter(
                        company_name, cand["name"], designation, salary,
                        joining_date.isoformat(), job["title"],
                    )
                    with open(pdf_path, "rb") as f:
                        pdf_bytes = f.read()

                    context = {"candidate_name": cand["name"], "candidate_email": cand["email"], "job_title": job["title"]}
                    success, msg = email_service.send_stage_email(
                        {"smtp_server": o_smtp_server, "smtp_port": int(o_smtp_port),
                         "sender_email": o_sender_email, "sender_password": o_sender_password},
                        str(app["_id"]), "Offer Sent", context,
                        attachment_bytes=pdf_bytes, attachment_name="offer_letter.pdf",
                    )
                    if success:
                        db.create_offer(str(app["_id"]), salary, designation, joining_date.isoformat(), pdf_path)
                        db.update_application_status(str(app["_id"]), "Offer Sent")
                        db.log_action(st.session_state.user["username"], "Sent Offer Letter", cand["name"])
                        st.success(f"✅ Offer letter emailed to {cand['name']} — status automatically updated to 'Offer Sent'.")
                        st.balloons()
                    else:
                        st.error(f"Offer letter was generated but the email failed to send: {msg}")

    with tab_joined:
        offer_sent_candidates = list(db.applications.find({"status": "Offer Sent"}))
        if not offer_sent_candidates:
            st.info("No candidates in 'Offer Sent' status yet.")
        else:
            options = {}
            for a in offer_sent_candidates:
                c = db.get_candidate(str(a["candidate_id"]))
                j = db.get_job(str(a["job_id"]))
                options[f"{c['name']} — {j['title']}"] = (a, c, j)
            choice = st.selectbox("Select candidate", list(options.keys()), key="joined_choice")
            app, cand, job = options[choice]

            if st.button("✅ Send Joining Confirmation Email", type="primary", key="send_joined_btn"):
                if not o_sender_email or not o_sender_password:
                    st.error("Please provide sender email and password above.")
                else:
                    context = {"candidate_name": cand["name"], "candidate_email": cand["email"], "job_title": job["title"]}
                    success, msg = email_service.send_stage_email(
                        {"smtp_server": o_smtp_server, "smtp_port": int(o_smtp_port),
                         "sender_email": o_sender_email, "sender_password": o_sender_password},
                        str(app["_id"]), "Joined", context,
                    )
                    if success:
                        db.update_application_status(str(app["_id"]), "Joined")
                        db.log_action(st.session_state.user["username"], "Confirmed Joining", cand["name"])
                        st.success(f"✅ Joining confirmation emailed to {cand['name']} — status automatically "
                                   f"updated to 'Joined'. Head to Onboarding / Payroll to create their employee record.")
                        st.balloons()
                    else:
                        st.error(f"Email failed to send: {msg}")


def emails_page():
    st.subheader("Email Templates (Editable)")
    st.caption("These templates are used automatically when a candidate's status changes. Edit freely.")
    templates = db.get_all_email_templates()
    for tpl in templates:
        with st.expander(tpl["stage"]):
            subject = st.text_input("Subject", value=tpl["subject"], key=f"subj_{tpl['stage']}")
            body = st.text_area("Body", value=tpl["body"], height=150, key=f"body_{tpl['stage']}")
            if st.button("Save Template", key=f"save_{tpl['stage']}"):
                db.update_email_template(tpl["stage"], subject, body)
                st.success("Template updated.")

    st.markdown("---")
    st.markdown("#### Email Log")
    log = db.get_email_log()
    if log:
        df = pd.DataFrame(log)[["stage", "subject", "status", "sent_at"]]
        st.dataframe(df, hide_index=True, width="stretch")
    else:
        st.info("No emails sent yet.")

    st.info("💡 To generate and send an Offer Letter or a Joining confirmation email, "
            "go to **Interview Scheduler → 🎉 Offer & Joining Actions**.")


def search_page():
    st.subheader("Search & Filters")
    candidates = db.get_all_candidates()
    apps = list(db.applications.find())
    jobs = {str(j["_id"]): j for j in db.get_jobs()}

    c1, c2, c3 = st.columns(3)
    name_kw = c1.text_input("Name contains")
    skill_kw = c2.text_input("Skill contains")
    location_kw = c3.text_input("Job Location contains")
    c4, c5, c6 = st.columns(3)
    min_score = c4.slider("Min Match Score", 0, 100, 0)
    status_filter = c5.multiselect("Status", ATS_STAGES)
    education_kw = c6.text_input("Education contains")

    rows = []
    for app in apps:
        cand = db.get_candidate(str(app["candidate_id"]))
        job = jobs.get(str(app["job_id"]))
        if not cand or not job:
            continue
        resume = cand.get("resume_data", {})
        rows.append({
            "Name": cand["name"], "Email": cand["email"], "Job": job["title"],
            "Location": job.get("location", ""), "Skills": ", ".join(resume.get("skills", [])),
            "Education": "; ".join(resume.get("education", [])),
            "Experience": resume.get("experience", ""), "Match Score": app["match_score"],
            "Status": app["status"],
        })
    df = pd.DataFrame(rows)
    if df.empty:
        st.info("No applications to search yet.")
        return

    filtered = df[df["Match Score"] >= min_score]
    if name_kw:
        filtered = filtered[filtered["Name"].str.contains(name_kw, case=False)]
    if skill_kw:
        filtered = filtered[filtered["Skills"].str.contains(skill_kw, case=False)]
    if location_kw:
        filtered = filtered[filtered["Location"].str.contains(location_kw, case=False)]
    if education_kw:
        filtered = filtered[filtered["Education"].str.contains(education_kw, case=False)]
    if status_filter:
        filtered = filtered[filtered["Status"].isin(status_filter)]

    if filtered.empty:
        st.info("No results match these filters.")
        return

    PAGE_SIZE = 25
    page = ui.pagination_controls(len(filtered), PAGE_SIZE, key="search")
    page_df = filtered.iloc[(page - 1) * PAGE_SIZE: page * PAGE_SIZE]
    st.dataframe(page_df, hide_index=True, width="stretch")


def notifications_page():
    st.subheader("Notifications")
    notifs = db.get_notifications("HR")
    if st.button("Mark all as read"):
        db.mark_notifications_read("HR")
        st.rerun()
    if not notifs:
        st.info("No notifications.")
        return
    for n in notifs:
        icon = "🆕" if not n["is_read"] else "✅"
        st.write(f"{icon} {n['message']}  —  _{n['created_at'].strftime('%Y-%m-%d %H:%M')}_")


def settings_page():
    st.subheader("Branding & AI Settings")
    st.markdown("#### Company Branding")
    company_name = st.text_input("Company Name", value=db.get_setting_value("company_name"))
    logo_file = st.file_uploader("Upload Company Logo (JPG/PNG)", type=["jpg", "jpeg", "png"])
    if st.button("Save Branding"):
        db.set_setting_value("company_name", company_name)
        if logo_file is not None:
            import config, os
            logo_bytes = logo_file.read()
            path = os.path.join(config.LOGO_DIR, logo_file.name)
            with open(path, "wb") as f:
                f.write(logo_bytes)
            db.set_setting_value("logo_path", path)
            st.session_state.logo_bytes = logo_bytes
        st.success("Branding updated.")
        st.rerun()

    st.markdown("---")
    st.markdown("#### SMTP Settings (used for all automatic emails)")
    st.caption("Saved to the database so 'Application Received' and other automatic emails can be sent "
               "without HR needing to be logged in at that moment.")
    s1, s2 = st.columns(2)
    smtp_server = s1.text_input("SMTP Server", value=db.get_setting_value("smtp_server", "smtp.gmail.com"))
    smtp_port = s2.number_input("SMTP Port", value=int(db.get_setting_value("smtp_port", "587") or 587))
    sender_email = s1.text_input("Sender Email", value=db.get_setting_value("sender_email", ""))
    sender_password = s2.text_input("Sender Password / App Password", type="password",
                                    value=db.get_setting_value("sender_password", ""))
    if st.button("Save SMTP Settings"):
        db.set_setting_value("smtp_server", smtp_server)
        db.set_setting_value("smtp_port", str(smtp_port))
        db.set_setting_value("sender_email", sender_email)
        db.set_setting_value("sender_password", sender_password)
        st.success("SMTP settings saved.")

    st.markdown("---")
    st.markdown("#### AI-Powered Resume Screening")
    st.caption("Powers the AI evaluation used on every application (match score, skills, experience). "
               "Saved to the database (Admin-only) so it works for every candidate who applies, not just "
               "during your current session. If the call fails or no key is set, the system automatically "
               "falls back to a rule-based TF-IDF evaluator — there's always a score.")

    current_provider = db.get_setting_value("ai_provider", "Claude")
    provider = st.selectbox(
        "AI Provider", matching.AI_PROVIDERS,
        index=matching.AI_PROVIDERS.index(current_provider) if current_provider in matching.AI_PROVIDERS else 0,
    )
    provider_key_setting = {
        "Claude": "anthropic_api_key", "OpenAI": "openai_api_key",
        "Gemini": "gemini_api_key", "Grok": "grok_api_key",
    }
    key_labels = {
        "Claude": "Anthropic API Key", "OpenAI": "OpenAI API Key",
        "Gemini": "Google AI (Gemini) API Key", "Grok": "xAI (Grok) API Key",
    }
    setting_key = provider_key_setting[provider]
    api_key = st.text_input(
        key_labels[provider], value=db.get_setting_value(setting_key, ""), type="password",
        key=f"ai_key_{provider}",
    )
    if st.button("Save AI Settings", type="primary"):
        db.set_setting_value("ai_provider", provider)
        db.set_setting_value(setting_key, api_key)
        st.success(f"AI settings saved — using {provider} for resume screening.")

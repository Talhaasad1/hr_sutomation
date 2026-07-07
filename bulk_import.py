"""
bulk_import.py
Processes a bulk resume ZIP import task: extracts each resume, parses it,
runs the same AI/TF-IDF screening used on the Career Portal, and creates a
candidate + application record for each one.

This is executed by worker.py (the standalone background-task processor),
NOT by the Streamlit app process itself — so importing hundreds of old
resumes never blocks or freezes the HR portal's UI.
"""

import io
import os
import zipfile
from datetime import datetime

import db
import config
import resume_parser
import matching

ALLOWED_EXTENSIONS = {"pdf", "docx"}


def process_bulk_import_task(task: dict):
    task_id = str(task["_id"])
    payload = task["payload"]
    job_id = payload["job_id"]
    zip_path = payload["zip_path"]
    uploaded_by = payload.get("uploaded_by", "system")

    job = db.get_job(job_id)
    if not job:
        db.update_background_task(task_id, status="failed", result={"error": "Job not found"})
        return

    jd_text = job["description"]
    jd_skills = job.get("skills_required", [])
    ai_provider, ai_key = db.get_ai_config()

    created, skipped, duplicates, errors = 0, 0, 0, 0
    error_details = []

    try:
        with zipfile.ZipFile(zip_path, "r") as z:
            names = [n for n in z.namelist() if not n.endswith("/")
                     and "." in n and n.rsplit(".", 1)[-1].lower() in ALLOWED_EXTENSIONS
                     and not os.path.basename(n).startswith(".")]
            total = len(names)
            db.update_background_task(task_id, total=total)

            for i, name in enumerate(names):
                try:
                    raw_bytes = z.read(name)
                    filename = os.path.basename(name)
                    ext = filename.rsplit(".", 1)[-1].lower()

                    # Same magic-byte validation used on the public apply flow —
                    # a ZIP full of resumes is still untrusted input.
                    is_valid_pdf = ext == "pdf" and raw_bytes[:4] == b"%PDF"
                    is_valid_docx = ext == "docx" and raw_bytes[:2] == b"PK"
                    if not (is_valid_pdf or is_valid_docx) or len(raw_bytes) > db.MAX_RESUME_SIZE_MB * 1024 * 1024:
                        skipped += 1
                        continue

                    resume_data = resume_parser.parse_resume(io.BytesIO(raw_bytes), filename)
                    if not resume_data["email"]:
                        skipped += 1  # can't create a candidate record without an email
                        continue

                    dup = matching.check_duplicate_resume(resume_data["text_hash"])
                    is_duplicate = dup is not None
                    if is_duplicate:
                        duplicates += 1

                    candidate_name = filename.rsplit(".", 1)[0].replace("_", " ").replace("-", " ").title()
                    safe_email = resume_data["email"].replace("@", "_at_").replace(".", "_")
                    resume_filename = f"bulk_{safe_email}_{int(datetime.now().timestamp())}.{ext}"
                    resume_file_path = os.path.join(config.RESUME_DIR, resume_filename)
                    with open(resume_file_path, "wb") as f:
                        f.write(raw_bytes)

                    candidate_fields = {
                        "name": candidate_name, "phone": resume_data.get("phone", ""),
                        "resume_data": resume_data, "is_duplicate": is_duplicate,
                        "resume_file_path": resume_file_path, "resume_filename": filename,
                    }
                    existing = db.find_candidate_by_email(resume_data["email"])
                    if existing:
                        candidate_id = str(existing["_id"])
                        db.update_candidate(candidate_id, candidate_fields)
                    else:
                        candidate_id = db.create_candidate({"email": resume_data["email"], **candidate_fields})

                    if db.check_duplicate_application(candidate_id, job_id):
                        skipped += 1
                        continue

                    screening = matching.evaluate_resume(
                        jd_text, jd_skills, resume_data["raw_text"], resume_data["skills"],
                        candidate_name, provider=ai_provider, api_key=ai_key,
                    )
                    db.create_application(candidate_id, job_id, screening)
                    created += 1
                except Exception as e:
                    errors += 1
                    error_details.append(f"{name}: {e}")

                db.update_background_task(task_id, progress=i + 1)

        db.log_action(uploaded_by, "Bulk Resume Import",
                       f"{job['title']}: {created} created, {duplicates} duplicates, "
                       f"{skipped} skipped, {errors} errors")
        db.update_background_task(
            task_id, status="done",
            result={"created": created, "duplicates": duplicates, "skipped": skipped,
                    "errors": errors, "error_details": error_details[:20]},
        )
    except Exception as e:
        db.update_background_task(task_id, status="failed", result={"error": str(e)})
    finally:
        try:
            os.remove(zip_path)
        except OSError:
            pass

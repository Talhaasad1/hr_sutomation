"""
worker.py
Standalone background-task processor for the ATS Portal.

Why this exists: with only 5-10 users, running a full Celery + Redis stack
is unnecessary complexity — it's more infrastructure to configure, monitor,
and (if left unpatched) a bigger attack surface. MongoDB itself works fine
as a lightweight task queue at this scale: the Streamlit app writes a task
document with status="queued", and this separate process picks it up,
processes it, and writes the result back — so slow operations like parsing
hundreds of resumes from a ZIP file never block the HR portal's UI.

Run this alongside the Streamlit app:
    python worker.py

Or as a separate Docker service (see docker-compose.yml) so it restarts
automatically and can be scaled independently of the web app.
"""

import time
import traceback

import db
import bulk_import

POLL_INTERVAL_SECONDS = 3
MAINTENANCE_INTERVAL_SECONDS = 60  # how often to run housekeeping checks (job auto-close, etc.)

TASK_HANDLERS = {
    "bulk_resume_import": bulk_import.process_bulk_import_task,
}


def run():
    print("[worker] Started. Polling for background tasks every "
          f"{POLL_INTERVAL_SECONDS}s ...")
    last_maintenance = 0
    while True:
        try:
            # Housekeeping: auto-close jobs past their deadline. This also
            # happens live whenever someone loads the Career Portal or Job
            # Management page, but running it here too means expired jobs
            # get closed even on days nobody visits the portal.
            now = time.time()
            if now - last_maintenance >= MAINTENANCE_INTERVAL_SECONDS:
                closed = db.auto_close_expired_jobs()
                if closed:
                    print(f"[worker] Auto-closed {closed} job(s) past their deadline.")
                last_maintenance = now

            task = db.claim_next_task()
            if task:
                task_type = task.get("type")
                handler = TASK_HANDLERS.get(task_type)
                print(f"[worker] Processing task {task['_id']} ({task_type})")
                if handler:
                    handler(task)
                    print(f"[worker] Finished task {task['_id']}")
                else:
                    db.update_background_task(str(task["_id"]), status="failed",
                                               result={"error": f"Unknown task type: {task_type}"})
            else:
                time.sleep(POLL_INTERVAL_SECONDS)
        except KeyboardInterrupt:
            print("[worker] Shutting down.")
            break
        except Exception:
            # Never let one bad task crash the whole worker loop
            print("[worker] Unexpected error:")
            traceback.print_exc()
            time.sleep(POLL_INTERVAL_SECONDS)


if __name__ == "__main__":
    run()

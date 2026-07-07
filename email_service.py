"""
email_service.py
Sends automatic (but editable) emails for each ATS pipeline stage, and
generates .ics calendar invites for scheduled interviews.
No manual emailing required — templates are filled and sent automatically
when HR moves a candidate to a new stage.
"""

import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.base import MIMEBase
from email import encoders
from datetime import datetime

import db


def render_template(template: dict, context: dict) -> tuple:
    subject = template["subject"].format(**{k: context.get(k, "") for k in _template_keys(template["subject"])})
    body = template["body"].format(**{k: context.get(k, "") for k in _template_keys(template["body"])})
    return subject, body


def _template_keys(s: str) -> dict:
    import string
    return {name: "" for _, name, _, _ in string.Formatter().parse(s) if name}


def build_ics_invite(candidate_name: str, job_title: str, date_str: str, time_str: str) -> bytes:
    """Build a minimal .ics calendar invite file for the interview."""
    try:
        dt = datetime.strptime(f"{date_str} {time_str}", "%Y-%m-%d %H:%M")
    except ValueError:
        dt = datetime.now()
    dtstamp = dt.strftime("%Y%m%dT%H%M%S")
    ics = f"""BEGIN:VCALENDAR
VERSION:2.0
PRODID:-//ATS Portal//Interview Invite//EN
BEGIN:VEVENT
UID:{dtstamp}-{candidate_name.replace(' ', '')}@ats-portal
DTSTAMP:{dtstamp}
DTSTART:{dtstamp}
SUMMARY:Interview - {job_title} - {candidate_name}
DESCRIPTION:Interview for the position of {job_title} with {candidate_name}.
END:VEVENT
END:VCALENDAR
"""
    return ics.encode("utf-8")


def send_email(smtp_server: str, smtp_port: int, sender_email: str, sender_password: str,
               receiver_email: str, subject: str, body: str, attachment_bytes: bytes = None,
               attachment_name: str = None) -> tuple:
    if not receiver_email:
        return False, "No recipient email address provided."

    msg = MIMEMultipart()
    msg["From"] = sender_email
    msg["To"] = receiver_email
    msg["Subject"] = subject
    msg.attach(MIMEText(body, "plain"))

    if attachment_bytes:
        part = MIMEBase("application", "octet-stream")
        part.set_payload(attachment_bytes)
        encoders.encode_base64(part)
        part.add_header("Content-Disposition", f"attachment; filename={attachment_name or 'attachment'}")
        msg.attach(part)

    try:
        server = smtplib.SMTP(smtp_server, smtp_port)
        server.starttls()
        server.login(sender_email, sender_password)
        server.sendmail(sender_email, receiver_email, msg.as_string())
        server.quit()
        return True, "Email sent successfully."
    except Exception as e:
        return False, f"Failed to send email: {e}"


def send_stage_email(smtp_config: dict, application_id: str, stage: str, context: dict,
                      attachment_bytes: bytes = None, attachment_name: str = None) -> tuple:
    """Look up the editable template for `stage`, render it, and send + log it."""
    template = db.get_email_template(stage)
    if not template:
        return False, f"No email template configured for stage '{stage}'."

    subject, body = render_template(template, context)
    success, msg = send_email(
        smtp_config["smtp_server"], smtp_config["smtp_port"], smtp_config["sender_email"],
        smtp_config["sender_password"], context.get("candidate_email", ""), subject, body,
        attachment_bytes, attachment_name,
    )
    db.log_email(application_id, stage, subject, "Sent" if success else f"Failed: {msg}")
    return success, msg

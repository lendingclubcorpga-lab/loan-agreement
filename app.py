import calendar
import io
from datetime import date, datetime
from textwrap import wrap
from typing import Optional
from urllib.parse import urlencode
import numpy as np
import streamlit as st
from PIL import Image
from streamlit_drawable_canvas import st_canvas
from reportlab.lib.pagesizes import letter
from reportlab.lib.units import inch
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas as pdf_canvas

# -------------------------------------------------------------------------- #
# Configuration
# -------------------------------------------------------------------------- #
st.set_page_config(page_title="LoanSign · Document e-Signing", page_icon="📝", layout="centered")

# The admin should set this to the real deployed URL of this app
BASE_URL = "https://onrender.com"

AGREEMENT_TERMS = (
    "By signing below, the borrower named above acknowledges and agrees to the terms of this loan agreement, "
    "including repayment obligations, applicable interest, fees, and all conditions as communicated by the lending institution. "
    "The borrower confirms that the information above is accurate to the best of their knowledge. This electronic signature "
    "is intended to carry the same legal weight and effect as a handwritten signature under applicable e-signature law."
)

REQUIRED_FIELDS = ["name", "address", "amount", "email"]
LOAN_TERMS_FIELDS = [
    "apr", "term_months", "orig_fee_pct", "orig_fee_amt", 
    "monthly_payment", "total_interest", "total_repayment", 
    "total_cost", "payoff_date",
]

def _add_months(start: date, months: int) -> date:
    """Add a whole number of calendar months to a date, clamping the day."""
    total_month_index = start.month - 1 + months
    year = start.year + total_month_index // 12
    month = total_month_index % 12 + 1
    day = min(start.day, calendar.monthrange(year, month)[1])
    return start.replace(year=year, month=month, day=day)

def compute_loan_terms(principal: float, apr_pct: float, term_months: int, origination_fee_pct: float, start: date) -> dict:
    """Standard amortized-loan math: payment, interest, fees, cost, and payoff date."""
    monthly_rate = apr_pct / 100 / 12
    n = term_months
    if monthly_rate > 0:
        monthly_payment = (principal * monthly_rate * (1 + monthly_rate) ** n / ((1 + monthly_rate) ** n - 1))
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

# -------------------------------------------------------------------------- #
# PDF generation
# -------------------------------------------------------------------------- #
def generate_pdf(name: str, address: str, amount: str, email: str, signature_img: Image.Image, timestamp: str, loan_terms: Optional[dict] = None) -> io.BytesIO:
    """Render a one-page signed loan agreement PDF with custom company logo."""
    buffer = io.BytesIO()
    c = pdf_canvas.Canvas(buffer, pagesize=letter)
    width, height = letter
    margin = 1 * inch
    
    # --- Top Brand Header & Logo Placement ---------------------------------
    logo_width, logo_height = 2.0 * inch, 0.65 * inch
    logo_y_position = height - margin - 0.2 * inch
    
    try:
        # Load the company logo file uploaded by the user
        logo_img = Image.open("image_hxLNr7.png")
        logo_buffer = io.BytesIO()
        logo_img.save(logo_buffer, format="PNG")
        logo_buffer.seek(0)
        
        c.drawImage(
            ImageReader(logo_buffer), 
            margin, 
            logo_y_position, 
            width=logo_width, 
            height=logo_height, 
            mask="auto"
        )
    except Exception:
        # Fallback safeguard text if the file image cannot be read locally
        c.setFont("Helvetica-Bold", 14)
        c.drawString(margin, logo_y_position + 0.2 * inch, "ADVANCE AMERICA")

    # --- Document Metadata Headers -----------------------------------------
    c.setFont("Helvetica-Bold", 18)
    c.drawRightString(width - margin, logo_y_position + 0.3 * inch, "LOAN AGREEMENT")
    
    c.setFont("Helvetica", 9)
    c.setFillGray(0.4)
    c.drawRightString(width - margin, logo_y_position + 0.1 * inch, f"Document generated: {timestamp}")
    
    c.setFillGray(0)
    c.setLineWidth(1)
    boundary_y = logo_y_position - 0.25 * inch
    c.line(margin, boundary_y, width - margin, boundary_y)
    
    y = boundary_y - 0.35 * inch

    # --- Borrower info ------------------------------------------------------
    c.setFont("Helvetica-Bold", 13)
    c.drawString(margin, y, "Borrower Information")
    y -= 0.28 * inch
    
    for label, value in [
        ("Full Name:", name),
        ("Address:", address),
        ("Loan Amount:", f"${amount}"),
        ("Email:", email),
    ]:
        c.setFont("Helvetica-Bold", 11)
        c.drawString(margin, y, label)
        c.setFont("Helvetica", 11)
        c.drawString(margin + 1.3 * inch, y, str(value))
        y -= 0.24 * inch
        
    y -= 0.15 * inch

    # --- Loan Terms -----------------------------------------------------------
    if loan_terms:
        c.setFont("Helvetica-Bold", 13)
        c.drawString(margin, y, "Loan Terms")
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
        c.drawString(margin + 1.5 * inch, y, loan_terms['payoff_date'])
        y -= 0.32 * inch

    # --- Terms --------------------------------------------------------------
    c.setFont("Helvetica-Bold", 13)
    c.drawString(margin, y, "Agreement Terms")
    y -= 0.24 * inch
    
    c.setFont("Helvetica", 10)
    for line in wrap(AGREEMENT_TERMS, 92):
        c.drawString(margin, y, line)
        y -= 0.18 * inch
        
    y -= 0.3 * inch

    # --- Signature ------------------------------------------------------------
    c.setFont("Helvetica-Bold", 13)
    c.drawString(margin, y, "Signature")
    y -= 0.15 * inch
    
    sig_width, sig_height = 3 * inch, 1.1 * inch
    if signature_img is not None:
        img_buffer = io.BytesIO()
        signature_img.save(img_buffer, format="PNG")
        img_buffer.seek(0)
        c.drawImage(ImageReader(img_buffer), margin, y - sig_height, width=sig_width, height=sig_height, mask="auto")
        
    y -= sig_height + 0.08 * inch
    c.setLineWidth(0.7)
    c.line(margin, y, margin + sig_width, y)
    
    c.setFont("Helvetica", 8)
    c.setFillGray(0.4)
    c.drawString(margin, y - 0.16 * inch, f"Signed electronically by {name} on {timestamp}")

    # --- Footer ---------------------------------------------------------------
    c.setFont("Helvetica-Oblique", 7)
    c.drawString(margin, margin * 0.4, "Generated by LoanSign — electronic signature record")
    
    c.showPage()
    c.save()
    buffer.seek(0)
    return buffer

# -------------------------------------------------------------------------- #
# Admin flow
# -------------------------------------------------------------------------- #
def admin_flow() -> None:
    st.title("📝 LoanSign — Admin Portal")
    st.caption("Fill in the borrower's details, then generate a secure link to send for e-signature.")
    with st.form("loan_form", clear_on_submit=False):
        col1, col2 = st.columns(2)
        with col1:
            name = st.text_input("Full Name", placeholder="Jane Doe")
            amount = st.text_input("Loan Amount ($)", placeholder="5000")
        with col2:
            email = st.text_input("Email", placeholder="jane@example.com")
            address = st.text_input("Address", placeholder="123 Main St, Springfield")
        st.markdown("**Loan Terms**")
        col3, col4, col5 = st.columns(3)
        with col3:
            apr = st.number_input("APR (%)", min_value=0.0, max_value=100.0, value=8.0, step=0.01, format="%.2f")
        with col4:
            term_months = st.number_input("Loan Term (months)", min_value=1, max_value=480, value=36, step=1)
        with col5:
            orig_fee_pct = st.number_input("Origination Fee (%)", min_value=0.0, max_value=100.0, value=2.5, step=0.1, format="%.2f")

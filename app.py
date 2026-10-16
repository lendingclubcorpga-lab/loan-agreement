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

# --------------------------------------------------------------------------
# Configuration
# --------------------------------------------------------------------------

# set_page_config must be the first Streamlit call.
st.set_page_config(page_title="LoanSign - Document e-Signing", page_icon="📝", layout="centered")

# IMPORTANT: change this to your real deployed app URL (no trailing slash),
# e.g. "https://your-app-name.onrender.com"
BASE_URL = "https://your-app-name.onrender.com"

AGREEMENT_TERMS = (
    "Section 1: General Agreement Framework\n"
    "By signing below, the borrower acknowledges and agrees to the terms of this loan agreement, "
    "including all repayment obligations, applicable interest, and fees as disclosed in the Loan Terms. "
    "The borrower confirms that all provided account information is accurate to the best of their knowledge. "
    "This electronic signature carries the same legal weight and effect as a handwritten signature.\n\n"
    "Section 2: Repayment\n"
    "2.1 The borrower agrees to repay the principal, interest, and any origination fee in the fixed "
    "monthly installments shown in the Loan Terms, through the payoff date stated in this agreement.\n"
    "2.2 Prepayment: The borrower may prepay all or part of the loan at any time. Any prepayment "
    "penalty must be stated here by the lender: [LENDER TO COMPLETE].\n"
    "2.3 Late payments: Late fees and consequences of default are as follows: [LENDER TO COMPLETE].\n\n"
    "Section 3: Disbursement\n"
    "Funds will be disbursed to the borrower's designated bank account after this agreement is signed. "
    "No payment from the borrower is required before disbursement, other than any origination fee "
    "disclosed in the Loan Terms, which is deducted from the loan proceeds.\n\n"
    "Section 4: Lender Information\n"
    "Lender name, license number, and contact details: [LENDER TO COMPLETE]."
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
# Loan math
# --------------------------------------------------------------------------

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
    c.drawString(margin, height - margin, "LOAN AGREEMENT DOCUMENT")
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

    for label, value in [
        ("Full Name:", name),
        ("Address:", address),
        ("Disbursing Bank:", bank_name),
        ("Loan Amount:", f"${amount}"),
        ("Email:", email),
    ]:
        lines = wrap(str(value), 60) or [""]
        c.setFont("Helvetica-Bold", 11)
        c.drawString(margin, y, label)
        c.setFont("Helvetica", 11)
        for line in lines:
            c.drawString(margin + 1.5 * inch, y, line)
            y -= 0.22 * inch
        y -= 0.02 * inch

    y -= 0.15 * inch

    # Loan terms
    if loan_terms:
        y = new_page_if_needed(y, 2 * inch)
        c.setFont("Helvetica-Bold", 13)
        c.drawString(margin, y, "Loan Terms")
        y -= 0.28 * inch

        left_col = [
            ("APR:", f"{loan_terms['apr']}%"),
            ("Term:", f"{loan_terms['term_months']} months"),
            ("Origination Fee:", f"{loan_terms['orig_fee_pct']}% (${loan_terms['orig_fee_amt']})"),
            ("Monthly Payment:", f"${loan_terms['monthly_payment']}"),
        ]
        right_col = [
            ("Total Interest:", f"${loan_terms['total_interest']}"),
            ("Total Repayment:", f"${loan_terms['total_repayment']}"),
            ("Total Cost:", f"${loan_terms['total_cost']}"),
            ("Payoff Date:", loan_terms["payoff_date"]),
        ]
        col2_x = margin + 3.2 * inch
        row_y = y
        for (l1, v1), (l2, v2) in zip(left_col, right_col):
            c.setFont("Helvetica-Bold", 10)
            c.drawString(margin, row_y, l1)
            c.drawString(col2_x, row_y, l2)
            c.setFont("Helvetica", 10)
            c.drawString(margin + 1.3 * inch, row_y, v1)
            c.drawString(col2_x + 1.2 * inch, row_y, v2)
            row_y -= 0.22 * inch
        y = row_y - 0.15 * inch

    # Terms
    y = new_page_if_needed(y, 1 * inch)
    c.setFont("Helvetica-Bold", 13)
    c.drawString(margin, y, "Agreement Terms")
    y -= 0.24 * inch

    c.setFont("Helvetica", 10)
    for paragraph in AGREEMENT_TERMS.split("\n"):
        if not paragraph.strip():
            y -= 0.12 * inch
            continue
        for line in wrap(paragraph, 92):
            if y < margin + 0.5 * inch:
                c.showPage()
                y = height - margin
                c.setFont("Helvetica", 10)
            c.drawString(margin, y, line)
            y -= 0.18 * inch

    y -= 0.3 * inch

    # Signature
    sig_width, sig_height = 3 * inch, 1.1 * inch
    y = new_page_if_needed(y, sig_height + 1 * inch)
    c.setFont("Helvetica-Bold", 13)
    c.drawString(margin, y, "Signature")
    y -= 0.15 * inch

    if signature_img is not None:
        img_buffer = io.BytesIO()
        signature_img.save(img_buffer, format="PNG")
        img_buffer.seek(0)
        c.drawImage(ImageReader(img_buffer), margin, y - sig_height,
                    width=sig_width, height=sig_height, mask="auto")
        y -= sig_height + 0.08 * inch

    c.setLineWidth(0.8)
    c.line(margin, y, margin + sig_width, y)
    y -= 0.2 * inch
    c.setFont("Helvetica", 10)
    c.drawString(margin, y, f"Signed by: {name}")
    y -= 0.18 * inch
    c.drawString(margin, y, f"Signed on: {timestamp}")

    c.save()
    buffer.seek(0)
    return buffer


# --------------------------------------------------------------------------
# Admin flow
# --------------------------------------------------------------------------

def admin_flow():
    st.title("📝 LoanSign - Admin")
    st.caption("Create a loan record and generate a shareable signing link for the borrower.")

    with st.form("loan_form"):
        name = st.text_input("Borrower full name")
        email = st.text_input("Borrower email")
        address = st.text_area("Borrower address", height=80)
        bank_name = st.text_input("Disbursing bank name")

        col1, col2 = st.columns(2)
        with col1:
            amount = st.number_input("Loan amount ($)", min_value=100.0, value=5000.0, step=100.0)
            term_months = st.number_input("Term (months)", min_value=1, max_value=120, value=12, step=1)
        with col2:
            apr = st.number_input("APR (%)", min_value=0.0, max_value=100.0, value=12.0, step=0.25)
            fee_pct = st.number_input("Origination fee (%)", min_value=0.0, max_value=25.0, value=2.0, step=0.25)

        submitted = st.form_submit_button("Generate signing link")

    if not submitted:
        return

    values = {"name": name.strip(), "address": address.strip(), "email": email.strip(),
              "bank_name": bank_name.strip()}
    missing = [k for k, v in values.items() if not v]
    if missing:
        st.error("Please fill in: " + ", ".join(m.replace("_", " ") for m in missing))
        return

    terms = compute_loan_terms(float(amount), float(apr), int(term_months),
                               float(fee_pct), date.today())
    params = {**values, "amount": f"{amount:.2f}", **terms}
    link = f"{BASE_URL.rstrip('/')}/?{urlencode(params)}"

    st.success("Signing link generated.")
    st.code(link, language=None)

    st.subheader("Loan summary")
    c1, c2, c3 = st.columns(3)
    c1.metric("Monthly payment", f"${terms['monthly_payment']}")
    c2.metric("Total interest", f"${terms['total_interest']}")
    c3.metric("Total cost", f"${terms['total_cost']}")
    st.write(f"Payoff date: **{terms['payoff_date']}**")


# --------------------------------------------------------------------------
# Customer flow
# --------------------------------------------------------------------------

def customer_flow(params: dict):
    name = params["name"]
    address = params["address"]
    amount = params["amount"]
    email = params["email"]
    bank_name = params["bank_name"]
    loan_terms = (
        {k: params[k] for k in LOAN_TERMS_FIELDS}
        if all(k in params for k in LOAN_TERMS_FIELDS) else None
    )

    st.title("📝 Loan Agreement")
    st.caption("Please review the details below, then sign to complete the agreement.")

    st.subheader("Borrower & account information")
    st.markdown(
        f"**Name:** {html.escape(name)}  \n"
        f"**Address:** {html.escape(address)}  \n"
        f"**Disbursing bank:** {html.escape(bank_name)}  \n"
        f"**Loan amount:** ${html.escape(amount)}  \n"
        f"**Email:** {html.escape(email)}"
    )

    if loan_terms:
        st.subheader("Loan terms")
        c1, c2, c3 = st.columns(3)
        c1.metric("APR", f"{loan_terms['apr']}%")
        c2.metric("Term", f"{loan_terms['term_months']} mo")
        c3.metric("Monthly payment", f"${loan_terms['monthly_payment']}")
        c4, c5, c6 = st.columns(3)
        c4.metric("Total interest", f"${loan_terms['total_interest']}")
        c5.metric("Origination fee", f"${loan_terms['orig_fee_amt']}")
        c6.metric("Total cost", f"${loan_terms['total_cost']}")
        st.write(f"Payoff date: **{loan_terms['payoff_date']}**")

    st.subheader("Agreement terms")
    st.markdown(
        f'<div class="full-terms-container">{html.escape(AGREEMENT_TERMS)}</div>',
        unsafe_allow_html=True,
    )

    agreed = st.checkbox("I have read and agree to the terms above.")

    st.subheader("Sign here")
    canvas_result = st_canvas(
        fill_color="rgba(255, 255, 255, 0)",
        stroke_width=3,
        stroke_color="#000000",
        background_color="#FFFFFF",
        height=180,
        width=500,
        drawing_mode="freedraw",
        key="signature_canvas",
    )

    signature_img = None
    if canvas_result.image_data is not None:
        arr = canvas_result.image_data.astype("uint8")
        # Treat as signed only if something was actually drawn (non-white pixels).
        if arr[:, :, :3].min() < 250 or arr[:, :, 3].min() < 255:
            rgba = Image.fromarray(arr, "RGBA")
            background = Image.new("RGB", rgba.size, (255, 255, 255))
            background.paste(rgba, mask=rgba.split()[3])
            signature_img = background

    if not agreed:
        st.info("Tick the box above to enable signing.")
        return
    if signature_img is None:
        st.info("Draw your signature in the box above.")
        return

    timestamp = datetime.now().strftime("%B %d, %Y at %I:%M %p")
    st.success("Signature captured. You can download your signed copy below.")

    png_buf = io.BytesIO()
    signature_img.save(png_buf, format="PNG")
    pdf_buf = generate_pdf(name, address, amount, email, bank_name,
                           signature_img, timestamp, loan_terms)

    d1, d2 = st.columns(2)
    d1.download_button("Download signature (PNG)", data=png_buf.getvalue(),
                       file_name="signature.png", mime="image/png")
    d2.download_button("Download signed agreement (PDF)", data=pdf_buf.getvalue(),
                       file_name="signed_loan_agreement.pdf", mime="application/pdf")


# --------------------------------------------------------------------------
# Router
# --------------------------------------------------------------------------

def main():
    params = {k: (v if isinstance(v, str) else v[0]) for k, v in st.query_params.items()}

    if not params:
        admin_flow()
        return

    missing = [f for f in REQUIRED_FIELDS if not params.get(f)]
    if missing:
        st.error("This signing link is incomplete or invalid. Missing: " + ", ".join(missing))
        return

    customer_flow(params)


main()

"""
LoanSign — A single-file Streamlit loan document e-signing platform.

Two flows, driven entirely by URL query parameters:
  - ADMIN FLOW   (no query params): build a loan record, get a shareable signing link.
  - CUSTOMER FLOW (query params present): review the agreement, draw a signature,
                   download it as PNG or as a formal signed PDF.

Run with:
    streamlit run app.py
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
# Configuration
# --------------------------------------------------------------------------

st.set_page_config(page_title="LoanSign · Document e-Signing", page_icon="📝", layout="centered")

# The admin should set this to the real deployed URL of this app
# (e.g. "https://loansign.streamlit.app"). It's used purely to build the
# link shown to the admin — the customer's browser already knows its own URL,
# so this constant is never relied on in the customer flow.
BASE_URL = "https://loan-agreement-e-sign.onrender.com"

AGREEMENT_TERMS = (
    "By signing below, the borrower named above acknowledges and agrees to the terms of "
    "this loan agreement, including repayment obligations, applicable interest, fees, and "
    "all conditions as communicated by the lending institution. The borrower confirms that "
    "the information above is accurate to the best of their knowledge. This electronic "
    "signature is intended to carry the same legal weight and effect as a handwritten "
    "signature under applicable e-signature law."
)

REQUIRED_FIELDS = ["name", "address", "amount", "email"]

# Loan-terms fields are optional so links generated before this feature was
# added still work — the customer view just skips the "Loan Terms" section
# if any of these are missing.
LOAN_TERMS_FIELDS = [
    "apr", "term_months", "orig_fee_pct", "orig_fee_amt",
    "monthly_payment", "total_interest", "total_repayment",
    "total_cost", "payoff_date",
]


def _add_months(start: date, months: int) -> date:
    """Add a whole number of calendar months to a date, clamping the day
    to the last valid day of the resulting month (e.g. Jan 31 + 1mo -> Feb 28/29)."""
    total_month_index = start.month - 1 + months
    year = start.year + total_month_index // 12
    month = total_month_index % 12 + 1
    day = min(start.day, calendar.monthrange(year, month)[1])
    return start.replace(year=year, month=month, day=day)


def compute_loan_terms(principal: float, apr_pct: float, term_months: int,
                        origination_fee_pct: float, start: date) -> dict:
    """Standard amortized-loan math: fixed monthly payment, total interest,
    origination fee, total cost, and the payoff date."""
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

def generate_pdf(name: str, address: str, amount: str, email: str,
                  signature_img: Image.Image, timestamp: str,
                  loan_terms: Optional[dict] = None) -> io.BytesIO:
    """Render a one-page signed loan agreement PDF and return it as a buffer."""
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

    # --- Borrower info ------------------------------------------------------
    c.setFont("Helvetica-Bold", 13)
    c.drawString(margin, y, "Borrower Information")
    y -= 0.28 * inch

    c.setFont("Helvetica", 11)
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
        c.drawString(margin + 1.5 * inch, y, loan_terms["payoff_date"])
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
        c.drawImage(
            ImageReader(img_buffer),
            margin,
            y - sig_height,
            width=sig_width,
            height=sig_height,
            mask="auto",
        )
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


# --------------------------------------------------------------------------
# Admin flow
# --------------------------------------------------------------------------

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
            apr = st.number_input("APR (%)", min_value=0.0, max_value=100.0, value=8, step=0.01, format="%.2f")
        with col4:
            term_months = st.number_input("Loan Term (months)", min_value=1, max_value=480, value=36, step=1)
        with col5:
            orig_fee_pct = st.number_input("Origination Fee (%)", min_value=0.0, max_value=100.0, value=2.5, step=0.1, format="%.2f")

        submitted = st.form_submit_button("🔗 Generate Signing Link", use_container_width=True)

    if not submitted:
        return

    if not all(field.strip() for field in [name, address, amount, email]):
        st.error("⚠️ Please fill in every field before generating a link.")
        return

    try:
        float(amount.replace(",", "").replace("$", ""))
    except ValueError:
        st.error("⚠️ Loan amount must be a valid number (e.g. 5000 or 5000.00).")
        return

    if "@" not in email or "." not in email.split("@")[-1]:
        st.error("⚠️ Please enter a valid email address.")
        return

    principal = float(amount.replace(",", "").replace("$", ""))
    loan_terms = compute_loan_terms(
        principal=principal,
        apr_pct=apr,
        term_months=int(term_months),
        origination_fee_pct=orig_fee_pct,
        start=date.today(),
    )

    params = {
        "name": name.strip(),
        "address": address.strip(),
        "amount": amount.strip(),
        "email": email.strip(),
        **loan_terms,
    }
    full_link = f"{BASE_URL}?{urlencode(params)}"

    st.success("✅ Signing link generated successfully.")
    st.code(full_link, language=None)
    st.caption(
        "Copy this link and send it to your customer. Opening it will show them the loan "
        "agreement pre-filled with these details, ready for their electronic signature."
    )


# --------------------------------------------------------------------------
# Customer flow
# --------------------------------------------------------------------------

def customer_flow(params) -> None:
    values = {field: params.get(field, "").strip() for field in REQUIRED_FIELDS}
    missing = [field for field, value in values.items() if not value]

    if missing:
        st.error(
            "⚠️ This signing link is incomplete — missing: "
            f"**{', '.join(missing)}**. Please request a fresh link from your lender."
        )
        st.stop()

    name, address, amount, email = (
        values["name"], values["address"], values["amount"], values["email"]
    )

    st.title("📄 Loan Agreement Document")
    st.caption("Please review the details below carefully before signing.")

    with st.container(border=True):
        st.subheader("Borrower Information")
        c1, c2 = st.columns(2)
        c1.markdown(f"**Full Name**  \n{name}")
        c1.markdown(f"**Loan Amount**  \n${amount}")
        c2.markdown(f"**Email**  \n{email}")
        c2.markdown(f"**Address**  \n{address}")

        loan_terms = {field: params.get(field, "").strip() for field in LOAN_TERMS_FIELDS}
        has_loan_terms = all(loan_terms.values())

        if has_loan_terms:
            st.divider()
            st.subheader("Loan Terms")
            t1, t2 = st.columns(2)
            t1.markdown(f"**APR**  \n{loan_terms['apr']}%")
            t1.markdown(f"**Origination Fee**  \n{loan_terms['orig_fee_pct']}% (${loan_terms['orig_fee_amt']})")
            t1.markdown(f"**Monthly Payment**  \n${loan_terms['monthly_payment']}")
            t2.markdown(f"**Total Interest**  \n${loan_terms['total_interest']}")
            t2.markdown(f"**Total Repayment Amount**  \n${loan_terms['total_repayment']}")
            t2.markdown(f"**Total Cost of Loan**  \n${loan_terms['total_cost']}")
            st.markdown(f"**Payoff Date**  \n{loan_terms['payoff_date']}")

        st.divider()
        st.subheader("Agreement Terms")
        st.write(AGREEMENT_TERMS)

    st.subheader("✍️ Draw Your Signature Below")
    st.caption("Use your mouse or touchscreen to sign inside the box.")

    canvas_result = st_canvas(
        fill_color="rgba(255, 255, 255, 0)",
        stroke_width=3,
        stroke_color="#000000",
        background_color="#FFFFFF",
        height=200,
        width=600,
        drawing_mode="freedraw",
        key="signature_canvas",
    )

    signature_ready = (
        canvas_result.image_data is not None
        and canvas_result.image_data[:, :, 3].sum() > 0
    )

    sig_img = None
    if signature_ready:
        sig_array = canvas_result.image_data.astype("uint8")
        rgba_img = Image.fromarray(sig_array, mode="RGBA")
        white_bg = Image.new("RGBA", rgba_img.size, "WHITE")
        white_bg.paste(rgba_img, mask=rgba_img)
        sig_img = white_bg.convert("RGB")
    else:
        st.info("✏️ Please draw your signature above — downloads will unlock once you sign.")

    st.divider()
    col1, col2 = st.columns(2)

    with col1:
        if signature_ready:
            png_buffer = io.BytesIO()
            sig_img.save(png_buffer, format="PNG")
            png_buffer.seek(0)
            st.download_button(
                "⬇️ Download Signature (PNG)",
                data=png_buffer,
                file_name=f"signature_{name.replace(' ', '_')}.png",
                mime="image/png",
                use_container_width=True,
            )
        else:
            st.button("⬇️ Download Signature (PNG)", disabled=True, use_container_width=True)

    with col2:
        if signature_ready:
            timestamp = datetime.now().strftime("%B %d, %Y at %I:%M %p")
            pdf_buffer = generate_pdf(
                name, address, amount, email, sig_img, timestamp,
                loan_terms=loan_terms if has_loan_terms else None,
            )
            st.download_button(
                "⬇️ Download Signed Agreement (PDF)",
                data=pdf_buffer,
                file_name=f"loan_agreement_{name.replace(' ', '_')}.pdf",
                mime="application/pdf",
                use_container_width=True,
            )
        else:
            st.button("⬇️ Download Signed Agreement (PDF)", disabled=True, use_container_width=True)


# --------------------------------------------------------------------------
# Entry point
# --------------------------------------------------------------------------

def main() -> None:
    params = st.query_params
    if len(params) > 0:
        customer_flow(params)
    else:
        admin_flow()


if __name__ == "__main__":
    main()

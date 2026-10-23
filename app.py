def generate_pdf(name: str, address: str, amount: str, email: str, signature_img: Image.Image, timestamp: str, loan_terms: Optional[dict] = None) -> io.BytesIO:
    """Render a one-page signed loan agreement PDF with custom company logo."""
    buffer = io.BytesIO()
    c = pdf_canvas.Canvas(buffer, pagesize=letter)
    width, height = letter
    margin = 1 * inch
    
    # --- Top Brand Header & Logo Placement ---------------------------------
    # Define bounding space for the company logo at the top left margin
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
        # Fallback safeguard placeholder text block if the image file cannot be read
        c.setFont("Helvetica-Bold", 14)
        c.drawString(margin, logo_y_position + 0.2 * inch, "ADVANCE AMERICA")

    # --- Document Metadata Headers -----------------------------------------
    # Shift title text slightly rightwards to sit clean beside the logo bounds
    c.setFont("Helvetica-Bold", 18)
    c.drawRightString(width - margin, logo_y_position + 0.3 * inch, "LOAN AGREEMENT")
    
    c.setFont("Helvetica", 9)
    c.setFillGray(0.4)
    c.drawRightString(width - margin, logo_y_position + 0.1 * inch, f"Document generated: {timestamp}")
    
    # Establish structural horizontal boundary rule clear below the top header
    c.setFillGray(0)
    c.setLineWidth(1)
    boundary_y = logo_y_position - 0.25 * inch
    c.line(margin, boundary_y, width - margin, boundary_y)
    
    # Reset downstream vertical starting coordinate index
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

"""
Smart NIC Card Renderer & PDF Generator
Generates ISO/IEC 7810 ID-1 proportioned (1012x638) Front & Back National Identity Card visuals
and downloadable print-ready PDF documents.
Uses clearly marked academic prototype designation — never official government seals.
"""

import os
import io
import textwrap
import tempfile
from typing import Dict, Any, Tuple

from PIL import Image, ImageDraw, ImageFont
from fpdf import FPDF

from modules.database import BASE_DIR, get_setting
from modules.qr_service import generate_qr_image

LOGO_PATH = os.path.join(BASE_DIR, "assets", "logo.png")
CARD_W, CARD_H = 1012, 638


def _load_font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    """Load clean TrueType font with graceful Windows/Linux/default fallback."""
    candidates = []
    if bold:
        candidates = [
            "C:/Windows/Fonts/arialbd.ttf",
            "C:/Windows/Fonts/segoeuib.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
            "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
        ]
    else:
        candidates = [
            "C:/Windows/Fonts/arial.ttf",
            "C:/Windows/Fonts/segoeui.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
            "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
        ]
    for path in candidates:
        if os.path.exists(path):
            try:
                return ImageFont.truetype(path, size=size)
            except Exception:
                continue
    return ImageFont.load_default()


def _load_citizen_photo(photo_path: str, size: Tuple[int, int] = (210, 250)) -> Image.Image:
    """Load citizen photo resized & cropped neatly, or create a professional silhouette avatar."""
    if photo_path and os.path.exists(photo_path):
        try:
            img = Image.open(photo_path).convert("RGB")
            # Center crop to target aspect ratio
            tw, th = size
            iw, ih = img.size
            target_ratio = tw / th
            img_ratio = iw / ih
            if img_ratio > target_ratio:
                new_w = int(ih * target_ratio)
                left = (iw - new_w) // 2
                img = img.crop((left, 0, left + new_w, ih))
            else:
                new_h = int(iw / target_ratio)
                top = (ih - new_h) // 2
                img = img.crop((0, top, iw, top + new_h))
            return img.resize(size, Image.Resampling.LANCZOS)
        except Exception:
            pass

    # Clean vector placeholder silhouette
    ph = Image.new("RGB", size, (226, 232, 240))
    d = ImageDraw.Draw(ph)
    cx = size[0] // 2
    d.ellipse([cx - 42, 42, cx + 42, 126], fill=(148, 163, 184))
    d.pieslice([cx - 78, 138, cx + 78, 290], 180, 360, fill=(148, 163, 184))
    return ph


def _status_palette(status: str) -> Tuple[Tuple[int, int, int], Tuple[int, int, int]]:
    s = (status or "ACTIVE").upper()
    if s == "ACTIVE":
        return (236, 253, 245), (5, 150, 105)
    if s == "EXPIRED":
        return (255, 251, 235), (217, 119, 6)
    if s == "REVOKED":
        return (254, 242, 242), (220, 38, 38)
    return (241, 245, 249), (71, 85, 105)


def render_card_front(card: Dict[str, Any]) -> Image.Image:
    """Render high-resolution Front of the Smart National Identity Card."""
    img = Image.new("RGB", (CARD_W, CARD_H), (255, 255, 255))
    draw = ImageDraw.Draw(img)

    # Subtle security micro-pattern lines in background
    for y in range(135, CARD_H - 45, 18):
        draw.line([(0, y), (CARD_W, y)], fill=(248, 250, 252), width=1)
    for x in range(0, CARD_W, 36):
        draw.line([(x, 135), (x + 120, CARD_H - 45)], fill=(241, 245, 249), width=1)

    # Top Royal Blue Official-Inspired Academic Header Band
    draw.rectangle([0, 0, CARD_W, 132], fill=(29, 78, 216))
    draw.rectangle([0, 122, CARD_W, 132], fill=(37, 99, 235))
    # Subtle accent stripe
    draw.rectangle([0, 132, CARD_W, 138], fill=(16, 185, 129))

    # Project Emblem Logo
    if os.path.exists(LOGO_PATH):
        try:
            logo = Image.open(LOGO_PATH).convert("RGBA").resize((86, 86), Image.Resampling.LANCZOS)
            img.paste(logo, (34, 22), logo)
        except Exception:
            pass

    f_auth = _load_font(18, bold=True)
    f_title = _load_font(30, bold=True)
    f_badge = _load_font(15, bold=True)
    f_lbl = _load_font(15, bold=True)
    f_val = _load_font(23, bold=True)
    f_name = _load_font(30, bold=True)
    f_nic = _load_font(26, bold=True)
    f_small = _load_font(14, bold=False)

    authority = get_setting("issuing_authority_demo", "ACADEMIC DEMO IDENTITY AUTHORITY (PROTOTYPE)").upper()
    draw.text((138, 26), authority[:56], fill=(191, 219, 254), font=f_auth)
    draw.text((138, 56), "SMART NATIONAL IDENTITY CARD", fill=(255, 255, 255), font=f_title)
    draw.text((138, 94), "DIGITAL IDENTITY CREDENTIAL  •  FICTIONAL DEMO PROTOTYPE", fill=(147, 197, 253), font=f_small)

    # Status Pill in Top Right
    st_bg, st_fg = _status_palette(card.get("status", "ACTIVE"))
    status_text = str(card.get("status", "ACTIVE")).upper()
    draw.rounded_rectangle([CARD_W - 170, 38, CARD_W - 34, 78], radius=18, fill=st_bg)
    draw.text((CARD_W - 145, 49), status_text, fill=st_fg, font=f_badge)

    # Citizen Photograph Frame (Left)
    photo = _load_citizen_photo(card.get("photo_path", ""), size=(210, 260))
    draw.rounded_rectangle([38, 166, 256, 434], radius=12, fill=(241, 245, 249), outline=(203, 213, 225), width=3)
    img.paste(photo, (42, 170))

    # Smart Chip Visual Graphic below photo (symbolic card detail)
    draw.rounded_rectangle([42, 454, 118, 508], radius=8, fill=(251, 191, 36), outline=(217, 119, 6), width=2)
    draw.line([(42, 481), (118, 481)], fill=(180, 83, 9), width=2)
    draw.line([(80, 454), (80, 508)], fill=(180, 83, 9), width=2)
    draw.rounded_rectangle([64, 469, 96, 493], radius=4, outline=(180, 83, 9), width=2)
    draw.text((130, 462), "SMART NIC", fill=(30, 41, 59), font=f_lbl)
    draw.text((130, 484), "VERIFIED QR", fill=(100, 116, 139), font=f_small)

    # Citizen Details (Center Column)
    x_col = 290
    draw.text((x_col, 168), "FULL NAME", fill=(100, 116, 139), font=f_lbl)
    draw.text((x_col, 190), str(card.get("full_name", "N/A"))[:28], fill=(15, 23, 42), font=f_name)

    draw.text((x_col, 242), "NATIONAL IDENTITY NUMBER (DEMO)", fill=(100, 116, 139), font=f_lbl)
    draw.rounded_rectangle([x_col, 265, x_col + 365, 312], radius=8, fill=(239, 246, 255), outline=(191, 219, 254), width=2)
    draw.text((x_col + 14, 274), str(card.get("nic_number", "SNIC-0000-000000")), fill=(29, 78, 216), font=f_nic)

    # Grid of DOB / Gender / Issue / Expiry
    draw.text((x_col, 334), "DATE OF BIRTH", fill=(100, 116, 139), font=f_lbl)
    draw.text((x_col, 356), str(card.get("date_of_birth", "—")), fill=(15, 23, 42), font=f_val)

    draw.text((x_col + 210, 334), "GENDER", fill=(100, 116, 139), font=f_lbl)
    draw.text((x_col + 210, 356), str(card.get("gender", "—")), fill=(15, 23, 42), font=f_val)

    draw.text((x_col, 408), "ISSUE DATE", fill=(100, 116, 139), font=f_lbl)
    draw.text((x_col, 430), str(card.get("issue_date", "—")), fill=(15, 23, 42), font=f_val)

    draw.text((x_col + 210, 408), "EXPIRY DATE", fill=(100, 116, 139), font=f_lbl)
    draw.text((x_col + 210, 430), str(card.get("expiry_date", "—")), fill=(220, 38, 38) if status_text == "EXPIRED" else (15, 23, 42), font=f_val)

    # QR Code (Right Column) — encodes ONLY opaque signed token!
    qr_img = generate_qr_image(card["verification_token"], card["token_signature"], box_size=6, border=2)
    qr_img = qr_img.resize((220, 220), Image.Resampling.NEAREST)
    qr_x, qr_y = CARD_W - 260, 185
    draw.rounded_rectangle([qr_x - 10, qr_y - 10, qr_x + 230, qr_y + 260], radius=12, fill=(255, 255, 255), outline=(203, 213, 225), width=2)
    img.paste(qr_img, (qr_x, qr_y))
    draw.text((qr_x + 24, qr_y + 228), "SCAN TO VERIFY", fill=(37, 99, 235), font=f_lbl)

    # Bottom Footer Bar
    draw.rectangle([0, CARD_H - 46, CARD_W, CARD_H], fill=(15, 23, 42))
    draw.text((38, CARD_H - 32), f"CITIZEN CODE: {card.get('citizen_code', 'N/A')}   |   BLOOD GROUP: {card.get('blood_group', 'Unknown')}", fill=(203, 213, 225), font=f_small)
    draw.text((CARD_W - 355, CARD_H - 32), "ACADEMIC PROTOTYPE — DEMO USE ONLY", fill=(147, 197, 253), font=f_small)

    # Outer Border
    draw.rounded_rectangle([1, 1, CARD_W - 2, CARD_H - 2], radius=16, outline=(203, 213, 225), width=3)
    return img


def render_card_back(card: Dict[str, Any]) -> Image.Image:
    """Render high-resolution Back of the Smart National Identity Card."""
    img = Image.new("RGB", (CARD_W, CARD_H), (255, 255, 255))
    draw = ImageDraw.Draw(img)

    # Top Slate Header Strip
    draw.rectangle([0, 0, CARD_W, 74], fill=(15, 23, 42))
    f_hdr = _load_font(20, bold=True)
    f_lbl = _load_font(16, bold=True)
    f_body = _load_font(20, bold=False)
    f_small = _load_font(15, bold=False)
    f_warn = _load_font(16, bold=True)

    draw.text((38, 24), "SMART NATIONAL IDENTITY CARD — CARDHOLDER & VERIFICATION DETAILS", fill=(255, 255, 255), font=f_hdr)

    # Residential Address Box
    draw.rounded_rectangle([38, 102, CARD_W - 38, 256], radius=12, fill=(248, 250, 252), outline=(226, 232, 240), width=2)
    draw.text((58, 118), "RESIDENTIAL ADDRESS", fill=(37, 99, 235), font=f_lbl)

    full_addr = f"{card.get('residential_address', '')}, {card.get('city', '')}, {card.get('state', '')} - {card.get('postal_code', '')}"
    wrapped_addr = textwrap.wrap(full_addr, width=68)
    y_cursor = 148
    for line in wrapped_addr[:3]:
        draw.text((58, y_cursor), line, fill=(15, 23, 42), font=f_body)
        y_cursor += 30

    # Card Status & Metadata Row
    status_text = str(card.get("status", "ACTIVE")).upper()
    st_bg, st_fg = _status_palette(status_text)

    draw.rounded_rectangle([38, 278, 490, 428], radius=12, fill=(255, 255, 255), outline=(226, 232, 240), width=2)
    draw.text((58, 294), "CARD STATUS & RECORD", fill=(37, 99, 235), font=f_lbl)
    draw.rounded_rectangle([58, 326, 200, 362], radius=16, fill=st_bg)
    draw.text((84, 334), status_text, fill=st_fg, font=f_lbl)
    draw.text((220, 334), f"NIC: {card.get('nic_number', '')}", fill=(15, 23, 42), font=f_lbl)
    draw.text((58, 382), f"Valid: {card.get('issue_date', '')}  to  {card.get('expiry_date', '')}", fill=(71, 85, 105), font=f_small)

    # QR Verification Instructions Box
    draw.rounded_rectangle([514, 278, CARD_W - 38, 428], radius=12, fill=(239, 246, 255), outline=(191, 219, 254), width=2)
    draw.text((534, 294), "QR VERIFICATION INSTRUCTIONS", fill=(29, 78, 216), font=f_lbl)
    inst_lines = [
        "1. Open the Smart NIC Public QR Verification Portal.",
        "2. Scan the front QR code or enter the NIC number.",
        "3. Cryptographic signature & status are verified live.",
        "4. No private contact info is stored inside the QR.",
    ]
    iy = 322
    for l in inst_lines:
        draw.text((534, iy), l, fill=(30, 58, 138), font=f_small)
        iy += 24

    # Card Instructions & Academic Prototype Disclaimer
    draw.rounded_rectangle([38, 450, CARD_W - 38, 566], radius=12, fill=(255, 251, 235), outline=(253, 230, 138), width=2)
    draw.text((58, 464), "CARDHOLDER INSTRUCTIONS & PROTOTYPE NOTICE", fill=(180, 83, 9), font=f_warn)
    watermark = get_setting("demo_watermark_text", "ACADEMIC PROTOTYPE — NOT AN OFFICIAL GOVERNMENT ID")
    draw.text((58, 492), f"• {watermark}", fill=(146, 64, 14), font=f_small)
    draw.text((58, 516), "• Report lost or damaged credentials immediately via the Citizen Portal to revoke this token.", fill=(120, 53, 15), font=f_small)
    draw.text((58, 538), "• Renewal requests should be submitted prior to the printed expiry date.", fill=(120, 53, 15), font=f_small)

    # Bottom Stripe
    draw.rectangle([0, CARD_H - 42, CARD_W, CARD_H], fill=(241, 245, 249))
    draw.text((38, CARD_H - 30), "Smart NIC – National Identity Card Management & Verification System (ECE Minor Project)", fill=(100, 116, 139), font=f_small)
    draw.rounded_rectangle([1, 1, CARD_W - 2, CARD_H - 2], radius=16, outline=(203, 213, 225), width=3)
    return img


def image_to_png_bytes(img: Image.Image) -> bytes:
    """Convert PIL Image to PNG bytes."""
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def generate_card_pdf_bytes(card: Dict[str, Any]) -> bytes:
    """Generate a clean print-ready PDF containing Front & Back Smart NIC views and verification details."""
    front_img = render_card_front(card)
    back_img = render_card_back(card)

    with tempfile.NamedTemporaryFile(delete=False, suffix=".png") as tf_front, \
         tempfile.NamedTemporaryFile(delete=False, suffix=".png") as tf_back:
        front_img.save(tf_front.name, format="PNG")
        back_img.save(tf_back.name, format="PNG")
        f_path, b_path = tf_front.name, tf_back.name

    try:
        pdf = FPDF(orientation="P", unit="mm", format="A4")
        pdf.set_auto_page_break(auto=True, margin=15)
        pdf.add_page()

        # Title Header
        pdf.set_font("Arial", "B", 16)
        pdf.set_text_color(15, 23, 42)
        pdf.cell(0, 10, "SMART NIC - DIGITAL NATIONAL IDENTITY CARD", ln=True, align="C")

        pdf.set_font("Arial", "", 10)
        pdf.set_text_color(100, 116, 139)
        pdf.cell(0, 6, "Academic Prototype Credential Sheet  |  Not an Official Government Document", ln=True, align="C")
        pdf.ln(6)

        # Front Card
        pdf.set_font("Arial", "B", 11)
        pdf.set_text_color(37, 99, 235)
        pdf.cell(0, 7, "CARD FRONT (ISO/IEC 7810 ID-1 PROPORTIONAL VIEW)", ln=True)
        pdf.image(f_path, x=25, y=pdf.get_y() + 2, w=160)
        pdf.ln(108)

        # Back Card
        pdf.set_font("Arial", "B", 11)
        pdf.set_text_color(37, 99, 235)
        pdf.cell(0, 7, "CARD BACK (ADDRESS & VERIFICATION GUIDE)", ln=True)
        pdf.image(b_path, x=25, y=pdf.get_y() + 2, w=160)
        pdf.ln(108)

        # Summary Footer
        pdf.set_font("Arial", "", 9)
        pdf.set_text_color(71, 85, 105)
        pdf.cell(0, 6, f"NIC Number: {card.get('nic_number')}   |   Holder: {card.get('full_name')}   |   Status: {card.get('status')}", ln=True, align="C")
        pdf.cell(0, 5, f"Issued: {card.get('issue_date')}   |   Expires: {card.get('expiry_date')}", ln=True, align="C")

        out = pdf.output(dest="S")
        return out.encode("latin-1") if isinstance(out, str) else bytes(out)
    finally:
        for p in (f_path, b_path):
            if os.path.exists(p):
                try:
                    os.remove(p)
                except Exception:
                    pass

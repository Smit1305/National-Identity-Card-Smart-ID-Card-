"""
QR Code Generation, Scanning (OpenCV), and Cryptographic Token Verification Service
- Encodes ONLY an opaque signed verification credential (never sensitive PII) into QR codes.
- Supports live webcam / uploaded image QR scanning via OpenCV QRCodeDetector.
- Supports manual code entry and public verification with rate limiting and history logging.
"""

import os
import io
import hmac
import hashlib
import secrets
from datetime import datetime, date
from typing import Optional, Tuple, Dict, Any, List

import cv2
import numpy as np
import qrcode
from PIL import Image

from modules.database import get_connection, utc_now_str, get_setting
from modules.auth_service import check_rate_limit

_QR_HMAC_KEY = os.environ.get("SMART_NIC_QR_KEY", "smart-nic-qr-verification-hmac-secret-2026").encode("utf-8")


def generate_verification_credential(nic_number: str) -> Tuple[str, str]:
    """
    Generate a cryptographically random opaque verification token and its HMAC-SHA256 signature.
    Returns (verification_token, token_signature).
    """
    token = secrets.token_urlsafe(18)  # 144 bits of entropy, compact for fast QR scanning
    sig = compute_token_signature(nic_number, token)
    return token, sig


def compute_token_signature(nic_number: str, token: str) -> str:
    """Compute truncated HMAC-SHA256 signature binding NIC number and random token."""
    msg = f"{nic_number}|{token}".encode("utf-8")
    return hmac.new(_QR_HMAC_KEY, msg, hashlib.sha256).hexdigest()[:20]


def build_qr_payload(verification_token: str, token_signature: str) -> str:
    """
    Build the opaque QR string.
    Contains NO personal data (no name, DOB, address, email, or phone).
    """
    return f"SNICV1|{verification_token}|{token_signature}"


def generate_qr_image(verification_token: str, token_signature: str, box_size: int = 8, border: int = 2) -> Image.Image:
    """Generate a high-contrast PIL QR code image for the signed verification credential."""
    payload = build_qr_payload(verification_token, token_signature)
    qr = qrcode.QRCode(
        version=None,
        error_correction=qrcode.constants.ERROR_CORRECT_M,
        box_size=box_size,
        border=border,
    )
    qr.add_data(payload)
    qr.make(fit=True)
    return qr.make_image(fill_color="#0F172A", back_color="#FFFFFF").convert("RGB")


def decode_qr_from_image_bytes(image_bytes: bytes) -> Tuple[bool, str, Optional[str]]:
    """
    Decode QR code from raw image bytes (camera frame or uploaded PNG/JPG) using OpenCV.
    Returns (found, message, decoded_text).
    """
    if not image_bytes:
        return False, "No image data provided.", None
    try:
        arr = np.frombuffer(image_bytes, dtype=np.uint8)
        img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
        if img is None:
            return False, "Unable to decode image file.", None

        detector = cv2.QRCodeDetector()
        data, _, _ = detector.detectAndDecode(img)
        if data:
            return True, "QR code decoded successfully.", data.strip()

        # Retry on grayscale with adaptive contrast if first pass missed
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        data, _, _ = detector.detectAndDecode(gray)
        if data:
            return True, "QR code decoded successfully.", data.strip()

        return False, "No readable QR code detected in the image. Ensure clear lighting and focus.", None
    except Exception as e:
        return False, f"QR decoding error: {e}", None


def _log_verification(
    card_id: Optional[int],
    nic_queried: str,
    token_fp: str,
    method: str,
    result: str,
    verifier_info: str = "Public Verification Portal",
) -> None:
    """Persist every verification attempt into card_verifications."""
    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO card_verifications (card_id, nic_number_queried, token_fingerprint, method, result, verifier_info, verified_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (card_id, nic_queried, token_fp, method, result, verifier_info, utc_now_str()),
        )
        conn.commit()


def verify_credential(
    code_or_payload: str,
    method: str = "MANUAL_CODE",
    verifier_info: str = "Public Portal",
    rate_limit_key: str = "public_verify",
) -> Dict[str, Any]:
    """
    Verify either:
      1) A signed QR payload: 'SNICV1|<token>|<sig>'
      2) A manual NIC number: 'SNIC-YYYY-XXXXXX'
      3) A raw verification token

    Returns a strictly minimal, privacy-preserving verification response with status:
      VALID | EXPIRED | REVOKED | INVALID | NOT FOUND
    Never returns sensitive PII (address, email, mobile, password, or secret tokens).
    """
    max_rpm = int(get_setting("rate_limit_verifications_per_min", "30") or 30)
    allowed, _ = check_rate_limit(f"qr:{rate_limit_key}", max_requests=max_rpm, window_seconds=60)
    if not allowed:
        return {
            "result": "INVALID",
            "message": "Rate limit exceeded. Please wait a minute before trying again.",
            "limited_info": None,
        }

    raw = (code_or_payload or "").strip()
    if not raw:
        return {"result": "INVALID", "message": "Verification code is empty.", "limited_info": None}

    method_clean = method if method in ("QR_SCAN", "MANUAL_CODE", "API") else "MANUAL_CODE"
    token_fp = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:12]

    is_signed_payload = raw.startswith("SNICV1|")
    card_row = None

    with get_connection() as conn:
        if is_signed_payload:
            parts = raw.split("|")
            if len(parts) != 3:
                _log_verification(None, "", token_fp, method_clean, "INVALID", verifier_info)
                return {"result": "INVALID", "message": "Malformed QR verification credential.", "limited_info": None}

            _, token, sig = parts
            card_row = conn.execute(
                """
                SELECT ic.*, c.full_name, c.photo_path, c.account_status AS citizen_status
                FROM identity_cards ic
                JOIN citizens c ON ic.citizen_id = c.id
                WHERE ic.verification_token = ?
                """,
                (token,),
            ).fetchone()

            if not card_row:
                _log_verification(None, "", token_fp, method_clean, "NOT FOUND", verifier_info)
                return {"result": "NOT FOUND", "message": "No Smart NIC record matches this verification token.", "limited_info": None}

            # Verify cryptographic HMAC signature (detects forged/tampered QR)
            expected_sig = compute_token_signature(card_row["nic_number"], token)
            if not hmac.compare_digest(sig, expected_sig) or not hmac.compare_digest(sig, card_row["token_signature"]):
                _log_verification(card_row["id"], card_row["nic_number"], token_fp, method_clean, "INVALID", verifier_info)
                return {"result": "INVALID", "message": "Cryptographic credential signature failed verification.", "limited_info": None}
        else:
            # Manual entry: match by NIC number OR raw verification token
            card_row = conn.execute(
                """
                SELECT ic.*, c.full_name, c.photo_path, c.account_status AS citizen_status
                FROM identity_cards ic
                JOIN citizens c ON ic.citizen_id = c.id
                WHERE UPPER(ic.nic_number) = UPPER(?) OR ic.verification_token = ?
                """,
                (raw, raw),
            ).fetchone()

            if not card_row:
                _log_verification(None, raw[:32], token_fp, method_clean, "NOT FOUND", verifier_info)
                return {"result": "NOT FOUND", "message": "No issued Smart NIC found for the entered code.", "limited_info": None}

        # Evaluate lifecycle status & expiry date
        card_id = card_row["id"]
        nic_num = card_row["nic_number"]
        status = card_row["status"]
        expiry_str = card_row["expiry_date"]
        is_past_expiry = False
        try:
            exp_date = datetime.strptime(expiry_str, "%Y-%m-%d").date()
            if exp_date < date.today():
                is_past_expiry = True
        except ValueError:
            pass

        if status == "REVOKED":
            result = "REVOKED"
            msg = "This Smart NIC has been REVOKED and is no longer valid."
        elif status == "EXPIRED" or is_past_expiry:
            result = "EXPIRED"
            msg = f"This Smart NIC EXPIRED on {expiry_str}."
            if status == "ACTIVE" and is_past_expiry:
                conn.execute("UPDATE identity_cards SET status = 'EXPIRED' WHERE id = ?", (card_id,))
                conn.commit()
                status = "EXPIRED"
        elif status == "INACTIVE" or card_row["citizen_status"] != "ACTIVE":
            result = "INVALID"
            msg = "This Smart NIC or citizen account is currently INACTIVE."
        else:
            result = "VALID"
            msg = "Smart NIC credential is authentic and currently ACTIVE."

    _log_verification(card_id, nic_num, token_fp, method_clean, result, verifier_info)

    # Strictly minimal public disclosure (no email, phone, address, or secret tokens)
    limited_info = {
        "nic_number": nic_num,
        "full_name": card_row["full_name"],
        "card_status": status,
        "issue_date": card_row["issue_date"],
        "expiry_date": expiry_str,
        "photo_path": card_row["photo_path"] if result == "VALID" else "",
        "verification_timestamp": utc_now_str(),
        "demo_notice": "Academic Prototype Verification Only",
    }

    return {
        "result": result,
        "message": msg,
        "limited_info": limited_info,
    }


def list_verifications(limit: int = 100, citizen_id: Optional[int] = None) -> List[Dict[str, Any]]:
    """Return verification log history (optionally filtered to a specific citizen's cards)."""
    with get_connection() as conn:
        if citizen_id is not None:
            rows = conn.execute(
                """
                SELECT cv.id, cv.nic_number_queried, cv.method, cv.result, cv.verifier_info, cv.verified_at
                FROM card_verifications cv
                JOIN identity_cards ic ON cv.card_id = ic.id
                WHERE ic.citizen_id = ?
                ORDER BY cv.verified_at DESC
                LIMIT ?
                """,
                (citizen_id, limit),
            ).fetchall()
        else:
            rows = conn.execute(
                """
                SELECT cv.id, cv.nic_number_queried, cv.method, cv.result, cv.verifier_info, cv.verified_at,
                       c.full_name AS citizen_name
                FROM card_verifications cv
                LEFT JOIN identity_cards ic ON cv.card_id = ic.id
                LEFT JOIN citizens c ON ic.citizen_id = c.id
                ORDER BY cv.verified_at DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [dict(r) for r in rows]

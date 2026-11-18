"""
FastAPI REST Backend for Smart NIC – National Identity Card Management and Verification System
Provides authenticated, role-protected REST API endpoints sharing the same SQLite database
and service modules as the Streamlit frontend.

Run locally: uvicorn api:app --reload --port 8000
"""

from contextlib import asynccontextmanager
from typing import Optional
from fastapi import FastAPI, Depends, HTTPException, Header, Query, status
from fastapi.responses import Response
from pydantic import BaseModel

from modules.database import init_db, get_all_settings, update_setting
from modules.auth_service import (
    authenticate_user, verify_signed_token, create_user, list_users, toggle_user_active
)
from modules.citizen_service import (
    register_citizen, list_citizens, get_citizen_by_id, update_citizen_profile,
    toggle_citizen_account_status, get_citizen_history
)
from modules.application_service import (
    list_applications, get_application_by_id, mark_under_review,
    approve_application, reject_application
)
from modules.card_service import (
    issue_card_for_citizen, list_cards, get_card_by_id, update_card_status,
    submit_renewal_request, list_renewal_requests, process_renewal_request,
    submit_replacement_request, list_replacement_requests, process_replacement_request
)
from modules.qr_service import verify_credential, list_verifications
from modules.card_renderer import generate_card_pdf_bytes
from modules.report_service import get_dashboard_metrics, get_report_dataframe, list_audit_logs, dataframe_to_csv_bytes
from utils.seed_data import seed_demo_data_if_empty

@asynccontextmanager
async def lifespan(_app: FastAPI):
    init_db()
    seed_demo_data_if_empty()
    yield


app = FastAPI(
    title="Smart NIC – National Identity Card Management & Verification API",
    description="Academic Prototype REST API for Citizen Registration, Smart NIC Issuance, and QR Verification.",
    version="1.0.0",
    lifespan=lifespan,
)


# -----------------------------------------------------------------------------
# AUTHENTICATION & AUTHORIZATION DEPENDENCIES
# -----------------------------------------------------------------------------
def get_current_user(authorization: Optional[str] = Header(default=None)):
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing or invalid Bearer token.")
    token = authorization.split(" ", 1)[1].strip()
    user = verify_signed_token(token)
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired authentication token.")
    return user


def require_admin(user=Depends(get_current_user)):
    if user.get("role") != "admin":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Administrator privileges required.")
    return user


# -----------------------------------------------------------------------------
# PYDANTIC SCHEMAS
# -----------------------------------------------------------------------------
class LoginRequest(BaseModel):
    username: str
    password: str
    role: Optional[str] = None


class CitizenRegisterRequest(BaseModel):
    full_name: str
    date_of_birth: str
    gender: str
    email: str
    mobile_number: str
    residential_address: str
    city: str
    state: str
    postal_code: str
    blood_group: Optional[str] = "Unknown"
    supporting_doc_ref: Optional[str] = ""
    portal_password: Optional[str] = None


class CitizenUpdateRequest(BaseModel):
    full_name: Optional[str] = None
    date_of_birth: Optional[str] = None
    gender: Optional[str] = None
    email: Optional[str] = None
    mobile_number: Optional[str] = None
    residential_address: Optional[str] = None
    city: Optional[str] = None
    state: Optional[str] = None
    postal_code: Optional[str] = None
    blood_group: Optional[str] = None
    supporting_doc_ref: Optional[str] = None


class StatusToggleRequest(BaseModel):
    status: str
    reason: Optional[str] = ""


class ApplicationReviewRequest(BaseModel):
    notes: Optional[str] = ""
    issue_card: Optional[bool] = True


class ApplicationRejectRequest(BaseModel):
    rejection_reason: str


class IssueCardRequest(BaseModel):
    citizen_id: int
    application_id: Optional[int] = None
    validity_years: Optional[int] = None


class VerifyRequest(BaseModel):
    code: str
    method: Optional[str] = "API"
    verifier_info: Optional[str] = "REST API Client"


class RenewalCreateRequest(BaseModel):
    citizen_id: int
    card_id: int
    reason: str


class ReplacementCreateRequest(BaseModel):
    citizen_id: int
    card_id: int
    request_type: str  # LOST or DAMAGED
    incident_details: str


class RequestDecisionBody(BaseModel):
    approve: bool
    admin_notes: Optional[str] = ""


class CreateUserBody(BaseModel):
    username: str
    email: str
    full_name: str
    password: str
    role: str = "admin"


# -----------------------------------------------------------------------------
# HEALTH & AUTH ENDPOINTS
# -----------------------------------------------------------------------------
@app.get("/api/health")
def health_check():
    return {"status": "ok", "service": "Smart NIC Identity Management API"}


@app.post("/api/auth/login")
def api_login(body: LoginRequest):
    ok, msg, user = authenticate_user(body.username, body.password, expected_role=body.role)
    if not ok:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=msg)
    return {"success": True, "message": msg, "user": user}


@app.get("/api/auth/me")
def api_me(user=Depends(get_current_user)):
    return {"success": True, "user": user}


# -----------------------------------------------------------------------------
# PUBLIC QR VERIFICATION ENDPOINT (NO ADMIN LOGIN REQUIRED)
# -----------------------------------------------------------------------------
@app.post("/api/verify")
def api_verify_card(body: VerifyRequest):
    res = verify_credential(body.code, method=body.method or "API", verifier_info=body.verifier_info or "REST API")
    return {"success": True, **res}


# -----------------------------------------------------------------------------
# CITIZEN ENDPOINTS
# -----------------------------------------------------------------------------
@app.post("/api/citizens/register", status_code=status.HTTP_201_CREATED)
def api_register_citizen(body: CitizenRegisterRequest):
    ok, msg, data = register_citizen(body.model_dump(), portal_password=body.portal_password)
    if not ok:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=msg)
    return {"success": True, "message": msg, "data": data}


@app.get("/api/citizens")
def api_list_citizens(
    search: str = "",
    status_filter: str = "ALL",
    gender_filter: str = "ALL",
    admin=Depends(require_admin),
):
    rows = list_citizens(search=search, status_filter=status_filter, gender_filter=gender_filter)
    return {"success": True, "count": len(rows), "citizens": rows}


@app.get("/api/citizens/{citizen_id}")
def api_get_citizen(citizen_id: int, user=Depends(get_current_user)):
    if user["role"] == "citizen" and user.get("citizen_id") != citizen_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied: You may only view your own record.")
    cit = get_citizen_by_id(citizen_id)
    if not cit:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Citizen not found.")
    history = get_citizen_history(citizen_id)
    # Strip secret tokens from cards list in API response
    safe_cards = [{k: v for k, v in c.items() if k not in ("verification_token", "token_signature")} for c in history["cards"]]
    history["cards"] = safe_cards
    return {"success": True, "citizen": cit, "history": history}


@app.put("/api/citizens/{citizen_id}")
def api_update_citizen(citizen_id: int, body: CitizenUpdateRequest, user=Depends(get_current_user)):
    is_self = user["role"] == "citizen"
    if is_self and user.get("citizen_id") != citizen_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied.")
    ok, msg = update_citizen_profile(
        citizen_id, body.model_dump(exclude_none=True), actor=user, citizen_self_service=is_self
    )
    if not ok:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=msg)
    return {"success": True, "message": msg}


@app.patch("/api/citizens/{citizen_id}/status")
def api_toggle_citizen_status(citizen_id: int, body: StatusToggleRequest, admin=Depends(require_admin)):
    ok, msg = toggle_citizen_account_status(citizen_id, body.status, admin)
    if not ok:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=msg)
    return {"success": True, "message": msg}


# -----------------------------------------------------------------------------
# APPLICATION ENDPOINTS
# -----------------------------------------------------------------------------
@app.get("/api/applications")
def api_list_applications(status_filter: str = "ALL", search: str = "", user=Depends(get_current_user)):
    cid = user.get("citizen_id") if user["role"] == "citizen" else None
    rows = list_applications(status_filter=status_filter, search=search, citizen_id=cid)
    return {"success": True, "count": len(rows), "applications": rows}


@app.post("/api/applications/{app_id}/review")
def api_review_application(app_id: int, body: ApplicationReviewRequest, admin=Depends(require_admin)):
    ok, msg = mark_under_review(app_id, admin, notes=body.notes or "")
    if not ok:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=msg)
    return {"success": True, "message": msg}


@app.post("/api/applications/{app_id}/approve")
def api_approve_application(app_id: int, body: ApplicationReviewRequest, admin=Depends(require_admin)):
    ok, msg, card = approve_application(app_id, admin, issue_card_immediately=bool(body.issue_card), notes=body.notes or "")
    if not ok:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=msg)
    return {"success": True, "message": msg, "card": card}


@app.post("/api/applications/{app_id}/reject")
def api_reject_application(app_id: int, body: ApplicationRejectRequest, admin=Depends(require_admin)):
    ok, msg = reject_application(app_id, body.rejection_reason, admin)
    if not ok:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=msg)
    return {"success": True, "message": msg}


# -----------------------------------------------------------------------------
# IDENTITY CARD ENDPOINTS
# -----------------------------------------------------------------------------
@app.get("/api/cards")
def api_list_cards(search: str = "", status_filter: str = "ALL", user=Depends(get_current_user)):
    cid = user.get("citizen_id") if user["role"] == "citizen" else None
    rows = list_cards(search=search, status_filter=status_filter, citizen_id=cid)
    safe = [{k: v for k, v in r.items() if k not in ("verification_token", "token_signature")} for r in rows]
    return {"success": True, "count": len(safe), "cards": safe}


@app.post("/api/cards/issue", status_code=status.HTTP_201_CREATED)
def api_issue_card(body: IssueCardRequest, admin=Depends(require_admin)):
    ok, msg, card = issue_card_for_citizen(body.citizen_id, admin, application_id=body.application_id, validity_years=body.validity_years)
    if not ok:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=msg)
    return {"success": True, "message": msg, "card": card}


@app.patch("/api/cards/{card_id}/status")
def api_update_card_status(card_id: int, body: StatusToggleRequest, admin=Depends(require_admin)):
    ok, msg = update_card_status(card_id, body.status, admin, reason=body.reason or "")
    if not ok:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=msg)
    return {"success": True, "message": msg}


@app.get("/api/cards/{card_id}/pdf")
def api_download_card_pdf(card_id: int, user=Depends(get_current_user)):
    card = get_card_by_id(card_id)
    if not card:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Card not found.")
    if user["role"] == "citizen" and card["citizen_id"] != user.get("citizen_id"):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied.")
    pdf_bytes = generate_card_pdf_bytes(card)
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f"attachment; filename={card['nic_number']}.pdf"},
    )


# -----------------------------------------------------------------------------
# RENEWAL & REPLACEMENT ENDPOINTS
# -----------------------------------------------------------------------------
@app.get("/api/renewals")
def api_list_renewals(status_filter: str = "ALL", user=Depends(get_current_user)):
    cid = user.get("citizen_id") if user["role"] == "citizen" else None
    return {"success": True, "renewals": list_renewal_requests(status_filter=status_filter, citizen_id=cid)}


@app.post("/api/renewals", status_code=status.HTTP_201_CREATED)
def api_create_renewal(body: RenewalCreateRequest, user=Depends(get_current_user)):
    ok, msg, code = submit_renewal_request(body.citizen_id, body.card_id, body.reason, user)
    if not ok:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=msg)
    return {"success": True, "message": msg, "request_code": code}


@app.post("/api/renewals/{request_id}/decision")
def api_decide_renewal(request_id: int, body: RequestDecisionBody, admin=Depends(require_admin)):
    ok, msg = process_renewal_request(request_id, body.approve, body.admin_notes or "", admin)
    if not ok:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=msg)
    return {"success": True, "message": msg}


@app.get("/api/replacements")
def api_list_replacements(status_filter: str = "ALL", user=Depends(get_current_user)):
    cid = user.get("citizen_id") if user["role"] == "citizen" else None
    return {"success": True, "replacements": list_replacement_requests(status_filter=status_filter, citizen_id=cid)}


@app.post("/api/replacements", status_code=status.HTTP_201_CREATED)
def api_create_replacement(body: ReplacementCreateRequest, user=Depends(get_current_user)):
    ok, msg, code = submit_replacement_request(body.citizen_id, body.card_id, body.request_type, body.incident_details, user)
    if not ok:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=msg)
    return {"success": True, "message": msg, "request_code": code}


@app.post("/api/replacements/{request_id}/decision")
def api_decide_replacement(request_id: int, body: RequestDecisionBody, admin=Depends(require_admin)):
    ok, msg = process_replacement_request(request_id, body.approve, body.admin_notes or "", admin)
    if not ok:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=msg)
    return {"success": True, "message": msg}


# -----------------------------------------------------------------------------
# REPORTS, AUDIT LOGS, USER MANAGEMENT & SETTINGS
# -----------------------------------------------------------------------------
@app.get("/api/reports/dashboard")
def api_dashboard_metrics(admin=Depends(require_admin)):
    m = get_dashboard_metrics()
    return {
        "success": True,
        "metrics": {
            "total_citizens": m["total_citizens"],
            "active_cards": m["active_cards"],
            "pending_apps": m["pending_apps"],
            "approved_apps": m["approved_apps"],
            "rejected_apps": m["rejected_apps"],
            "expired_cards": m["expired_cards"],
            "revoked_cards": m["revoked_cards"],
            "total_verifications": m["total_verifications"],
        },
    }


@app.get("/api/reports/{report_type}")
def api_get_report(
    report_type: str,
    start_date: Optional[str] = Query(default=None),
    end_date: Optional[str] = Query(default=None),
    export: str = Query(default="json"),
    admin=Depends(require_admin),
):
    df = get_report_dataframe(report_type, start_date=start_date, end_date=end_date)
    if export == "csv":
        return Response(
            content=dataframe_to_csv_bytes(df),
            media_type="text/csv",
            headers={"Content-Disposition": f"attachment; filename=smart_nic_{report_type}.csv"},
        )
    return {"success": True, "count": len(df), "records": df.to_dict(orient="records")}


@app.get("/api/audit-logs")
def api_audit_logs(action_filter: str = "ALL", search: str = "", limit: int = 100, admin=Depends(require_admin)):
    return {"success": True, "logs": list_audit_logs(action_filter=action_filter, search=search, limit=limit)}


@app.get("/api/users")
def api_list_users(role_filter: Optional[str] = None, admin=Depends(require_admin)):
    return {"success": True, "users": list_users(role_filter=role_filter)}


@app.post("/api/users", status_code=status.HTTP_201_CREATED)
def api_create_user(body: CreateUserBody, admin=Depends(require_admin)):
    ok, msg, uid = create_user(body.username, body.email, body.full_name, body.password, role=body.role, actor=admin)
    if not ok:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=msg)
    return {"success": True, "message": msg, "user_id": uid}


@app.patch("/api/users/{user_id}/status")
def api_toggle_user(user_id: int, is_active: bool, admin=Depends(require_admin)):
    ok, msg = toggle_user_active(user_id, is_active, admin)
    if not ok:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=msg)
    return {"success": True, "message": msg}


@app.get("/api/settings")
def api_get_settings(admin=Depends(require_admin)):
    return {"success": True, "settings": get_all_settings()}

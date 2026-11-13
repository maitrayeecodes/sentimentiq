from __future__ import annotations
import csv, io, os, uuid, zipfile, time, logging, json
from datetime import timezone, datetime, timedelta
from contextlib import asynccontextmanager
from collections import defaultdict, deque
from typing import Any

from fastapi import Depends, FastAPI, File, Form, Header, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, EmailStr, Field
import pandas as pd
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from sqlalchemy import select, text
from fastapi.responses import Response

from .security import create_access_token, decode_access_token, hash_password, verify_password
from .services.analyzer import analyze_reviews
from .storage import (SessionLocal, User, Workspace, Membership, ReportSchedule, ReportDelivery, AuditEvent, Analysis, init_db, get_user_by_email,
                      get_user_workspaces, user_has_workspace, save_analysis, get_analysis, list_analyses)
from .services.reporting import build_pdf_report, next_run
from .services.scheduler import start_scheduler, stop_scheduler, execute_schedule

@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    start_scheduler()
    try:
        yield
    finally:
        stop_scheduler()

app = FastAPI(title="SentimentIQ API", description="Workspace-scoped customer feedback analysis API.", version="1.0.0-rc1", lifespan=lifespan)
app.add_middleware(CORSMiddleware,
    allow_origins=[o.strip() for o in os.getenv("SENTIMENTIQ_CORS_ORIGINS", "http://127.0.0.1:5500,http://localhost:5500,http://localhost:3000,http://localhost:8080").split(",") if o.strip()],
    allow_credentials=False, allow_methods=["GET", "POST", "DELETE"], allow_headers=["Authorization", "Content-Type", "X-Workspace-ID"])
bearer = HTTPBearer(auto_error=False)
logger = logging.getLogger("sentimentiq.api")
_rate_buckets: dict[tuple[str, str], deque[float]] = defaultdict(deque)

@app.middleware("http")
async def security_and_rate_limit(request, call_next):
    path = request.url.path
    client_ip = request.client.host if request.client else "unknown"
    if path.startswith("/api/v1/auth/"):
        limit, window, bucket = 12, 60, "auth"
    elif path == "/api/v1/analyses" and request.method == "POST":
        limit, window, bucket = 12, 60, "upload"
    elif path.startswith("/api/"):
        limit, window, bucket = 240, 60, "api"
    else:
        limit, window, bucket = 600, 60, "general"
    now = time.monotonic()
    key = (client_ip, bucket)
    events = _rate_buckets[key]
    while events and now - events[0] >= window:
        events.popleft()
    # Starlette TestClient uses this reserved host; avoid cross-test shared counters.
    if client_ip == "testclient":
        response = await call_next(request)
    elif len(events) >= limit:
        from fastapi.responses import JSONResponse
        response = JSONResponse({"detail": "Rate limit exceeded. Please retry shortly."}, status_code=429,
                                headers={"Retry-After": str(max(1, int(window - (now - events[0]))) )})
    else:
        events.append(now)
        # Bound memory used by client/bucket keys during long-running processes.
        if len(_rate_buckets) > 10000:
            stale_before = now - window
            for old_key in list(_rate_buckets.keys())[:2000]:
                if not _rate_buckets[old_key] or _rate_buckets[old_key][-1] < stale_before:
                    _rate_buckets.pop(old_key, None)
        try:
            response = await call_next(request)
        except Exception:
            logger.exception("Unhandled request failure", extra={"path": path, "method": request.method})
            raise
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
    if path.startswith("/api/"):
        response.headers["Cache-Control"] = "no-store"
    return response

class RegisterInput(BaseModel):
    full_name: str = Field(min_length=2, max_length=120)
    email: EmailStr
    password: str = Field(min_length=10, max_length=128)
    workspace_name: str = Field(min_length=2, max_length=120)

class LoginInput(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=128)

class WorkspaceInput(BaseModel):
    name: str = Field(min_length=2, max_length=120)

class BenchmarkInput(BaseModel):
    analysis_ids: list[str] = Field(min_length=2, max_length=8)

class ReportScheduleInput(BaseModel):
    analysis_id: str = Field(min_length=1, max_length=36)
    recipient_email: EmailStr
    cadence: str = Field(pattern="^(weekly|monthly)$")
    hour_utc: int = Field(default=9, ge=0, le=23)
    day_of_week: int = Field(default=0, ge=0, le=6)
    day_of_month: int = Field(default=1, ge=1, le=28)
    negative_alert_threshold: float | None = Field(default=None, ge=0, le=100)



def db_session():
    db = SessionLocal()
    try: yield db
    finally: db.close()


def current_user(credentials: HTTPAuthorizationCredentials | None = Depends(bearer), db: Session = Depends(db_session)) -> User:
    if not credentials:
        raise HTTPException(status_code=401, detail="Sign in to continue", headers={"WWW-Authenticate": "Bearer"})
    user_id = decode_access_token(credentials.credentials)
    user = db.get(User, user_id)
    if not user or not user.is_active:
        raise HTTPException(status_code=401, detail="Account is unavailable")
    return user


def current_workspace(x_workspace_id: str | None = Header(default=None), user: User = Depends(current_user), db: Session = Depends(db_session)) -> str:
    if not x_workspace_id:
        workspaces = get_user_workspaces(db, user.id)
        if not workspaces: raise HTTPException(status_code=403, detail="No workspace is assigned to this account")
        return workspaces[0]["id"]
    if not user_has_workspace(db, user.id, x_workspace_id):
        raise HTTPException(status_code=404, detail="Workspace not found")
    return x_workspace_id


def utc_iso(value):
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat()


def user_payload(user: User) -> dict[str, str]:
    return {"id": user.id, "full_name": user.full_name, "email": user.email}


def auth_payload(db: Session, user: User) -> dict[str, Any]:
    workspaces = get_user_workspaces(db, user.id)
    return {"access_token": create_access_token(user.id), "token_type": "bearer", "user": user_payload(user), "workspaces": workspaces, "active_workspace_id": workspaces[0]["id"] if workspaces else None}

@app.get("/health")
def health() -> dict[str, str]:
    """Liveness probe: the API process is responding."""
    return {"status": "ok", "service": "sentimentiq-api", "version": app.version}


@app.get("/ready")
def readiness(db: Session = Depends(db_session)) -> dict[str, str]:
    """Readiness probe: the API can reach its configured database."""
    try:
        db.execute(text("SELECT 1"))
    except Exception as exc:
        logger.exception("Database readiness check failed")
        raise HTTPException(status_code=503, detail="Database is unavailable") from exc
    return {"status": "ready", "service": "sentimentiq-api", "database": "ok", "version": app.version}

@app.post("/api/v1/auth/register", status_code=201)
def register(payload: RegisterInput, db: Session = Depends(db_session)):
    email = payload.email.lower().strip()
    if get_user_by_email(db, email): raise HTTPException(status_code=409, detail="An account with this email already exists")
    user = User(id=str(uuid.uuid4()), email=email, full_name=payload.full_name.strip(), password_hash=hash_password(payload.password))
    workspace = Workspace(id=str(uuid.uuid4()), name=payload.workspace_name.strip())
    db.add_all([user, workspace]); db.flush()
    db.add(Membership(id=str(uuid.uuid4()), user_id=user.id, workspace_id=workspace.id, role="owner"))
    try: db.commit()
    except IntegrityError:
        db.rollback(); raise HTTPException(status_code=409, detail="An account with this email already exists")
    return auth_payload(db, user)

@app.post("/api/v1/auth/login")
def login(payload: LoginInput, db: Session = Depends(db_session)):
    user = get_user_by_email(db, payload.email)
    if not user or not verify_password(payload.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Email or password is incorrect")
    if not user.is_active: raise HTTPException(status_code=403, detail="This account has been disabled")
    return auth_payload(db, user)

@app.get("/api/v1/auth/me")
def me(user: User = Depends(current_user), db: Session = Depends(db_session)):
    return {"user": user_payload(user), "workspaces": get_user_workspaces(db, user.id)}

@app.get("/api/v1/workspaces")
def workspaces(user: User = Depends(current_user), db: Session = Depends(db_session)):
    return get_user_workspaces(db, user.id)

@app.post("/api/v1/workspaces", status_code=201)
def create_workspace(payload: WorkspaceInput, user: User = Depends(current_user), db: Session = Depends(db_session)):
    workspace = Workspace(id=str(uuid.uuid4()), name=payload.name.strip())
    db.add(workspace); db.flush()
    db.add(Membership(id=str(uuid.uuid4()), user_id=user.id, workspace_id=workspace.id, role="owner")); db.commit()
    return {"id": workspace.id, "name": workspace.name, "role": "owner"}

@app.post("/api/v1/analyses", status_code=201)
async def create_analysis(file: UploadFile = File(...), dataset_name: str = Form("Uploaded customer feedback"), user: User = Depends(current_user), workspace_id: str = Depends(current_workspace), db: Session = Depends(db_session)) -> dict[str, Any]:
    filename = (file.filename or "").lower()
    if filename.endswith(".csv"):
        file_type = "csv"
    elif filename.endswith(".xlsx"):
        file_type = "xlsx"
    else:
        raise HTTPException(status_code=415, detail="Supported formats are CSV (.csv) and Excel (.xlsx).")
    raw = await file.read(10 * 1024 * 1024 + 1)
    if not raw: raise HTTPException(status_code=400, detail="The uploaded file is empty.")
    if len(raw) > 10 * 1024 * 1024: raise HTTPException(status_code=413, detail="File exceeds the 10 MB limit.")
    try:
        if file_type == "csv":
            reader = csv.DictReader(io.StringIO(raw.decode("utf-8-sig")))
            if not reader.fieldnames: raise ValueError("CSV header row is missing")
            source_rows = list(reader)
            source_headers = {h.strip().lower().replace(" ", "_"): h for h in reader.fieldnames if h}
        else:
            with zipfile.ZipFile(io.BytesIO(raw)) as workbook_zip:
                expanded_size = sum(info.file_size for info in workbook_zip.infolist())
                if expanded_size > 100 * 1024 * 1024:
                    raise HTTPException(status_code=413, detail="Excel workbook expands beyond the 100 MB processing limit.")
            frame = pd.read_excel(io.BytesIO(raw), engine="openpyxl", dtype=object, nrows=20001)
            frame = frame.where(pd.notna(frame), None)
            source_rows = frame.to_dict(orient="records")
            source_headers = {str(h).strip().lower().replace(" ", "_"): h for h in frame.columns if h is not None}
        if len(source_rows) > 20000:
            raise HTTPException(status_code=413, detail="A single upload can contain at most 20,000 review rows.")
        review_col = next((source_headers[k] for k in ("review_text", "review", "text", "comment", "feedback") if k in source_headers), None)
        if not review_col: raise HTTPException(status_code=422, detail="File must contain a review_text, review, text, comment or feedback column.")
        if not source_rows: raise HTTPException(status_code=422, detail="The file contains a header but no review rows.")
        def cell(row, *keys):
            key = next((source_headers[k] for k in keys if k in source_headers), None)
            value = row.get(key) if key else None
            if hasattr(value, "isoformat"):
                return value.isoformat()
            return "" if value is None else str(value)
        mapped = [{
            "review_text": cell(r, "review_text", "review", "text", "comment", "feedback"),
            "review_id": cell(r, "review_id", "id"),
            "rating": cell(r, "rating", "stars"),
            "date": cell(r, "date", "created_at"),
            "category": cell(r, "category", "product_category"),
            "expected_sentiment": cell(r, "expected_sentiment", "label", "ground_truth_sentiment"),
        } for r in source_rows]
        from starlette.concurrency import run_in_threadpool
        result = await run_in_threadpool(analyze_reviews, mapped)
        if result["total_reviews"] == 0: raise HTTPException(status_code=422, detail="No non-empty review text values were found.")
    except UnicodeDecodeError: raise HTTPException(status_code=400, detail="CSV must be UTF-8 encoded.")
    except HTTPException: raise
    except Exception as exc:
        detail = "Excel file could not be read. Ensure it is a valid .xlsx workbook with a header row." if file_type == "xlsx" else "CSV could not be parsed. Check its UTF-8 encoding and formatting."
        raise HTTPException(status_code=400, detail=detail) from exc
    analysis_id = str(uuid.uuid4()); safe_name = " ".join(dataset_name.split())[:120] or "Uploaded customer feedback"
    save_analysis(db, analysis_id, workspace_id, user.id, safe_name, result)
    return {"id": analysis_id, "workspace_id": workspace_id, "dataset_name": safe_name, **result}

@app.get("/api/v1/analyses")
def analyses(workspace_id: str = Depends(current_workspace), db: Session = Depends(db_session)):
    return list_analyses(db, workspace_id)

@app.get("/api/v1/analyses/{analysis_id}")
def analysis(analysis_id: str, workspace_id: str = Depends(current_workspace), db: Session = Depends(db_session)):
    result = get_analysis(db, analysis_id, workspace_id)
    if not result: raise HTTPException(status_code=404, detail="Analysis not found")
    return result


@app.delete("/api/v1/analyses/{analysis_id}", status_code=204)
def delete_analysis(analysis_id: str, user: User = Depends(current_user), workspace_id: str = Depends(current_workspace), db: Session = Depends(db_session)):
    item = db.scalar(select(Analysis).where(Analysis.id == analysis_id, Analysis.workspace_id == workspace_id))
    if not item:
        raise HTTPException(status_code=404, detail="Analysis not found")
    # Remove dependent records explicitly for consistent SQLite and PostgreSQL behavior.
    schedules = db.scalars(select(ReportSchedule).where(ReportSchedule.analysis_id == analysis_id)).all()
    for schedule in schedules:
        db.delete(schedule)
    deliveries = db.scalars(select(ReportDelivery).where(ReportDelivery.analysis_id == analysis_id)).all()
    for delivery in deliveries:
        db.delete(delivery)
    db.add(AuditEvent(id=str(uuid.uuid4()), workspace_id=workspace_id, actor_id=user.id,
        action="delete", resource_type="analysis", resource_id=analysis_id,
        details_json=json.dumps({"dataset_name": item.dataset_name})))
    db.delete(item)
    db.commit()
    return Response(status_code=204)


@app.get("/api/v1/audit-events")
def list_audit_events(user: User = Depends(current_user), workspace_id: str = Depends(current_workspace), db: Session = Depends(db_session)):
    membership = db.scalar(select(Membership).where(Membership.user_id == user.id, Membership.workspace_id == workspace_id))
    if not membership or membership.role != "owner":
        raise HTTPException(status_code=403, detail="Workspace owner permission required")
    rows = db.scalars(select(AuditEvent).where(AuditEvent.workspace_id == workspace_id).order_by(AuditEvent.created_at.desc()).limit(100)).all()
    return [{"id": x.id, "actor_id": x.actor_id, "action": x.action, "resource_type": x.resource_type,
             "resource_id": x.resource_id, "details": json.loads(x.details_json), "created_at": utc_iso(x.created_at)} for x in rows]


class RetentionPurgeInput(BaseModel):
    older_than_days: int = Field(ge=30, le=3650)
    confirm: bool = Field(default=False)


@app.post("/api/v1/data-retention/purge")
def purge_old_data(payload: RetentionPurgeInput, user: User = Depends(current_user), workspace_id: str = Depends(current_workspace), db: Session = Depends(db_session)):
    membership = db.scalar(select(Membership).where(Membership.user_id == user.id, Membership.workspace_id == workspace_id))
    if not membership or membership.role != "owner":
        raise HTTPException(status_code=403, detail="Workspace owner permission required")
    if not payload.confirm:
        raise HTTPException(status_code=400, detail="Set confirm=true to permanently delete old workspace data")
    cutoff = datetime.now(timezone.utc) - timedelta(days=payload.older_than_days)
    old = db.scalars(select(Analysis).where(Analysis.workspace_id == workspace_id, Analysis.created_at < cutoff)).all()
    deleted_ids = [x.id for x in old]
    for analysis_id in deleted_ids:
        schedules = db.scalars(select(ReportSchedule).where(ReportSchedule.analysis_id == analysis_id)).all()
        for schedule in schedules: db.delete(schedule)
        deliveries = db.scalars(select(ReportDelivery).where(ReportDelivery.analysis_id == analysis_id)).all()
        for delivery in deliveries: db.delete(delivery)
        db.delete(db.get(Analysis, analysis_id))
    if deleted_ids:
        db.add(AuditEvent(id=str(uuid.uuid4()), workspace_id=workspace_id, actor_id=user.id,
            action="retention_purge", resource_type="analysis", resource_id="bulk",
            details_json=json.dumps({"older_than_days": payload.older_than_days, "deleted_count": len(deleted_ids)})))
    db.commit()
    return {"deleted_analyses": len(deleted_ids), "cutoff_utc": cutoff.isoformat()}


@app.get("/api/v1/reports/{analysis_id}.pdf")
def download_report_pdf(analysis_id: str, workspace_id: str = Depends(current_workspace), db: Session = Depends(db_session)):
    item = get_analysis(db, analysis_id, workspace_id)
    if not item:
        raise HTTPException(status_code=404, detail="Analysis not found")
    pdf = build_pdf_report(item)
    filename = "sentimentiq-report.pdf"
    return Response(content=pdf, media_type="application/pdf", headers={"Content-Disposition": f'attachment; filename="{filename}"'})


@app.post("/api/v1/report-schedules", status_code=201)
def create_report_schedule(payload: ReportScheduleInput, user: User = Depends(current_user), workspace_id: str = Depends(current_workspace), db: Session = Depends(db_session)):
    if not get_analysis(db, payload.analysis_id, workspace_id):
        raise HTTPException(status_code=404, detail="Analysis not found in this workspace")
    run_at = next_run(payload.cadence, payload.hour_utc, payload.day_of_week, payload.day_of_month)
    schedule = ReportSchedule(id=str(uuid.uuid4()), workspace_id=workspace_id, created_by=user.id,
        analysis_id=payload.analysis_id, recipient_email=str(payload.recipient_email), cadence=payload.cadence,
        hour_utc=payload.hour_utc, day_of_week=payload.day_of_week, day_of_month=payload.day_of_month,
        negative_alert_threshold=payload.negative_alert_threshold, enabled=True, next_run_at=run_at)
    db.add(schedule); db.commit(); db.refresh(schedule)
    return {"id": schedule.id, "analysis_id": schedule.analysis_id, "recipient_email": schedule.recipient_email,
        "cadence": schedule.cadence, "hour_utc": schedule.hour_utc, "day_of_week": schedule.day_of_week,
        "day_of_month": schedule.day_of_month, "negative_alert_threshold": schedule.negative_alert_threshold,
        "enabled": schedule.enabled, "next_run_at": utc_iso(schedule.next_run_at), "last_status": schedule.last_status}


@app.get("/api/v1/report-schedules")
def list_report_schedules(workspace_id: str = Depends(current_workspace), db: Session = Depends(db_session)):
    rows = db.scalars(select(ReportSchedule).where(ReportSchedule.workspace_id == workspace_id).order_by(ReportSchedule.created_at.desc())).all()
    return [{"id": x.id, "analysis_id": x.analysis_id, "recipient_email": x.recipient_email, "cadence": x.cadence,
        "hour_utc": x.hour_utc, "day_of_week": x.day_of_week, "day_of_month": x.day_of_month,
        "negative_alert_threshold": x.negative_alert_threshold, "enabled": x.enabled,
        "next_run_at": utc_iso(x.next_run_at), "last_run_at": utc_iso(x.last_run_at),
        "last_status": x.last_status} for x in rows]


@app.delete("/api/v1/report-schedules/{schedule_id}", status_code=204)
def delete_report_schedule(schedule_id: str, workspace_id: str = Depends(current_workspace), db: Session = Depends(db_session)):
    schedule = db.scalar(select(ReportSchedule).where(ReportSchedule.id == schedule_id, ReportSchedule.workspace_id == workspace_id))
    if not schedule:
        raise HTTPException(status_code=404, detail="Report schedule not found")
    db.delete(schedule); db.commit()
    return Response(status_code=204)


@app.post("/api/v1/report-schedules/{schedule_id}/run")
def run_report_schedule_now(schedule_id: str, workspace_id: str = Depends(current_workspace), db: Session = Depends(db_session)):
    schedule = db.scalar(select(ReportSchedule).where(ReportSchedule.id == schedule_id, ReportSchedule.workspace_id == workspace_id))
    if not schedule:
        raise HTTPException(status_code=404, detail="Report schedule not found")
    delivery = execute_schedule(db, schedule)
    return {"id": delivery.id, "status": delivery.status, "recipient_email": delivery.recipient_email,
        "error_message": delivery.error_message, "download_url": f"/api/v1/report-deliveries/{delivery.id}.pdf"}


@app.get("/api/v1/report-deliveries")
def list_report_deliveries(workspace_id: str = Depends(current_workspace), db: Session = Depends(db_session)):
    rows = db.scalars(select(ReportDelivery).where(ReportDelivery.workspace_id == workspace_id).order_by(ReportDelivery.created_at.desc()).limit(50)).all()
    return [{"id": x.id, "analysis_id": x.analysis_id, "recipient_email": x.recipient_email, "status": x.status,
        "subject": x.subject, "error_message": x.error_message, "created_at": x.created_at.isoformat()} for x in rows]


@app.get("/api/v1/report-deliveries/{delivery_id}.pdf")
def download_report_delivery(delivery_id: str, workspace_id: str = Depends(current_workspace), db: Session = Depends(db_session)):
    delivery = db.scalar(select(ReportDelivery).where(ReportDelivery.id == delivery_id, ReportDelivery.workspace_id == workspace_id))
    if not delivery:
        raise HTTPException(status_code=404, detail="Report delivery not found")
    return Response(content=delivery.pdf_bytes, media_type="application/pdf", headers={"Content-Disposition": 'attachment; filename="sentimentiq-scheduled-report.pdf"'})


@app.post("/api/v1/competitive/benchmark")
def competitive_benchmark(payload: BenchmarkInput, workspace_id: str = Depends(current_workspace), db: Session = Depends(db_session)) -> dict[str, Any]:
    """Compare user-selected analysis runs within the authenticated workspace.

    Dataset names act as brand labels. This endpoint does not scrape or infer
    competitor data; each comparison must be based on uploaded review datasets.
    """
    if len(set(payload.analysis_ids)) != len(payload.analysis_ids):
        raise HTTPException(status_code=422, detail="Select each dataset only once.")
    datasets = []
    for analysis_id in payload.analysis_ids:
        item = get_analysis(db, analysis_id, workspace_id)
        if not item:
            raise HTTPException(status_code=404, detail="One or more selected datasets were not found in this workspace.")
        reviews = item.get("reviews", [])
        total = max(len(reviews), 1)
        counts = {label: sum(1 for r in reviews if r.get("sentiment") == label) for label in ("Positive", "Neutral", "Negative")}
        priority_count = sum(1 for r in reviews if (r.get("urgency") or {}).get("priority") in ("High", "Critical"))
        datasets.append({
            "analysis_id": item["id"], "brand": item["dataset_name"], "review_count": len(reviews),
            "sentiment": {label: {"count": counts[label], "percentage": round(counts[label] / total * 100, 1)} for label in counts},
            "net_sentiment": round((counts["Positive"] - counts["Negative"]) / total * 100, 1),
            "high_priority_count": priority_count, "high_priority_percentage": round(priority_count / total * 100, 1),
        })
    topic_rows: dict[str, dict[str, dict[str, int]]] = {}
    for item, summary in zip([get_analysis(db, aid, workspace_id) for aid in payload.analysis_ids], datasets):
        brand = summary["brand"]
        for review in item.get("reviews", []):
            for aspect in review.get("aspect_sentiments", []):
                topic = aspect.get("topic", "Other")
                bucket = topic_rows.setdefault(topic, {}).setdefault(brand, {"mentions": 0, "negative": 0, "positive": 0})
                bucket["mentions"] += 1
                if aspect.get("sentiment") == "Negative": bucket["negative"] += 1
                if aspect.get("sentiment") == "Positive": bucket["positive"] += 1
    topic_comparison = []
    for topic, brands in topic_rows.items():
        entries = []
        for brand, values in brands.items():
            entries.append({"brand": brand, **values, "negative_percentage": round(values["negative"] / max(values["mentions"], 1) * 100, 1)})
        topic_comparison.append({"topic": topic, "brands": entries})
    topic_comparison.sort(key=lambda x: sum(b["mentions"] for b in x["brands"]), reverse=True)
    ranked = sorted(datasets, key=lambda x: x["net_sentiment"], reverse=True)
    insights = []
    if ranked:
        insights.append({"type": "strength", "title": f"Highest net sentiment: {ranked[0]['brand']}", "evidence": f"{ranked[0]['net_sentiment']:+.1f} net sentiment points across {ranked[0]['review_count']} reviews."})
        weakest = ranked[-1]
        insights.append({"type": "attention", "title": f"Lowest net sentiment: {weakest['brand']}", "evidence": f"{weakest['net_sentiment']:+.1f} net sentiment points. Inspect its negative review evidence before drawing conclusions."})
    for topic in topic_comparison:
        ranked_topics = sorted((b for b in topic["brands"] if b["mentions"] >= 2), key=lambda b: b["negative_percentage"], reverse=True)
        if ranked_topics and len(ranked_topics) > 1:
            worst = ranked_topics[0]
            insights.append({"type": "attention", "title": f"{topic['topic']} needs review at {worst['brand']}", "evidence": f"{worst['negative_percentage']:.1f}% negative among {worst['mentions']} topic mentions. Small samples should be treated cautiously."})
    return {"workspace_id": workspace_id, "dataset_count": len(datasets), "datasets": datasets, "topic_comparison": topic_comparison, "insights": insights, "methodology": "Descriptive comparison of uploaded datasets in this workspace. Net sentiment = positive share minus negative share. Topic negative share uses aspect-level labels. Dataset names are used as brand labels; this is not external market research, causal analysis, or a market-share estimate."}

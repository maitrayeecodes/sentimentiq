from __future__ import annotations

import threading
import uuid
from datetime import datetime, timezone
from sqlalchemy import select, text
from ..storage import engine

from ..storage import SessionLocal, ReportSchedule, ReportDelivery, Analysis, get_analysis
from .reporting import build_pdf_report, send_report_email, following_run

stop_event = threading.Event()
worker_thread: threading.Thread | None = None
_scheduler_lock_connection = None
_scheduler_lock_acquired = False


def execute_schedule(db, schedule: ReportSchedule) -> ReportDelivery:
    original = get_analysis(db, schedule.analysis_id, schedule.workspace_id)
    analysis = original
    if original:
        # A recurring subscription follows the newest run with the same dataset name.
        latest = db.scalar(select(Analysis).where(
            Analysis.workspace_id == schedule.workspace_id,
            Analysis.dataset_name == original.get("dataset_name"),
        ).order_by(Analysis.created_at.desc()).limit(1))
        if latest:
            analysis = get_analysis(db, latest.id, schedule.workspace_id)
    if not analysis:
        pdf = build_pdf_report({"dataset_name": "Unavailable dataset", "total_reviews": 0})
        sent, error = False, "The linked analysis no longer exists."
        subject = "SentimentIQ report unavailable"
    else:
        pdf = build_pdf_report(analysis)
        negative = (analysis.get("sentiment_distribution", {}).get("Negative", {}) or {}).get("percentage", 0)
        alert = schedule.negative_alert_threshold is not None and negative >= schedule.negative_alert_threshold
        prefix = "[Sentiment alert] " if alert else ""
        subject = f"{prefix}SentimentIQ report: {analysis.get('dataset_name', 'Customer feedback')}"
        sent, error = send_report_email(schedule.recipient_email, subject, pdf, analysis.get("dataset_name", "Customer feedback"))
    delivery = ReportDelivery(
        id=str(uuid.uuid4()), workspace_id=schedule.workspace_id, schedule_id=schedule.id,
        analysis_id=analysis.get("id", schedule.analysis_id) if analysis else schedule.analysis_id, recipient_email=schedule.recipient_email,
        status="sent" if sent else ("generated_not_sent" if error and "not configured" in error else "failed"),
        subject=subject, pdf_bytes=pdf, error_message=error,
    )
    db.add(delivery)
    now = datetime.now(timezone.utc)
    schedule.last_run_at = now
    schedule.last_status = delivery.status
    schedule.next_run_at = following_run(schedule, now)
    db.commit()
    db.refresh(delivery)
    return delivery


def run_due_schedules_once() -> int:
    db = SessionLocal()
    try:
        now = datetime.now(timezone.utc)
        due = db.scalars(select(ReportSchedule).where(ReportSchedule.enabled.is_(True), ReportSchedule.next_run_at <= now).order_by(ReportSchedule.next_run_at).limit(20)).all()
        count = 0
        for schedule in due:
            try:
                execute_schedule(db, schedule)
                count += 1
            except Exception:
                db.rollback()
                schedule = db.get(ReportSchedule, schedule.id)
                if schedule:
                    schedule.last_run_at = now
                    schedule.last_status = "failed"
                    schedule.next_run_at = following_run(schedule, now)
                    db.commit()
        return count
    finally:
        db.close()


def _worker() -> None:
    while not stop_event.is_set():
        run_due_schedules_once()
        stop_event.wait(60)


def start_scheduler() -> None:
    global worker_thread
    if worker_thread and worker_thread.is_alive():
        return
    stop_event.clear()
    worker_thread = threading.Thread(target=_worker, name="sentimentiq-report-scheduler", daemon=True)
    worker_thread.start()


def stop_scheduler() -> None:
    stop_event.set()
    if worker_thread and worker_thread.is_alive():
        worker_thread.join(timeout=3)

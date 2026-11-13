from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, create_engine, inspect, select, LargeBinary, Float, Index
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship, sessionmaker
from sqlalchemy.engine import make_url

DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    db_path = Path(os.getenv("SENTIMENTIQ_DB_PATH", Path(__file__).resolve().parents[1] / "data" / "sentimentiq.db"))
    db_path.parent.mkdir(parents=True, exist_ok=True)
    DATABASE_URL = f"sqlite:///{db_path.as_posix()}"

engine_kwargs: dict[str, Any] = {"pool_pre_ping": True}
if make_url(DATABASE_URL).get_backend_name() == "sqlite":
    engine_kwargs["connect_args"] = {"check_same_thread": False}
engine = create_engine(DATABASE_URL, **engine_kwargs)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)

class Base(DeclarativeBase):
    pass

class User(Base):
    __tablename__ = "users"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    email: Mapped[str] = mapped_column(String(320), unique=True, index=True, nullable=False)
    full_name: Mapped[str] = mapped_column(String(120), nullable=False)
    password_hash: Mapped[str] = mapped_column(String(512), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    memberships: Mapped[list["Membership"]] = relationship(back_populates="user", cascade="all, delete-orphan")

class Workspace(Base):
    __tablename__ = "workspaces"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    memberships: Mapped[list["Membership"]] = relationship(back_populates="workspace", cascade="all, delete-orphan")
    analyses: Mapped[list["Analysis"]] = relationship(back_populates="workspace", cascade="all, delete-orphan")

class Membership(Base):
    __tablename__ = "memberships"
    __table_args__ = (UniqueConstraint("user_id", "workspace_id", name="uq_membership_user_workspace"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), index=True)
    role: Mapped[str] = mapped_column(String(20), default="owner", nullable=False)
    user: Mapped[User] = relationship(back_populates="memberships")
    workspace: Mapped[Workspace] = relationship(back_populates="memberships")

class Analysis(Base):
    __tablename__ = "analyses"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), index=True, nullable=False)
    created_by: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    dataset_name: Mapped[str] = mapped_column(String(120), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), index=True)
    total_reviews: Mapped[int] = mapped_column(Integer, nullable=False)
    result_json: Mapped[str] = mapped_column(Text, nullable=False)
    workspace: Mapped[Workspace] = relationship(back_populates="analyses")


class ReportSchedule(Base):
    __tablename__ = "report_schedules"
    __table_args__ = (Index("ix_report_due", "enabled", "next_run_at"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), index=True, nullable=False)
    created_by: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    analysis_id: Mapped[str] = mapped_column(ForeignKey("analyses.id", ondelete="CASCADE"), nullable=False)
    recipient_email: Mapped[str] = mapped_column(String(320), nullable=False)
    cadence: Mapped[str] = mapped_column(String(16), nullable=False)
    hour_utc: Mapped[int] = mapped_column(Integer, default=9, nullable=False)
    day_of_week: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    day_of_month: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    negative_alert_threshold: Mapped[float | None] = mapped_column(Float, nullable=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    next_run_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True, nullable=False)
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_status: Mapped[str | None] = mapped_column(String(40), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


class AuditEvent(Base):
    __tablename__ = "audit_events"
    __table_args__ = (Index("ix_audit_workspace_created", "workspace_id", "created_at"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), index=True, nullable=False)
    actor_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    action: Mapped[str] = mapped_column(String(60), nullable=False)
    resource_type: Mapped[str] = mapped_column(String(60), nullable=False)
    resource_id: Mapped[str] = mapped_column(String(36), nullable=False)
    details_json: Mapped[str] = mapped_column(Text, default="{}", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), index=True)


class ReportDelivery(Base):
    __tablename__ = "report_deliveries"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), index=True, nullable=False)
    schedule_id: Mapped[str | None] = mapped_column(ForeignKey("report_schedules.id", ondelete="SET NULL"), nullable=True)
    analysis_id: Mapped[str] = mapped_column(ForeignKey("analyses.id", ondelete="CASCADE"), nullable=False)
    recipient_email: Mapped[str] = mapped_column(String(320), nullable=False)
    status: Mapped[str] = mapped_column(String(40), nullable=False)
    subject: Mapped[str] = mapped_column(String(240), nullable=False)
    pdf_bytes: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), index=True)


def init_db() -> None:
    # Preserve a pre-authentication Iteration 2 SQLite table for manual recovery.
    # Its rows cannot be safely assigned to a tenant without knowing their owner.
    inspector = inspect(engine)
    if inspector.has_table("analyses") and "workspace_id" not in {c["name"] for c in inspector.get_columns("analyses")}:
        with engine.begin() as conn:
            existing = inspect(conn)
            if not existing.has_table("legacy_analyses"):
                conn.exec_driver_sql("ALTER TABLE analyses RENAME TO legacy_analyses")
            else:
                conn.exec_driver_sql("DROP TABLE analyses")
    Base.metadata.create_all(bind=engine)


def get_user_by_email(db, email: str) -> User | None:
    return db.scalar(select(User).where(User.email == email.lower().strip()))


def get_user_workspaces(db, user_id: str) -> list[dict[str, Any]]:
    rows = db.execute(select(Workspace, Membership.role).join(Membership).where(Membership.user_id == user_id).order_by(Workspace.created_at)).all()
    return [{"id": w.id, "name": w.name, "role": role} for w, role in rows]


def user_has_workspace(db, user_id: str, workspace_id: str) -> bool:
    return db.scalar(select(Membership.id).where(Membership.user_id == user_id, Membership.workspace_id == workspace_id)) is not None


def save_analysis(db, analysis_id: str, workspace_id: str, user_id: str, dataset_name: str, result: dict[str, Any]) -> None:
    db.add(Analysis(id=analysis_id, workspace_id=workspace_id, created_by=user_id, dataset_name=dataset_name, total_reviews=result["total_reviews"], result_json=json.dumps(result)))
    db.commit()


def get_analysis(db, analysis_id: str, workspace_id: str) -> dict[str, Any] | None:
    row = db.scalar(select(Analysis).where(Analysis.id == analysis_id, Analysis.workspace_id == workspace_id))
    if not row:
        return None
    return {"id": row.id, "workspace_id": row.workspace_id, "dataset_name": row.dataset_name, "created_at": row.created_at.isoformat(), **json.loads(row.result_json)}


def list_analyses(db, workspace_id: str) -> list[dict[str, Any]]:
    rows = db.scalars(select(Analysis).where(Analysis.workspace_id == workspace_id).order_by(Analysis.created_at.desc())).all()
    return [{"id": r.id, "dataset_name": r.dataset_name, "created_at": r.created_at.isoformat(), "total_reviews": r.total_reviews} for r in rows]

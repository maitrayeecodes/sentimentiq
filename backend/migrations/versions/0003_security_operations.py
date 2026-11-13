"""Audit events and operational indexes."""
from alembic import op
from app.storage import AuditEvent

revision = "0003_security_operations"
down_revision = "0002_reporting"
branch_labels = None
depends_on = None

def upgrade():
    bind = op.get_bind()
    AuditEvent.__table__.create(bind=bind, checkfirst=True)
    op.create_index("ix_report_due", "report_schedules", ["enabled", "next_run_at"], if_not_exists=True)
    op.create_index("ix_audit_workspace_created", "audit_events", ["workspace_id", "created_at"], if_not_exists=True)

def downgrade():
    bind = op.get_bind()
    op.drop_index("ix_audit_workspace_created", table_name="audit_events", if_exists=True)
    op.drop_index("ix_report_due", table_name="report_schedules", if_exists=True)
    AuditEvent.__table__.drop(bind=bind, checkfirst=True)

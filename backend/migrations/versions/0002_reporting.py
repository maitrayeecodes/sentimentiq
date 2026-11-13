"""Scheduled report subscriptions and retained report deliveries."""
from alembic import op
from app.storage import ReportSchedule, ReportDelivery

revision = "0002_reporting"
down_revision = "0001_workspace_auth"
branch_labels = None
depends_on = None

def upgrade():
    bind = op.get_bind()
    ReportSchedule.__table__.create(bind=bind, checkfirst=True)
    ReportDelivery.__table__.create(bind=bind, checkfirst=True)

def downgrade():
    bind = op.get_bind()
    ReportDelivery.__table__.drop(bind=bind, checkfirst=True)
    ReportSchedule.__table__.drop(bind=bind, checkfirst=True)

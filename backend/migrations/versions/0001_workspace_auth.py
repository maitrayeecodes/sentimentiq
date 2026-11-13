"""Initial multi-tenant schema: users, workspaces, memberships, analyses."""
from alembic import op
from app.storage import User, Workspace, Membership, Analysis

revision = "0001_workspace_auth"
down_revision = None
branch_labels = None
depends_on = None

def upgrade():
    bind = op.get_bind()
    for model in (User, Workspace, Membership, Analysis):
        model.__table__.create(bind=bind, checkfirst=True)

def downgrade():
    bind = op.get_bind()
    for model in (Analysis, Membership, Workspace, User):
        model.__table__.drop(bind=bind, checkfirst=True)

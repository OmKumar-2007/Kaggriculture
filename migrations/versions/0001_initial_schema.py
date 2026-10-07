"""Initial shared arena schema.

Revision ID: 0001_initial_schema
"""
from alembic import op
from backend.services.storage import Base

revision="0001_initial_schema"
down_revision=None
branch_labels=None
depends_on=None

def upgrade():
    Base.metadata.create_all(bind=op.get_bind())

def downgrade():
    Base.metadata.drop_all(bind=op.get_bind())

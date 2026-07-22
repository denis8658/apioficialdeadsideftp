"""Initial multi-server schema for Phase 1 and reserved later-phase tables."""

from alembic import op

from app.db.base import Base
from app.db import models  # noqa: F401

revision = "0001_phase1"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    Base.metadata.create_all(bind=op.get_bind(), checkfirst=True)


def downgrade() -> None:
    Base.metadata.drop_all(bind=op.get_bind(), checkfirst=True)

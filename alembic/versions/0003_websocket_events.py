"""Persist WebSocket domain events and per-server sequences."""

from alembic import op
from app.db.base import Base
from app.db import models  # noqa: F401

revision = "0003_websocket_events"
down_revision = "0002_death_events_combat"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    Base.metadata.tables["server_event_sequences"].create(bind, checkfirst=True)
    Base.metadata.tables["domain_events"].create(bind, checkfirst=True)


def downgrade() -> None:
    bind = op.get_bind()
    Base.metadata.tables["domain_events"].drop(bind, checkfirst=True)
    Base.metadata.tables["server_event_sequences"].drop(bind, checkfirst=True)

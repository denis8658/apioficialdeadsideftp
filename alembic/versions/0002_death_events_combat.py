"""Add normalized combat fields to the reserved death_events table."""

from alembic import op
import sqlalchemy as sa

revision = "0002_death_events_combat"
down_revision = "0001_phase1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    columns = (
        sa.Column("event_time", sa.DateTime(timezone=True), nullable=True),
        sa.Column("event_type", sa.String(30), nullable=True),
        sa.Column("victim_id", sa.String(100), nullable=True),
        sa.Column("victim_name", sa.String(200), nullable=True),
        sa.Column("victim_type", sa.String(20), nullable=True),
        sa.Column("victim_platform", sa.String(20), nullable=True),
        sa.Column("killer_id", sa.String(100), nullable=True),
        sa.Column("killer_name", sa.String(200), nullable=True),
        sa.Column("killer_type", sa.String(20), nullable=True),
        sa.Column("killer_platform", sa.String(20), nullable=True),
        sa.Column("weapon_id", sa.String(200), nullable=True),
        sa.Column("weapon_name", sa.String(200), nullable=True),
        sa.Column("cause", sa.String(200), nullable=True),
        sa.Column("distance_meters", sa.Float(), nullable=True),
        sa.Column("is_player_kill", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("is_suicide", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("is_environmental", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("world_x", sa.Float(), nullable=True), sa.Column("world_y", sa.Float(), nullable=True), sa.Column("world_z", sa.Float(), nullable=True),
        sa.Column("map_x", sa.Float(), nullable=True), sa.Column("map_y", sa.Float(), nullable=True), sa.Column("grid", sa.String(20), nullable=True),
        sa.Column("source_file", sa.Text(), nullable=True), sa.Column("source_line", sa.Integer(), nullable=True),
        sa.Column("source_modified_at", sa.DateTime(timezone=True), nullable=True), sa.Column("fingerprint", sa.String(64), nullable=True),
    )
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_columns = {column["name"] for column in inspector.get_columns("death_events")}
    for column in columns:
        if column.name not in existing_columns:
            op.add_column("death_events", column)
    inspector = sa.inspect(bind)
    unique_names = {item.get("name") for item in inspector.get_unique_constraints("death_events")}
    if "uq_death_event_fingerprint" not in unique_names:
        if bind.dialect.name == "sqlite":
            with op.batch_alter_table("death_events") as batch:
                batch.create_unique_constraint("uq_death_event_fingerprint", ["server_id", "fingerprint"])
        else:
            op.create_unique_constraint("uq_death_event_fingerprint", "death_events", ["server_id", "fingerprint"])
    inspector = sa.inspect(bind)
    existing_indexes = {item["name"] for item in inspector.get_indexes("death_events")}
    wanted_indexes = {
        "ix_death_event_server_time": ["server_id", "event_time"],
        "ix_death_event_server_type": ["server_id", "event_type"],
        **{f"ix_death_events_{name}": [name] for name in ("killer_id", "killer_name", "victim_id", "victim_name", "weapon_name", "is_player_kill", "fingerprint")},
    }
    for name, fields in wanted_indexes.items():
        if name not in existing_indexes:
            op.create_index(name, "death_events", fields)


def downgrade() -> None:
    removing = {"fingerprint", "source_modified_at", "source_line", "source_file", "grid", "map_y", "map_x", "world_z", "world_y", "world_x", "is_environmental", "is_suicide", "is_player_kill", "distance_meters", "cause", "weapon_name", "weapon_id", "killer_platform", "killer_type", "killer_name", "killer_id", "victim_platform", "victim_type", "victim_name", "victim_id", "event_type", "event_time"}
    inspector = sa.inspect(op.get_bind())
    for index in inspector.get_indexes("death_events"):
        if removing.intersection(index.get("column_names") or ()):
            op.drop_index(index["name"], table_name="death_events")
    with op.batch_alter_table("death_events") as batch:
        batch.drop_constraint("uq_death_event_fingerprint", type_="unique")
        for name in removing:
            batch.drop_column(name)

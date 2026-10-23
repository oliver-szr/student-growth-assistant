"""Add two-level task organization without rewriting tasks or their references."""
from alembic import op
import sqlalchemy as sa

revision = "0002_task_hierarchy"
down_revision = "0001_baseline"
branch_labels = depends_on = None


def upgrade():
    # SQLite supports an additive nullable REFERENCES column with FK checking on.
    # Avoid batch table replacement: plans/history already reference task IDs.
    columns = {c["name"] for c in sa.inspect(op.get_bind()).get_columns("tasks")}
    if "task_kind" not in columns:
        op.execute("ALTER TABLE tasks ADD COLUMN task_kind VARCHAR(20) NOT NULL DEFAULT 'executable' CHECK (task_kind IN ('executable','container'))")
    if "sort_order" not in columns:
        op.execute("ALTER TABLE tasks ADD COLUMN sort_order INTEGER NOT NULL DEFAULT 0 CHECK (sort_order >= 0)")
    if "parent_task_id" not in columns:
        op.execute("ALTER TABLE tasks ADD COLUMN parent_task_id INTEGER REFERENCES tasks(id) ON DELETE RESTRICT CHECK (parent_task_id IS NULL OR (parent_task_id != id AND task_kind = 'executable'))")
    op.execute("CREATE INDEX IF NOT EXISTS ix_tasks_parent_task_id ON tasks(parent_task_id)")


def downgrade():
    raise RuntimeError("Destructive downgrade disabled; restore the pre-migration SQLite backup.")

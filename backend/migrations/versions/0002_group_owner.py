"""Add the creator-level group owner role.

Existing groups promote their recorded creator to the sole active owner. New
installs receive the enum/index in 0001; this migration remains idempotent so
it can also upgrade databases created by the original migration.
"""

from alembic import op

revision = "0002_group_owner"
down_revision = "0001_core_schema"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # PostgreSQL makes a newly added enum value visible only after the
    # transaction commits, hence the dedicated autocommit block.
    with op.get_context().autocommit_block():
        op.execute("ALTER TYPE group_role ADD VALUE IF NOT EXISTS 'owner'")

    op.execute(
        """
        UPDATE group_memberships AS membership
        SET role = 'owner'
        FROM groups
        WHERE membership.group_id = groups.id
          AND membership.user_id = groups.created_by_user_id
          AND membership.left_at IS NULL
        """
    )
    op.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS group_memberships_one_active_owner_idx
        ON group_memberships(group_id)
        WHERE role = 'owner' AND left_at IS NULL
        """
    )


def downgrade() -> None:
    # PostgreSQL cannot remove an enum value safely. Downgrade the data/index
    # only; the enum label is harmless and must remain for existing databases.
    op.execute("DROP INDEX IF EXISTS group_memberships_one_active_owner_idx")
    op.execute("UPDATE group_memberships SET role = 'admin' WHERE role = 'owner'")

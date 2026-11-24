"""Persist game payment tracking, its deadline and each participant's due time.

Before this, clients inferred "payment tracking on" from a non-empty
`payment_info`, so a game with tracking enabled but no payment details lost
the setting on reload, and the 1-7 day deadline was never stored
(docs/backend-schema.md, `games` and `game_participants`).

Existing games keep the behaviour they had: tracking is on when they carry
payment details or already have a paid participant.
"""

import sqlalchemy as sa
from alembic import op

revision = "0003_payment_tracking"
down_revision = "0002_group_owner"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "games",
        sa.Column(
            "payment_tracking_enabled",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
    )
    op.add_column("games", sa.Column("payment_deadline_days", sa.SmallInteger()))
    op.add_column(
        "game_participants",
        sa.Column("payment_due_at", sa.DateTime(timezone=True)),
    )

    op.execute(
        """
        UPDATE games
        SET payment_tracking_enabled = true
        WHERE payment_info <> ''
           OR EXISTS (
             SELECT 1 FROM game_participants AS participant
             WHERE participant.game_id = games.id AND participant.paid_at IS NOT NULL
           )
        """
    )

    op.create_check_constraint(
        "payment_deadline_range",
        "games",
        "payment_deadline_days IS NULL OR payment_deadline_days BETWEEN 1 AND 7",
    )
    # Payment details and a deadline only make sense while tracking is on.
    op.create_check_constraint(
        "payment_fields_require_tracking",
        "games",
        "payment_tracking_enabled"
        " OR (payment_deadline_days IS NULL AND payment_info = '')",
    )


def downgrade() -> None:
    op.drop_constraint("payment_fields_require_tracking", "games", type_="check")
    op.drop_constraint("payment_deadline_range", "games", type_="check")
    op.drop_column("game_participants", "payment_due_at")
    op.drop_column("games", "payment_deadline_days")
    op.drop_column("games", "payment_tracking_enabled")

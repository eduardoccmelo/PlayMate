"""Admin skill ballots (docs/backend-schema.md, `player_skill_votes`).

Each active admin holds at most one level ballot and one mobility ballot per
player. The profile's level/mobility is the half-up average of the current
ballots, recomputed on every vote.
"""

from alembic import op

revision = "0004_player_skill_votes"
down_revision = "0003_payment_tracking"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE TYPE player_skill_attribute AS ENUM ('level', 'mobility')")
    op.execute(
        """
        CREATE TABLE player_skill_votes (
          group_id uuid NOT NULL REFERENCES groups(id) ON DELETE CASCADE,
          player_id uuid NOT NULL REFERENCES player_profiles(id) ON DELETE CASCADE,
          admin_user_id uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
          attribute player_skill_attribute NOT NULL,
          value smallint NOT NULL,
          updated_at timestamptz NOT NULL DEFAULT now(),
          CONSTRAINT player_skill_votes_pkey
            PRIMARY KEY (group_id, player_id, admin_user_id, attribute),
          CONSTRAINT player_skill_votes_value_range_check CHECK (
            (attribute = 'level' AND value BETWEEN 1 AND 5)
            OR (attribute = 'mobility' AND value BETWEEN 1 AND 3)
          )
        )
        """
    )
    op.execute("CREATE INDEX player_skill_votes_player_idx ON player_skill_votes(player_id)")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS player_skill_votes")
    op.execute("DROP TYPE IF EXISTS player_skill_attribute")

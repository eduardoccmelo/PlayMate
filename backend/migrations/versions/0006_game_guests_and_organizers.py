"""Participant-created games and game-only guests.

- `games.created_by_role`: a participant may create a game and organizes
  only that game (docs/backend-schema.md, `created_by_role`). Existing games
  were all created by admins.
- `player_profiles.scope_game_id`: a manual guest added by a participant
  organizer belongs to that one game and stays out of the group-wide
  voting board (docs/app-flow.md).
"""

from alembic import op

revision = "0006_game_guests_and_organizers"
down_revision = "0005_team_balances"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE TYPE game_creator_role AS ENUM ('admin', 'participant')")
    op.execute(
        "ALTER TABLE games ADD COLUMN created_by_role game_creator_role"
        " NOT NULL DEFAULT 'admin'"
    )
    op.execute(
        "ALTER TABLE player_profiles ADD COLUMN scope_game_id uuid"
        " REFERENCES games(id) ON DELETE SET NULL"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE player_profiles DROP COLUMN IF EXISTS scope_game_id")
    op.execute("ALTER TABLE games DROP COLUMN IF EXISTS created_by_role")
    op.execute("DROP TYPE IF EXISTS game_creator_role")

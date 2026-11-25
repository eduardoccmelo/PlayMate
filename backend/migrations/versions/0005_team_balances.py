"""Server-side team balancing (docs/backend-schema.md, "Team-balance snapshots").

- `games.balance_window_*`: the final-rebalance window, opening 15 minutes
  before kickoff and closing at the game end. A reschedule moves it.
- `game_schedule_changes`: who moved a game and from when to when.
- `game_team_balances` / `game_team_balance_members`: every draw, its place
  in the 3 + 1 quota and the split it produced. At most one is active per
  game; the active split is mirrored on `game_participants.team`.

Members store their team as `team_side` (A/B) like `game_participants`,
and keep the balance signature they were drawn with, so a replacement with
an identical signature can inherit the place instead of invalidating it.
"""

from alembic import op

revision = "0005_team_balances"
down_revision = "0004_player_skill_votes"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE games
          ADD COLUMN balance_window_starts_at timestamptz,
          ADD COLUMN balance_window_ends_at timestamptz
        """
    )
    op.execute(
        """
        UPDATE games
        SET balance_window_starts_at = starts_at - interval '15 minutes',
            balance_window_ends_at = ends_at
        """
    )
    op.execute(
        """
        ALTER TABLE games
          ALTER COLUMN balance_window_starts_at SET NOT NULL,
          ALTER COLUMN balance_window_ends_at SET NOT NULL,
          ADD CONSTRAINT games_balance_window_order_check
            CHECK (balance_window_starts_at < balance_window_ends_at)
        """
    )

    op.execute(
        """
        CREATE TABLE game_schedule_changes (
          id uuid PRIMARY KEY,
          game_id uuid NOT NULL REFERENCES games(id) ON DELETE CASCADE,
          previous_starts_at timestamptz NOT NULL,
          current_starts_at timestamptz NOT NULL,
          changed_by_user_id uuid NOT NULL REFERENCES users(id),
          changed_at timestamptz NOT NULL DEFAULT now(),
          CONSTRAINT game_schedule_changes_moved_check
            CHECK (previous_starts_at <> current_starts_at)
        )
        """
    )
    op.execute(
        "CREATE INDEX game_schedule_changes_game_idx"
        " ON game_schedule_changes(game_id, changed_at DESC)"
    )

    op.execute("CREATE TYPE team_balance_trigger AS ENUM ('organizer', 'late_rebalance')")
    op.execute(
        """
        CREATE TABLE game_team_balances (
          id uuid PRIMARY KEY,
          game_id uuid NOT NULL REFERENCES games(id) ON DELETE CASCADE,
          trigger_type team_balance_trigger NOT NULL,
          triggered_by_user_id uuid NOT NULL REFERENCES users(id),
          window_opened_by_schedule_change_id uuid
            REFERENCES game_schedule_changes(id) ON DELETE SET NULL,
          standard_balance_number smallint
            CONSTRAINT game_team_balances_number_range_check
            CHECK (standard_balance_number BETWEEN 1 AND 3),
          algorithm_version text NOT NULL,
          team_a_score numeric(8,2) NOT NULL,
          team_b_score numeric(8,2) NOT NULL,
          generated_at timestamptz NOT NULL DEFAULT now(),
          invalidated_at timestamptz,
          CONSTRAINT game_team_balances_trigger_number_check CHECK (
            (trigger_type = 'organizer' AND standard_balance_number IS NOT NULL)
            OR (trigger_type = 'late_rebalance' AND standard_balance_number IS NULL)
          ),
          CONSTRAINT game_team_balances_window_source_check CHECK (
            window_opened_by_schedule_change_id IS NULL
            OR trigger_type = 'late_rebalance'
          )
        )
        """
    )
    op.execute(
        "CREATE UNIQUE INDEX game_team_balances_one_active_idx"
        " ON game_team_balances(game_id) WHERE invalidated_at IS NULL"
    )
    # The quota, enforced by the database as well as the service.
    op.execute(
        "CREATE UNIQUE INDEX game_team_balances_standard_number_idx"
        " ON game_team_balances(game_id, standard_balance_number)"
        " WHERE standard_balance_number IS NOT NULL"
    )
    op.execute(
        "CREATE UNIQUE INDEX game_team_balances_one_late_idx"
        " ON game_team_balances(game_id) WHERE trigger_type = 'late_rebalance'"
    )
    op.execute(
        """
        CREATE TABLE game_team_balance_members (
          team_balance_id uuid NOT NULL
            REFERENCES game_team_balances(id) ON DELETE CASCADE,
          participant_id uuid NOT NULL
            REFERENCES game_participants(id) ON DELETE CASCADE,
          team team_side NOT NULL,
          score_snapshot numeric(8,2) NOT NULL,
          signature text NOT NULL,
          CONSTRAINT game_team_balance_members_pkey
            PRIMARY KEY (team_balance_id, participant_id)
        )
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS game_team_balance_members")
    op.execute("DROP TABLE IF EXISTS game_team_balances")
    op.execute("DROP TYPE IF EXISTS team_balance_trigger")
    op.execute("DROP TABLE IF EXISTS game_schedule_changes")
    op.execute(
        """
        ALTER TABLE games
          DROP CONSTRAINT IF EXISTS games_balance_window_order_check,
          DROP COLUMN IF EXISTS balance_window_ends_at,
          DROP COLUMN IF EXISTS balance_window_starts_at
        """
    )

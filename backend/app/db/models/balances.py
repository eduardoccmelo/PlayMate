"""Team draws and game reschedules (migration 0005)."""

from datetime import datetime
from decimal import Decimal
from uuid import UUID, uuid4

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Numeric,
    PrimaryKeyConstraint,
    SmallInteger,
    Text,
    Uuid,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, created_at_column, pg_enum
from app.domain.enums import TeamBalanceTrigger, TeamSide


class GameScheduleChange(Base):
    __tablename__ = "game_schedule_changes"
    __table_args__ = (
        CheckConstraint("previous_starts_at <> current_starts_at", name="moved"),
        Index("game_schedule_changes_game_idx", "game_id", "changed_at"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    game_id: Mapped[UUID] = mapped_column(ForeignKey("games.id", ondelete="CASCADE"))
    previous_starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    current_starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    changed_by_user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"))
    changed_at: Mapped[datetime] = created_at_column()


class GameTeamBalance(Base):
    """One draw. At most one per game has `invalidated_at` NULL (the active
    split); the rest are history that still counts toward the quota."""

    __tablename__ = "game_team_balances"
    __table_args__ = (
        CheckConstraint("standard_balance_number BETWEEN 1 AND 3", name="number_range"),
        CheckConstraint(
            "(trigger_type = 'organizer' AND standard_balance_number IS NOT NULL)"
            " OR (trigger_type = 'late_rebalance' AND standard_balance_number IS NULL)",
            name="trigger_number",
        ),
        Index(
            "game_team_balances_one_active_idx",
            "game_id",
            unique=True,
            postgresql_where=text("invalidated_at IS NULL"),
        ),
        Index(
            "game_team_balances_standard_number_idx",
            "game_id",
            "standard_balance_number",
            unique=True,
            postgresql_where=text("standard_balance_number IS NOT NULL"),
        ),
        Index(
            "game_team_balances_one_late_idx",
            "game_id",
            unique=True,
            postgresql_where=text("trigger_type = 'late_rebalance'"),
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    game_id: Mapped[UUID] = mapped_column(ForeignKey("games.id", ondelete="CASCADE"))
    trigger_type: Mapped[TeamBalanceTrigger] = mapped_column(
        pg_enum(TeamBalanceTrigger, "team_balance_trigger")
    )
    triggered_by_user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"))
    window_opened_by_schedule_change_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("game_schedule_changes.id", ondelete="SET NULL")
    )
    standard_balance_number: Mapped[int | None] = mapped_column(SmallInteger)
    algorithm_version: Mapped[str] = mapped_column(Text)
    team_a_score: Mapped[Decimal] = mapped_column(Numeric(8, 2))
    team_b_score: Mapped[Decimal] = mapped_column(Numeric(8, 2))
    generated_at: Mapped[datetime] = created_at_column()
    invalidated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class GameTeamBalanceMember(Base):
    __tablename__ = "game_team_balance_members"
    __table_args__ = (
        PrimaryKeyConstraint(
            "team_balance_id", "participant_id", name="game_team_balance_members_pkey"
        ),
    )

    team_balance_id: Mapped[UUID] = mapped_column(
        ForeignKey("game_team_balances.id", ondelete="CASCADE")
    )
    participant_id: Mapped[UUID] = mapped_column(
        ForeignKey("game_participants.id", ondelete="CASCADE")
    )
    team: Mapped[TeamSide] = mapped_column(pg_enum(TeamSide, "team_side"))
    score_snapshot: Mapped[Decimal] = mapped_column(Numeric(8, 2))
    #: Position, effective level, mobility and condition at draw time.
    signature: Mapped[str] = mapped_column(Text)

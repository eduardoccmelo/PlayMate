from datetime import date, datetime, time
from decimal import Decimal
from uuid import UUID

from pydantic import Field

from app.domain.enums import (
    CancelReason,
    CurrencyCode,
    GameStatus,
    ParticipantStatus,
    TeamBalanceTrigger,
    TeamSide,
)
from app.schemas.common import CamelModel


class CreateGameRequest(CamelModel):
    game_date: date
    start_time: time
    duration_minutes: int = Field(gt=0)
    max_players: int = Field(ge=2)
    min_players: int | None = Field(default=None, ge=2)
    location: str = ""
    court_number: str = ""
    court_cost_cents: int = Field(default=0, ge=0)
    currency: CurrencyCode = CurrencyCode.EUR
    auto_cancellation_hours: int | None = Field(default=None, gt=0)
    payment_tracking_enabled: bool = False
    #: Days a newly listed player has to pay; requires payment tracking.
    payment_deadline_days: int | None = Field(default=None, ge=1, le=7)
    payment_info: str = ""
    player_notice: str = ""


class UpdateGameRequest(CamelModel):
    game_date: date | None = None
    start_time: time | None = None
    duration_minutes: int | None = Field(default=None, gt=0)
    max_players: int | None = Field(default=None, ge=2)
    min_players: int | None = Field(default=None, ge=2)
    location: str | None = None
    court_number: str | None = None
    court_cost_cents: int | None = Field(default=None, ge=0)
    payment_tracking_enabled: bool | None = None
    #: Send null to remove the deadline.
    payment_deadline_days: int | None = Field(default=None, ge=1, le=7)
    payment_info: str | None = None
    player_notice: str | None = None


class ParticipantResponse(CamelModel):
    id: UUID
    player_id: UUID
    #: The account that owns this entry; None for manual guests. Clients use
    #: this, never the display name, to find the viewer's own entry.
    user_id: UUID | None
    display_name: str
    status: ParticipantStatus
    list_position: int | None
    paid: bool
    payment_due_at: datetime | None
    team: TeamSide | None


class GameResponse(CamelModel):
    id: UUID
    group_id: UUID
    public_slug: str
    game_date: date
    start_time: time
    end_time: time | None
    duration_minutes: int
    starts_at: datetime
    ends_at: datetime
    location: str
    court_number: str
    court_cost_cents: int
    currency: CurrencyCode
    max_players: int
    min_players: int | None
    status: GameStatus
    cancel_reason: CancelReason | None
    payment_tracking_enabled: bool
    payment_deadline_days: int | None
    payment_info: str
    player_notice: str
    teams_drawn_at: datetime | None
    team_a_score: Decimal | None
    team_b_score: Decimal | None
    created_by_user_id: UUID


class ViewerAccessResponse(CamelModel):
    """§6.3 - every capability the viewer has, decided by the backend."""

    kind: str
    status: str | None
    can_view_details: bool
    can_view_group_players: bool
    can_join: bool
    can_leave: bool
    can_update_own_payment: bool
    can_draw_teams: bool
    can_manage_game: bool


class BalanceEntryResponse(CamelModel):
    trigger_type: TeamBalanceTrigger
    standard_balance_number: int | None
    generated_at: datetime
    #: Who drew; only sent to viewers who manage the game.
    triggered_by_name: str | None
    #: Who moved the game earlier, when that opened the final window early.
    rescheduled_by_name: str | None


class BalanceSummaryResponse(CamelModel):
    """The 3 + 1 quota and the final-rebalance window."""

    standard_count: int
    standard_limit: int
    late_rebalance_used: bool
    window_starts_at: datetime
    window_ends_at: datetime
    latest: BalanceEntryResponse | None


class ScheduleChangeResponse(CamelModel):
    previous_starts_at: datetime
    current_starts_at: datetime
    changed_at: datetime
    changed_by_name: str
    was_brought_forward: bool


class GameDetailResponse(CamelModel):
    game: GameResponse
    viewer_access: ViewerAccessResponse
    confirmed: list[ParticipantResponse]
    waiting_list: list[ParticipantResponse]
    balance: BalanceSummaryResponse
    last_schedule_change: ScheduleChangeResponse | None


class CreateGameResponse(CamelModel):
    game: GameResponse
    join_code: str


class JoinGameRequest(CamelModel):
    player_id: UUID | None = None
    display_name: str | None = None


class PaymentRequest(CamelModel):
    paid: bool


class ReorderRequest(CamelModel):
    status: ParticipantStatus
    ordered_ids: list[UUID]


class CancelGameRequest(CamelModel):
    reason: CancelReason = CancelReason.MANUAL

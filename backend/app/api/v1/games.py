from uuid import UUID

from fastapi import APIRouter
from sqlalchemy import select

from app.api.deps import (
    GameContext,
    GameManagerDep,
    GameViewerDep,
    GroupAdminDep,
    GroupMemberDep,
    SessionDep,
    ViewerDep,
)
from app.db.models import Game, GameParticipant, GameScheduleChange, PlayerProfile, User
from app.domain import balancing as balancing_domain
from app.domain import games as games_domain
from app.domain import participants as participants_domain
from app.domain.enums import GameStatus, ParticipantStatus
from app.domain.errors import NotFound, PermissionDenied
from app.schemas.games import (
    BalanceEntryResponse,
    BalanceSummaryResponse,
    CancelGameRequest,
    CreateGameRequest,
    CreateGameResponse,
    GameDetailResponse,
    GameResponse,
    JoinGameRequest,
    ParticipantResponse,
    PaymentRequest,
    ReorderRequest,
    ScheduleChangeResponse,
    UpdateGameRequest,
    ViewerAccessResponse,
)

router = APIRouter(tags=["games"])

#: Fields a PATCH may change without touching the schedule.
PLAIN_GAME_FIELDS = (
    "location", "court_number", "court_cost_cents", "min_players",
    "payment_info", "player_notice", "payment_deadline_days",
)
#: Changing any of these re-applies payment marks and deadlines to the lists.
PAYMENT_FIELDS = ("payment_tracking_enabled", "payment_deadline_days")


def _normalize_payment_fields(game: Game) -> None:
    """Payment details and a deadline exist only while tracking is on
    (enforced by a check constraint as well)."""
    if not game.payment_tracking_enabled:
        game.payment_info = ""
        game.payment_deadline_days = None
#: Changing any of these forces starts_at/ends_at to be recomputed.
SCHEDULE_FIELDS = ("game_date", "start_time", "duration_minutes")


def _participant_response(row: GameParticipant) -> ParticipantResponse:
    return ParticipantResponse(
        id=row.id,
        player_id=row.player_id,
        user_id=row.user_id,
        display_name=row.display_name_snapshot,
        status=row.status,
        list_position=row.list_position,
        paid=row.paid_at is not None,
        payment_due_at=row.payment_due_at,
        team=row.team,
    )


async def _lists(
    session: SessionDep, game_id: UUID
) -> tuple[list[GameParticipant], list[GameParticipant]]:
    rows = (
        (
            await session.execute(
                select(GameParticipant)
                .where(GameParticipant.game_id == game_id)
                .order_by(GameParticipant.list_position)
            )
        )
        .scalars()
        .all()
    )
    confirmed = [r for r in rows if r.status is ParticipantStatus.CONFIRMED]
    waiting = [r for r in rows if r.status is ParticipantStatus.WAITING_LIST]
    return confirmed, waiting


async def _user_name(session: SessionDep, user_id: UUID | None) -> str | None:
    if user_id is None:
        return None
    user = await session.get(User, user_id)
    return user.display_name if user else None


async def _detail(session: SessionDep, context: GameContext) -> GameDetailResponse:
    """The full game view: lists, the viewer's capabilities and the team
    balance state. Every endpoint returning a detail goes through here."""
    game = context.game
    await session.refresh(game)
    confirmed, waiting = await _lists(session, game.id)
    state = await balancing_domain.summary(session, game.id)
    change = await balancing_domain.latest_schedule_change(session, game.id)
    latest = None
    if state.latest is not None:
        opened_by = None
        if state.latest.window_opened_by_schedule_change_id is not None:
            source = await session.get(
                GameScheduleChange, state.latest.window_opened_by_schedule_change_id
            )
            opened_by = await _user_name(session, source.changed_by_user_id if source else None)
        latest = BalanceEntryResponse(
            trigger_type=state.latest.trigger_type,
            standard_balance_number=state.latest.standard_balance_number,
            generated_at=state.latest.generated_at,
            triggered_by_name=(
                await _user_name(session, state.latest.triggered_by_user_id)
                if context.access.can_manage_game
                else None
            ),
            rescheduled_by_name=opened_by,
        )
    return GameDetailResponse(
        game=GameResponse.model_validate(game),
        viewer_access=ViewerAccessResponse.model_validate(context.access),
        confirmed=[_participant_response(row) for row in confirmed],
        waiting_list=[_participant_response(row) for row in waiting],
        balance=BalanceSummaryResponse(
            standard_count=state.standard_count,
            standard_limit=balancing_domain.STANDARD_BALANCE_LIMIT,
            late_rebalance_used=state.late_rebalance_used,
            window_starts_at=game.balance_window_starts_at,
            window_ends_at=game.balance_window_ends_at,
            latest=latest,
        ),
        last_schedule_change=(
            ScheduleChangeResponse(
                previous_starts_at=change.previous_starts_at,
                current_starts_at=change.current_starts_at,
                changed_at=change.changed_at,
                changed_by_name=await _user_name(session, change.changed_by_user_id) or "",
                was_brought_forward=change.current_starts_at < change.previous_starts_at,
            )
            if change is not None
            else None
        ),
    )


@router.get("/groups/{group_id}/games", response_model=list[GameResponse])
async def list_games(context: GroupMemberDep, session: SessionDep) -> list[GameResponse]:
    rows = (
        (
            await session.execute(
                select(Game)
                .where(Game.group_id == context.group.id, Game.status != GameStatus.DELETED)
                .order_by(Game.starts_at)
            )
        )
        .scalars()
        .all()
    )
    return [GameResponse.model_validate(row) for row in rows]


@router.post("/groups/{group_id}/games", response_model=CreateGameResponse, status_code=201)
async def create_game(
    body: CreateGameRequest, context: GroupAdminDep, session: SessionDep
) -> CreateGameResponse:
    tracking = body.payment_tracking_enabled
    created = await games_domain.create_game(
        session,
        group_id=context.group.id,
        created_by_user_id=context.viewer.user.id,
        game_date=body.game_date,
        start_time=body.start_time,
        duration_minutes=body.duration_minutes,
        max_players=body.max_players,
        min_players=body.min_players,
        location=body.location,
        court_number=body.court_number,
        court_cost_cents=body.court_cost_cents,
        currency=body.currency,
        auto_cancellation_hours=body.auto_cancellation_hours,
        payment_tracking_enabled=tracking,
        payment_deadline_days=body.payment_deadline_days if tracking else None,
        payment_info=body.payment_info if tracking else "",
        player_notice=body.player_notice,
    )
    return CreateGameResponse(
        game=GameResponse.model_validate(created.game), join_code=created.join_code
    )


@router.get("/games/{game_id}", response_model=GameDetailResponse)
async def read_game(context: GameViewerDep, session: SessionDep) -> GameDetailResponse:
    await participants_domain.sweep_payment_deadlines(session, game_id=context.game.id)
    return await _detail(session, context)


@router.patch("/games/{game_id}", response_model=GameResponse)
async def update_game(
    body: UpdateGameRequest, context: GameManagerDep, session: SessionDep
) -> GameResponse:
    game = context.game
    changes = body.model_dump(exclude_unset=True)

    for field in PLAIN_GAME_FIELDS:
        if field in changes:
            setattr(game, field, changes[field])
    if changes.get("payment_tracking_enabled") is not None:
        game.payment_tracking_enabled = changes["payment_tracking_enabled"]
    _normalize_payment_fields(game)

    if any(field in changes for field in SCHEDULE_FIELDS):
        previous_start = game.starts_at
        for field in SCHEDULE_FIELDS:
            if field in changes:
                setattr(game, field, changes[field])
        from app.domain.groups import get_group

        games_domain.recompute_schedule(game, await get_group(session, game.group_id))
        if game.starts_at != previous_start and context.viewer is not None:
            # Moves the final-rebalance window; never resets the quota.
            session.add(
                GameScheduleChange(
                    game_id=game.id,
                    previous_starts_at=previous_start,
                    current_starts_at=game.starts_at,
                    changed_by_user_id=context.viewer.user.id,
                )
            )

    if "max_players" in changes:
        game.max_players = changes["max_players"]
        await session.flush()
        # Rule 13: a shrink pushes the roster tail to the waiting-list front.
        await participants_domain.resettle_after_capacity_change(session, game_id=game.id)

    if any(field in changes for field in PAYMENT_FIELDS):
        await session.flush()
        await participants_domain.apply_payment_settings(session, game_id=game.id)

    await session.flush()
    return GameResponse.model_validate(game)


@router.post("/games/{game_id}/cancel", response_model=GameResponse)
async def cancel_game(
    body: CancelGameRequest, context: GameManagerDep, session: SessionDep
) -> GameResponse:
    game = await games_domain.cancel_game(
        session, game_id=context.game.id, reason=body.reason
    )
    return GameResponse.model_validate(game)


@router.post("/games/{game_id}/team-balance", response_model=GameDetailResponse)
async def draw_teams(context: GameManagerDep, session: SessionDep) -> GameDetailResponse:
    """One manual draw: three regular ones per game, then a single final
    rebalance inside the window that opens 15 minutes before kickoff."""
    assert context.viewer is not None
    await balancing_domain.draw(
        session, game_id=context.game.id, actor_user_id=context.viewer.user.id
    )
    return await _detail(session, context)


@router.delete("/games/{game_id}", status_code=204)
async def delete_game(context: GameManagerDep, session: SessionDep) -> None:
    await games_domain.delete_game(session, game_id=context.game.id)


@router.post("/games/{game_id}/participants", response_model=GameDetailResponse, status_code=201)
async def join_game(
    body: JoinGameRequest, context: GameViewerDep, session: SessionDep, viewer: ViewerDep
) -> GameDetailResponse:
    if not context.access.can_join and not context.access.can_manage_game:
        raise PermissionDenied("You cannot join that game")

    player_id = body.player_id
    if player_id is None:
        # A member joins through their linked profile in this group (rule 4).
        profile = (
            await session.execute(
                select(PlayerProfile).where(
                    PlayerProfile.group_id == context.game.group_id,
                    PlayerProfile.owner_user_id == viewer.user.id,
                )
            )
        ).scalar_one_or_none()
        if profile is None:
            raise NotFound("You have no player profile in that group")
        player_id = profile.id
    elif not context.access.can_manage_game:
        # Only an admin may add someone else; everyone else joins as themselves.
        profile = await session.get(PlayerProfile, player_id)
        if profile is None or profile.owner_user_id != viewer.user.id:
            raise PermissionDenied("You may only add yourself to that game")

    profile = await session.get(PlayerProfile, player_id)
    if profile is None or profile.archived_at is not None:
        raise NotFound("Player profile not found")
    if profile.group_id != context.game.group_id:
        # A player profile is scoped to a group. In particular, an admin must
        # not be able to use a UUID learned in Group A to add that person to a
        # game in Group B.
        raise PermissionDenied("That player does not belong to this game's group")

    await participants_domain.join_game(
        session,
        game_id=context.game.id,
        player_id=player_id,
        # Ownership belongs to the player being added, never to the admin
        # performing the list-management action. Manual guest profiles have
        # no owner and therefore no self-service payment/leave access.
        user_id=profile.owner_user_id,
        display_name=body.display_name or profile.display_name,
    )
    return await _detail(session, context)


async def _owned_participant(
    session: SessionDep, game_id: UUID, participant_id: UUID
) -> GameParticipant:
    row = await session.get(GameParticipant, participant_id)
    if row is None or row.game_id != game_id:
        raise NotFound("Participant is not on this game's list")
    return row


@router.patch(
    "/games/{game_id}/participants/{participant_id}/payment",
    response_model=list[ParticipantResponse],
)
async def update_payment(
    participant_id: UUID,
    body: PaymentRequest,
    context: GameViewerDep,
    session: SessionDep,
    viewer: ViewerDep,
) -> list[ParticipantResponse]:
    row = await _owned_participant(session, context.game.id, participant_id)
    # Rule 10: a participant may change only their own payment state.
    own = row.user_id == viewer.user.id
    if not context.access.can_manage_game and not (
        own and context.access.can_update_own_payment
    ):
        raise PermissionDenied("You may only update your own payment")

    await participants_domain.set_payment(
        session,
        game_id=context.game.id,
        participant_id=participant_id,
        paid=body.paid,
        actor_user_id=viewer.user.id,
    )
    confirmed, waiting = await _lists(session, context.game.id)
    return [_participant_response(r) for r in [*confirmed, *waiting]]


@router.post(
    "/games/{game_id}/participants/{participant_id}/leave",
    response_model=list[ParticipantResponse],
)
async def leave_game(
    participant_id: UUID, context: GameViewerDep, session: SessionDep, viewer: ViewerDep
) -> list[ParticipantResponse]:
    row = await _owned_participant(session, context.game.id, participant_id)
    own = row.user_id == viewer.user.id
    if not context.access.can_manage_game and not (own and context.access.can_leave):
        raise PermissionDenied("You may only remove yourself from that game")

    await participants_domain.leave_game(
        session,
        game_id=context.game.id,
        participant_id=participant_id,
        actor_user_id=viewer.user.id,
        removed=not own,
    )
    confirmed, waiting = await _lists(session, context.game.id)
    return [_participant_response(r) for r in [*confirmed, *waiting]]


@router.delete(
    "/games/{game_id}/participants/{participant_id}",
    response_model=list[ParticipantResponse],
)
async def remove_participant(
    participant_id: UUID, context: GameManagerDep, session: SessionDep
) -> list[ParticipantResponse]:
    await _owned_participant(session, context.game.id, participant_id)
    await participants_domain.leave_game(
        session,
        game_id=context.game.id,
        participant_id=participant_id,
        actor_user_id=context.user_id,
        removed=True,
    )
    confirmed, waiting = await _lists(session, context.game.id)
    return [_participant_response(r) for r in [*confirmed, *waiting]]


@router.post(
    "/games/{game_id}/participants/reorder", response_model=list[ParticipantResponse]
)
async def reorder(
    body: ReorderRequest, context: GameManagerDep, session: SessionDep
) -> list[ParticipantResponse]:
    await participants_domain.reorder_list(
        session,
        game_id=context.game.id,
        status=body.status,
        ordered_ids=body.ordered_ids,
    )
    confirmed, waiting = await _lists(session, context.game.id)
    return [_participant_response(r) for r in [*confirmed, *waiting]]

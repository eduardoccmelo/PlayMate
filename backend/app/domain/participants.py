"""Roster and waiting-list transactions.

Every public function here follows the same shape, required by §6.2 of the
plan: lock the game row with `SELECT ... FOR UPDATE`, mutate, re-settle both
lists, renumber, notify. Callers must run them inside one transaction and
commit at the boundary.

The list-order unique constraint is DEFERRABLE INITIALLY DEFERRED, which is
what lets a renumber write overlapping positions mid-transaction and still
be checked at COMMIT.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import normalize_name
from app.core.time import utcnow
from app.db.models import Game, GameParticipant, PlayerProfile
from app.domain.enums import GameStatus, NotificationType, ParticipantStatus
from app.domain.errors import Conflict, NotFound, ValidationFailed
from app.domain.notifications import notify_group_admins
from app.domain.ordering import ListEntry, settle

ACTIVE_STATUSES = (ParticipantStatus.CONFIRMED, ParticipantStatus.WAITING_LIST)


@dataclass
class RosterChange:
    """What a transaction did, for the response and for notifications."""

    participant: GameParticipant | None
    promoted: list[GameParticipant]
    overflowed: list[GameParticipant]


async def lock_game(session: AsyncSession, game_id: UUID) -> Game:
    """Serialize every roster change to this game behind one row lock."""
    game = (
        await session.execute(select(Game).where(Game.id == game_id).with_for_update())
    ).scalar_one_or_none()
    if game is None:
        raise NotFound("Game not found")
    return game


async def _active_lists(
    session: AsyncSession, game_id: UUID
) -> tuple[list[GameParticipant], list[GameParticipant]]:
    rows = (
        (
            await session.execute(
                select(GameParticipant).where(
                    GameParticipant.game_id == game_id,
                    GameParticipant.status.in_(ACTIVE_STATUSES),
                )
            )
        )
        .scalars()
        .all()
    )
    confirmed = sorted(
        (row for row in rows if row.status is ParticipantStatus.CONFIRMED),
        key=lambda row: row.list_position or 0,
    )
    waiting = sorted(
        (row for row in rows if row.status is ParticipantStatus.WAITING_LIST),
        key=lambda row: row.list_position or 0,
    )
    return confirmed, waiting


def is_overdue(row: GameParticipant, now: datetime) -> bool:
    return (
        row.paid_at is None
        and row.payment_due_at is not None
        and row.payment_due_at <= now
    )


#: Public name for other domain modules.
active_lists = _active_lists


def _entries(rows: list[GameParticipant], now: datetime) -> list[ListEntry]:
    return [
        ListEntry(
            id=row.id,
            paid=row.paid_at is not None,
            position=row.list_position,
            overdue=is_overdue(row, now),
        )
        for row in rows
    ]


def due_at_for(game: Game, now: datetime) -> datetime | None:
    """The individual deadline a new entry gets, if the game has one."""
    if not game.payment_tracking_enabled or game.payment_deadline_days is None:
        return None
    return now + timedelta(days=game.payment_deadline_days)


async def _settle_lists(
    session: AsyncSession,
    game: Game,
    confirmed: list[GameParticipant],
    waiting: list[GameParticipant],
) -> tuple[list[GameParticipant], list[GameParticipant]]:
    """Apply the pure ordering rules and write the result back."""
    by_id = {row.id: row for row in [*confirmed, *waiting]}
    now = utcnow()
    new_confirmed, new_waiting, promoted, overflowed = settle(
        _entries(confirmed, now), _entries(waiting, now), game.max_players
    )

    for entry in new_confirmed:
        row = by_id[entry.id]
        row.status = ParticipantStatus.CONFIRMED
        row.list_position = entry.position
    for entry in new_waiting:
        row = by_id[entry.id]
        row.status = ParticipantStatus.WAITING_LIST
        row.list_position = entry.position
        row.team = None  # Only confirmed players can hold a team place.

    await session.flush()
    from app.domain import balancing  # Local: balancing imports this module.

    await balancing.reconcile(session, game, [by_id[entry.id] for entry in new_confirmed])
    return (
        [by_id[entry.id] for entry in promoted],
        [by_id[entry.id] for entry in overflowed],
    )


def _require_open(game: Game) -> None:
    if game.status is not GameStatus.ACTIVE:
        raise Conflict(f"Game is {game.status}")


async def join_game(
    session: AsyncSession,
    *,
    game_id: UUID,
    player_id: UUID,
    user_id: UUID | None,
    display_name: str,
) -> RosterChange:
    """Rule 4/13. Joins the roster, or the waiting-list tail when full."""
    game = await lock_game(session, game_id)
    _require_open(game)

    player = await session.get(PlayerProfile, player_id)
    if player is None:
        raise NotFound("Player profile not found")

    confirmed, waiting = await _active_lists(session, game_id)

    existing = (
        await session.execute(
            select(GameParticipant).where(
                GameParticipant.game_id == game_id, GameParticipant.player_id == player_id
            )
        )
    ).scalar_one_or_none()

    # Rule 11: unique name within the active lists, case and whitespace insensitive.
    normalized = normalize_name(display_name)
    for row in [*confirmed, *waiting]:
        if row.player_id != player_id and normalize_name(row.display_name_snapshot) == normalized:
            raise Conflict(f"'{display_name}' is already on this game's list")

    if existing is not None and existing.status in ACTIVE_STATUSES:
        raise Conflict("Player is already on this game's list")

    if existing is not None:
        # Rejoining after leaving reuses the row - the unique (game, player)
        # constraint means we cannot insert a second one.
        participant = existing
        participant.left_at = None
        participant.user_id = user_id
        participant.display_name_snapshot = display_name
    else:
        participant = GameParticipant(
            game_id=game_id,
            player_id=player_id,
            user_id=user_id,
            display_name_snapshot=display_name,
            status=ParticipantStatus.WAITING_LIST,
            list_position=len(waiting),
        )
        session.add(participant)

    # Keep an earlier deadline on rejoin, so leaving cannot reset it.
    if participant.payment_due_at is None:
        participant.payment_due_at = due_at_for(game, utcnow())

    has_room = len(confirmed) < game.max_players
    participant.status = (
        ParticipantStatus.CONFIRMED if has_room else ParticipantStatus.WAITING_LIST
    )
    participant.list_position = len(confirmed) if has_room else len(waiting)
    await session.flush()

    if has_room:
        confirmed.append(participant)
    else:
        waiting.append(participant)

    promoted, overflowed = await _settle_lists(session, game, confirmed, waiting)
    await notify_group_admins(
        session,
        group_id=game.group_id,
        game_id=game.id,
        type=NotificationType.PLAYER_JOINED,
        actor_user_id=user_id,
        player_id=player_id,
        payload={"status": participant.status.value, "displayName": display_name},
    )
    return RosterChange(participant=participant, promoted=promoted, overflowed=overflowed)


async def leave_game(
    session: AsyncSession,
    *,
    game_id: UUID,
    participant_id: UUID,
    actor_user_id: UUID | None,
    removed: bool = False,
) -> RosterChange:
    """Rule 13. Leaving frees a slot, so the waiting-list head is promoted."""
    game = await lock_game(session, game_id)
    _require_open(game)

    confirmed, waiting = await _active_lists(session, game_id)
    participant = next(
        (row for row in [*confirmed, *waiting] if row.id == participant_id), None
    )
    if participant is None:
        raise NotFound("Participant is not on this game's list")

    participant.status = (
        ParticipantStatus.REMOVED if removed else ParticipantStatus.LEFT
    )
    participant.left_at = utcnow()
    participant.list_position = None
    participant.team = None
    await session.flush()

    confirmed = [row for row in confirmed if row.id != participant_id]
    waiting = [row for row in waiting if row.id != participant_id]

    promoted, overflowed = await _settle_lists(session, game, confirmed, waiting)
    await notify_group_admins(
        session,
        group_id=game.group_id,
        game_id=game.id,
        type=NotificationType.PLAYER_LEFT,
        actor_user_id=actor_user_id,
        player_id=participant.player_id,
        payload={"removed": removed, "displayName": participant.display_name_snapshot},
    )
    for row in promoted:
        await notify_group_admins(
            session,
            group_id=game.group_id,
            game_id=game.id,
            type=NotificationType.WAITING_LIST_PROMOTED,
            player_id=row.player_id,
            payload={"displayName": row.display_name_snapshot},
        )
    return RosterChange(participant=participant, promoted=promoted, overflowed=overflowed)


async def set_payment(
    session: AsyncSession,
    *,
    game_id: UUID,
    participant_id: UUID,
    paid: bool,
    actor_user_id: UUID | None,
) -> RosterChange:
    """Rule 14. A payment change re-sorts the stored roster, paid first."""
    game = await lock_game(session, game_id)
    if not game.payment_tracking_enabled:
        raise Conflict("Payment tracking is off for this game")
    confirmed, waiting = await _active_lists(session, game_id)

    participant = next(
        (row for row in [*confirmed, *waiting] if row.id == participant_id), None
    )
    if participant is None:
        raise NotFound("Participant is not on this game's list")

    participant.paid_at = utcnow() if paid else None
    await session.flush()

    promoted, overflowed = await _settle_lists(session, game, confirmed, waiting)
    await notify_group_admins(
        session,
        group_id=game.group_id,
        game_id=game.id,
        type=NotificationType.PAYMENT_STATUS_CHANGED,
        actor_user_id=actor_user_id,
        player_id=participant.player_id,
        payload={"paid": paid, "displayName": participant.display_name_snapshot},
    )
    return RosterChange(participant=participant, promoted=promoted, overflowed=overflowed)


async def reorder_list(
    session: AsyncSession,
    *,
    game_id: UUID,
    status: ParticipantStatus,
    ordered_ids: list[UUID],
) -> RosterChange:
    """Apply an organizer's manual order, then re-settle.

    Rule 14 still wins: the paid block stays ahead of the unpaid one, and the
    requested order is preserved within each block.
    """
    if status not in ACTIVE_STATUSES:
        raise ValidationFailed("Only the roster and waiting list can be reordered")

    game = await lock_game(session, game_id)
    confirmed, waiting = await _active_lists(session, game_id)
    target = confirmed if status is ParticipantStatus.CONFIRMED else waiting

    if {row.id for row in target} != set(ordered_ids):
        raise ValidationFailed("The new order must list exactly the current entries once each")

    by_id = {row.id: row for row in target}
    reordered = [by_id[identifier] for identifier in ordered_ids]
    if status is ParticipantStatus.CONFIRMED:
        confirmed = reordered
    else:
        waiting = reordered

    promoted, overflowed = await _settle_lists(session, game, confirmed, waiting)
    return RosterChange(participant=None, promoted=promoted, overflowed=overflowed)


async def resettle_after_capacity_change(
    session: AsyncSession, *, game_id: UUID
) -> RosterChange:
    """Rule 13. After `max_players` changes: a shrink pushes the roster tail
    to the *front* of the waiting list; a growth promotes from the head."""
    game = await lock_game(session, game_id)
    confirmed, waiting = await _active_lists(session, game_id)
    promoted, overflowed = await _settle_lists(session, game, confirmed, waiting)
    for row in promoted:
        await notify_group_admins(
            session,
            group_id=game.group_id,
            game_id=game.id,
            type=NotificationType.WAITING_LIST_PROMOTED,
            player_id=row.player_id,
            payload={"displayName": row.display_name_snapshot},
        )
    return RosterChange(participant=None, promoted=promoted, overflowed=overflowed)


async def apply_payment_settings(session: AsyncSession, *, game_id: UUID) -> RosterChange:
    """Bring every entry in line with the game's current payment settings.

    Tracking off clears payment marks and deadlines. A deadline that is
    switched on gives every active entry without one its own due instant;
    switching the deadline off clears them. Then the lists are re-settled,
    which demotes anyone already overdue.
    """
    game = await lock_game(session, game_id)
    confirmed, waiting = await _active_lists(session, game_id)
    now = utcnow()
    for row in [*confirmed, *waiting]:
        if not game.payment_tracking_enabled:
            row.paid_at = None
            row.payment_due_at = None
        elif game.payment_deadline_days is None:
            row.payment_due_at = None
        elif row.payment_due_at is None:
            row.payment_due_at = due_at_for(game, now)
    await session.flush()
    promoted, overflowed = await _settle_lists(session, game, confirmed, waiting)
    for row in promoted:
        await notify_group_admins(
            session,
            group_id=game.group_id,
            game_id=game.id,
            type=NotificationType.WAITING_LIST_PROMOTED,
            player_id=row.player_id,
            payload={"displayName": row.display_name_snapshot},
        )
    return RosterChange(participant=None, promoted=promoted, overflowed=overflowed)


async def sweep_payment_deadlines(session: AsyncSession, *, game_id: UUID) -> None:
    """Apply deadlines that passed since the last write to this game.

    docs/backend-schema.md describes a scheduled worker for this. Until one
    exists, every read of a game's lists calls this first, so nobody ever
    sees an overdue player still on the roster. It locks the game only when
    there is something to move.
    """
    overdue = (
        await session.execute(
            select(GameParticipant.id)
            .where(
                GameParticipant.game_id == game_id,
                GameParticipant.status == ParticipantStatus.CONFIRMED,
                GameParticipant.paid_at.is_(None),
                GameParticipant.payment_due_at <= utcnow(),
            )
            .limit(1)
        )
    ).first()
    if overdue is None:
        return
    game = await lock_game(session, game_id)
    if game.status is not GameStatus.ACTIVE:
        return
    await resettle_after_capacity_change(session, game_id=game_id)

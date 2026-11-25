"""Server-side team balancing: eligibility, the 3 + 1 quota, stored draws and
what a roster change does to them (docs/backend-schema.md, "Team-balance
snapshots" and "Team-balancing guard").

- Eligible: confirmed participants; with payment tracking, only paid ones.
  The waiting list never plays.
- Quota: three organizer draws per game, then exactly one final rebalance,
  allowed only inside the game's balance window. Nothing resets the count.
- A roster or eligible-payment change never draws and never spends quota.
  If every newcomer replaces a departed player with an identical balance
  signature (position, effective level, mobility, condition), the newcomer
  inherits that team place; any other change invalidates the active split.
"""

from collections import defaultdict
from dataclasses import dataclass
from decimal import Decimal
from random import Random
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.time import utcnow
from app.db.models import (
    Game,
    GameParticipant,
    GameScheduleChange,
    GameTeamBalance,
    GameTeamBalanceMember,
    PlayerProfile,
)
from app.domain.enums import GameStatus, ParticipantStatus, TeamBalanceTrigger, TeamSide
from app.domain.errors import Conflict
from app.domain.teams import (
    ALGORITHM_VERSION,
    DrawPlayer,
    PreviousSplit,
    generate_balanced_teams,
    player_score,
)

STANDARD_BALANCE_LIMIT = 3
#: Players without any level ballot play at the default level
#: (docs/backend-schema.md rule 16).
DEFAULT_LEVEL = 3


def signature(profile: PlayerProfile) -> str:
    """The inputs the draw uses; equal signatures are interchangeable."""
    return ":".join(
        (
            profile.field_position.value,
            str(profile.level or DEFAULT_LEVEL),
            profile.mobility.value,
            profile.condition.value,
        )
    )


def _draw_player(row: GameParticipant, profile: PlayerProfile) -> DrawPlayer:
    return DrawPlayer(
        identifier=row.id,
        level=profile.level or DEFAULT_LEVEL,
        mobility=profile.mobility,
        condition=profile.condition,
        position=profile.field_position,
        display_name=row.display_name_snapshot,
    )


def eligible(game: Game, confirmed: list[GameParticipant]) -> list[GameParticipant]:
    if game.payment_tracking_enabled:
        return [row for row in confirmed if row.paid_at is not None]
    return list(confirmed)


async def _profiles(
    session: AsyncSession, rows: list[GameParticipant]
) -> dict[UUID, PlayerProfile]:
    if not rows:
        return {}
    found = await session.execute(
        select(PlayerProfile).where(PlayerProfile.id.in_({row.player_id for row in rows}))
    )
    return {profile.id: profile for profile in found.scalars().all()}


async def _balances(session: AsyncSession, game_id: UUID) -> list[GameTeamBalance]:
    rows = await session.execute(
        select(GameTeamBalance)
        .where(GameTeamBalance.game_id == game_id)
        .order_by(GameTeamBalance.generated_at)
    )
    return list(rows.scalars().all())


async def _members(session: AsyncSession, balance_id: UUID) -> list[GameTeamBalanceMember]:
    rows = await session.execute(
        select(GameTeamBalanceMember).where(GameTeamBalanceMember.team_balance_id == balance_id)
    )
    return list(rows.scalars().all())


@dataclass
class BalanceSummary:
    standard_count: int
    late_rebalance_used: bool
    latest: GameTeamBalance | None
    active: GameTeamBalance | None


async def summary(session: AsyncSession, game_id: UUID) -> BalanceSummary:
    balances = await _balances(session, game_id)
    return BalanceSummary(
        standard_count=sum(
            1 for balance in balances if balance.trigger_type is TeamBalanceTrigger.ORGANIZER
        ),
        late_rebalance_used=any(
            balance.trigger_type is TeamBalanceTrigger.LATE_REBALANCE for balance in balances
        ),
        latest=balances[-1] if balances else None,
        active=next((b for b in reversed(balances) if b.invalidated_at is None), None),
    )


async def latest_schedule_change(
    session: AsyncSession, game_id: UUID
) -> GameScheduleChange | None:
    return (
        await session.execute(
            select(GameScheduleChange)
            .where(GameScheduleChange.game_id == game_id)
            .order_by(GameScheduleChange.changed_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()


def _clear_split(game: Game, rows: list[GameParticipant]) -> None:
    for row in rows:
        row.team = None
    game.teams_drawn_at = None
    game.team_a_score = None
    game.team_b_score = None


async def draw(
    session: AsyncSession, *, game_id: UUID, actor_user_id: UUID, rng: Random | None = None
) -> GameTeamBalance:
    """Run one manual draw, spending one place in the quota."""
    # Local import: participants calls back into this module on every settle.
    from app.domain import participants as participants_domain

    await participants_domain.sweep_payment_deadlines(session, game_id=game_id)
    game = await participants_domain.lock_game(session, game_id)
    if game.status is not GameStatus.ACTIVE:
        raise Conflict(f"Game is {game.status}")
    now = utcnow()
    if now >= game.balance_window_ends_at:
        raise Conflict("The game has ended; its teams can no longer change")

    confirmed, _ = await participants_domain.active_lists(session, game_id)
    rows = eligible(game, confirmed)
    if len(rows) < 2:
        raise Conflict(
            "Mark at least two players as paid to draw teams"
            if game.payment_tracking_enabled
            else "Add at least two players to the list to draw teams"
        )

    state = await summary(session, game_id)
    window_change_id: UUID | None = None
    if state.standard_count < STANDARD_BALANCE_LIMIT:
        trigger = TeamBalanceTrigger.ORGANIZER
        number: int | None = state.standard_count + 1
    elif game.balance_window_starts_at <= now and not state.late_rebalance_used:
        trigger, number = TeamBalanceTrigger.LATE_REBALANCE, None
        change = await latest_schedule_change(session, game_id)
        if change is not None and change.current_starts_at < change.previous_starts_at:
            # The final window opened earlier because the game was moved forward.
            window_change_id = change.id
    elif state.late_rebalance_used:
        raise Conflict("The final rebalance has already been used")
    else:
        raise Conflict("The regular balances are used; the final one opens 15 minutes before")

    previous: PreviousSplit | None = None
    if state.active is not None:
        members = await _members(session, state.active.id)
        previous = (
            frozenset(m.participant_id for m in members if m.team is TeamSide.A),
            frozenset(m.participant_id for m in members if m.team is TeamSide.B),
        )
        state.active.invalidated_at = now
    _clear_split(game, confirmed)
    # Retire the old split before inserting the new one: one active per game.
    await session.flush()

    profiles = await _profiles(session, rows)
    players = [_draw_player(row, profiles[row.player_id]) for row in rows]
    result = generate_balanced_teams(players, previous, rng)

    balance = GameTeamBalance(
        game_id=game_id,
        trigger_type=trigger,
        triggered_by_user_id=actor_user_id,
        window_opened_by_schedule_change_id=window_change_id,
        standard_balance_number=number,
        algorithm_version=ALGORITHM_VERSION,
        team_a_score=result.score_a,
        team_b_score=result.score_b,
    )
    session.add(balance)
    await session.flush()

    by_id = {row.id: row for row in rows}
    for side, team in ((TeamSide.A, result.team_a), (TeamSide.B, result.team_b)):
        for player in team:
            row = by_id[player.identifier]
            profile = profiles[row.player_id]
            row.team = side
            row.level_at_draw = profile.level or DEFAULT_LEVEL
            session.add(
                GameTeamBalanceMember(
                    team_balance_id=balance.id,
                    participant_id=row.id,
                    team=side,
                    score_snapshot=Decimal(str(round(player_score(player), 2))),
                    signature=signature(profile),
                )
            )
    game.teams_drawn_at = now
    game.team_a_score = result.score_a
    game.team_b_score = result.score_b
    await session.flush()
    return balance


async def reconcile(session: AsyncSession, game: Game, confirmed: list[GameParticipant]) -> None:
    """Keep or drop the active split after the lists were re-settled.

    `confirmed` is the settled roster (rows already carry their new status).
    """
    if utcnow() >= game.balance_window_ends_at:
        return  # A finished game keeps its last split (rule 15).
    active = next(
        (b for b in reversed(await _balances(session, game.id)) if b.invalidated_at is None),
        None,
    )
    if active is None:
        return

    members = await _members(session, active.id)
    by_participant = {member.participant_id: member for member in members}
    rows = eligible(game, confirmed)
    eligible_ids = {row.id for row in rows}

    if eligible_ids != set(by_participant):
        departed = [m for m in members if m.participant_id not in eligible_ids]
        newcomers = [row for row in rows if row.id not in by_participant]
        profiles = await _profiles(session, newcomers)
        pool: dict[str, list[GameTeamBalanceMember]] = defaultdict(list)
        for member in departed:
            pool[member.signature].append(member)
        matches: list[tuple[GameParticipant, GameTeamBalanceMember]] = []
        for row in newcomers:
            candidates = pool.get(signature(profiles[row.player_id]))
            if candidates:
                matches.append((row, candidates.pop()))
        if len(matches) != len(newcomers) or len(matches) != len(departed):
            active.invalidated_at = utcnow()
            _clear_split(game, confirmed)
            await session.flush()
            return
        # An identical replacement inherits the place; the split stays.
        for row, member in matches:
            await session.delete(member)
            await session.flush()
            session.add(
                GameTeamBalanceMember(
                    team_balance_id=active.id,
                    participant_id=row.id,
                    team=member.team,
                    score_snapshot=member.score_snapshot,
                    signature=member.signature,
                )
            )
        by_participant = {
            **{m.participant_id: m for m in members if m.participant_id in eligible_ids},
            **{row.id: member for row, member in matches},
        }

    for row in confirmed:
        kept = by_participant.get(row.id)
        row.team = kept.team if kept is not None else None
    await session.flush()


async def invalidate_for_player(session: AsyncSession, player_id: UUID) -> None:
    """A player's balance inputs changed: drop active splits they are in."""
    rows = await session.execute(
        select(GameTeamBalance, Game)
        .join(GameTeamBalanceMember, GameTeamBalanceMember.team_balance_id == GameTeamBalance.id)
        .join(GameParticipant, GameParticipant.id == GameTeamBalanceMember.participant_id)
        .join(Game, Game.id == GameTeamBalance.game_id)
        .where(
            GameParticipant.player_id == player_id,
            GameTeamBalance.invalidated_at.is_(None),
            Game.status == GameStatus.ACTIVE,
        )
    )
    now = utcnow()
    for balance, game in rows.unique().all():
        if now >= game.balance_window_ends_at:
            continue
        balance.invalidated_at = now
        confirmed = (
            await session.execute(
                select(GameParticipant).where(
                    GameParticipant.game_id == game.id,
                    GameParticipant.status == ParticipantStatus.CONFIRMED,
                )
            )
        ).scalars().all()
        _clear_split(game, list(confirmed))
    await session.flush()

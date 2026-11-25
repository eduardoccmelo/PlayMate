"""Game codes, game-only guest access and organizer-added guests.

docs/app-flow.md: a non-member who receives a game code verifies their
identity (they are signed in) and goes straight onto the main or waiting
list. Game-only access never grants group membership. The access is an
approved `game_access_requests` row, which `games.viewer_access` already
turns into guest capabilities.
"""

from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import generate_code, hash_token
from app.core.time import utcnow
from app.db.models import Game, GameAccessRequest, GameParticipant, Group, PlayerProfile, User
from app.domain import participants as participants_domain
from app.domain import players as players_domain
from app.domain.enums import (
    AccessSource,
    AccessStatus,
    GameStatus,
    PlayerCondition,
    PlayerPosition,
    RequestKind,
)
from app.domain.errors import Conflict, NotFound
from app.domain.games import JOIN_CODE_LENGTH
from app.domain.groups import find_membership
from app.domain.participants import ACTIVE_STATUSES


def normalize_code(code: str) -> str:
    return code.strip().upper()


async def rotate_game_join_code(session: AsyncSession, game: Game) -> str:
    """Only the hash is stored, so sharing again issues a fresh code; the
    previous one stops working."""
    code = generate_code(JOIN_CODE_LENGTH)
    game.join_code_hash = hash_token(code)
    game.join_code_prefix = code[:4]
    await session.flush()
    return code


async def _linked_profile(
    session: AsyncSession, *, group_id: UUID, user: User
) -> PlayerProfile:
    """The user's profile in this group, created for a guest on first use."""
    profile = (
        await session.execute(
            select(PlayerProfile).where(
                PlayerProfile.group_id == group_id, PlayerProfile.owner_user_id == user.id
            )
        )
    ).scalar_one_or_none()
    if profile is not None:
        profile.archived_at = None
        return profile
    try:
        await players_domain.require_unique_name(
            session, group_id=group_id, display_name=user.display_name
        )
    except Conflict as error:
        raise Conflict(
            f"Someone in this group is already called '{user.display_name}'."
            " Change your profile name to join this game."
        ) from error
    profile = PlayerProfile(
        group_id=group_id, owner_user_id=user.id, display_name=user.display_name
    )
    session.add(profile)
    await session.flush()
    return profile


async def join_by_code(session: AsyncSession, *, join_code: str, user: User) -> Game:
    game = (
        await session.execute(
            select(Game).where(Game.join_code_hash == hash_token(normalize_code(join_code)))
        )
    ).scalar_one_or_none()
    if game is None or game.status is GameStatus.DELETED:
        raise NotFound("No game matches that code")
    if game.status is not GameStatus.ACTIVE:
        raise Conflict(f"Game is {game.status}")

    profile = await _linked_profile(session, group_id=game.group_id, user=user)
    member = await find_membership(session, group_id=game.group_id, user_id=user.id)
    if member is None:
        approved = (
            await session.execute(
                select(GameAccessRequest).where(
                    GameAccessRequest.game_id == game.id,
                    GameAccessRequest.user_id == user.id,
                    GameAccessRequest.status == AccessStatus.APPROVED,
                )
            )
        ).first()
        if approved is None:
            session.add(
                GameAccessRequest(
                    group_id=game.group_id,
                    game_id=game.id,
                    user_id=user.id,
                    kind=RequestKind.JOIN,
                    source=AccessSource.MANUAL_CODE,
                    status=AccessStatus.APPROVED,
                    requested_name=profile.display_name,
                    resolved_player_id=profile.id,
                    reviewed_at=utcnow(),
                )
            )
            await session.flush()

    already_listed = (
        await session.execute(
            select(GameParticipant.id).where(
                GameParticipant.game_id == game.id,
                GameParticipant.player_id == profile.id,
                GameParticipant.status.in_(ACTIVE_STATUSES),
            )
        )
    ).first()
    if already_listed is None:
        await participants_domain.join_game(
            session,
            game_id=game.id,
            player_id=profile.id,
            user_id=user.id,
            display_name=profile.display_name,
        )
    return game


@dataclass
class GuestGame:
    game: Game
    group: Group


async def guest_games(session: AsyncSession, *, user_id: UUID) -> list[GuestGame]:
    """Games the user reaches only through game access, not membership."""
    rows = await session.execute(
        select(Game, Group)
        .join(GameAccessRequest, GameAccessRequest.game_id == Game.id)
        .join(Group, Group.id == Game.group_id)
        .where(
            GameAccessRequest.user_id == user_id,
            GameAccessRequest.status == AccessStatus.APPROVED,
            Game.status != GameStatus.DELETED,
        )
        .order_by(Game.starts_at)
    )
    games: list[GuestGame] = []
    for game, group in rows.unique().all():
        if await find_membership(session, group_id=group.id, user_id=user_id) is None:
            games.append(GuestGame(game=game, group=group))
    return games


async def add_game_guest(
    session: AsyncSession,
    *,
    game: Game,
    display_name: str,
    position: PlayerPosition,
    condition: PlayerCondition,
) -> PlayerProfile:
    """An organizer's manual guest for one game: no account, no skill
    rating, kept out of the group's voting board, and put on the list."""
    await players_domain.require_unique_name(
        session, group_id=game.group_id, display_name=display_name
    )
    profile = PlayerProfile(
        group_id=game.group_id,
        owner_user_id=None,
        display_name=display_name.strip(),
        field_position=position,
        condition=condition,
        scope_game_id=game.id,
    )
    session.add(profile)
    await session.flush()
    await participants_domain.join_game(
        session,
        game_id=game.id,
        player_id=profile.id,
        user_id=None,
        display_name=profile.display_name,
    )
    return profile

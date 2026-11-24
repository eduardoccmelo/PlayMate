"""The group player directory: linked member profiles plus manual guests."""

from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import normalize_name
from app.core.time import utcnow
from app.db.models import Game, GameParticipant, PlayerProfile
from app.domain.enums import GameStatus, PlayerCondition, PlayerMobility, PlayerPosition
from app.domain.errors import Conflict, NotFound, PermissionDenied
from app.domain.participants import ACTIVE_STATUSES


async def list_players(session: AsyncSession, *, group_id: UUID) -> list[PlayerProfile]:
    return list(
        (
            await session.execute(
                select(PlayerProfile)
                .where(PlayerProfile.group_id == group_id, PlayerProfile.archived_at.is_(None))
                .order_by(PlayerProfile.display_name_normalized)
            )
        )
        .scalars()
        .all()
    )


async def get_player(session: AsyncSession, *, group_id: UUID, player_id: UUID) -> PlayerProfile:
    """A profile is only reachable through its own group (no cross-group ids)."""
    player = await session.get(PlayerProfile, player_id)
    if player is None or player.group_id != group_id or player.archived_at is not None:
        raise NotFound("Player not found in that group")
    return player


async def _require_unique_name(
    session: AsyncSession, *, group_id: UUID, display_name: str, except_id: UUID | None = None
) -> None:
    """Rule 11: names are unique per group, case and whitespace insensitive.

    Checked here so the client gets a 409 instead of the partial unique
    index surfacing as a 500.
    """
    query = select(PlayerProfile.id).where(
        PlayerProfile.group_id == group_id,
        PlayerProfile.archived_at.is_(None),
        PlayerProfile.display_name_normalized == normalize_name(display_name),
    )
    if except_id is not None:
        query = query.where(PlayerProfile.id != except_id)
    if (await session.execute(query)).first() is not None:
        raise Conflict(f"'{display_name.strip()}' already exists in this group")


async def create_guest(
    session: AsyncSession,
    *,
    group_id: UUID,
    display_name: str,
    level: int | None,
    mobility: PlayerMobility,
    condition: PlayerCondition,
    position: PlayerPosition,
) -> PlayerProfile:
    """A manual player without an account (the UI's "Guest" tag)."""
    await _require_unique_name(session, group_id=group_id, display_name=display_name)
    player = PlayerProfile(
        group_id=group_id,
        owner_user_id=None,
        display_name=display_name.strip(),
        level=level,
        mobility=mobility,
        condition=condition,
        field_position=position,
    )
    session.add(player)
    await session.flush()
    return player


#: What a player may change on their own linked profile (docs/app-flow.md:
#: "They may always edit only their own position and condition").
SELF_EDITABLE = frozenset({"condition", "field_position"})


async def update_player(
    session: AsyncSession,
    *,
    player: PlayerProfile,
    changes: dict[str, object],
    actor_user_id: UUID,
    actor_is_admin: bool,
) -> PlayerProfile:
    if not actor_is_admin:
        if player.owner_user_id != actor_user_id:
            raise PermissionDenied("Only group admins may edit other players")
        forbidden = set(changes) - SELF_EDITABLE
        if forbidden:
            raise PermissionDenied("You may only change your own position and condition")

    if "display_name" in changes:
        name = str(changes["display_name"]).strip()
        assert player.group_id is not None
        await _require_unique_name(
            session, group_id=player.group_id, display_name=name, except_id=player.id
        )
        changes = {**changes, "display_name": name}

    for field, value in changes.items():
        setattr(player, field, value)
    await session.flush()
    await session.refresh(player)
    return player


async def archive_player(session: AsyncSession, *, player: PlayerProfile) -> None:
    """Rule 18: profiles with history are archived, never deleted.

    Only manual guests can be archived; a member's linked profile goes away
    when they leave the group. A guest still on an open game list must be
    removed from that list first, so no roster changes silently.
    """
    if player.owner_user_id is not None:
        raise Conflict("Only guest players can be removed from the directory")

    on_open_list = (
        await session.execute(
            select(func.count())
            .select_from(GameParticipant)
            .join(Game, Game.id == GameParticipant.game_id)
            .where(
                GameParticipant.player_id == player.id,
                GameParticipant.status.in_(ACTIVE_STATUSES),
                Game.status == GameStatus.ACTIVE,
            )
        )
    ).scalar_one()
    if on_open_list:
        raise Conflict("Remove this player from their open games first")

    player.archived_at = utcnow()
    await session.flush()

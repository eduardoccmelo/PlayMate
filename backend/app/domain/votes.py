"""Admin skill ballots and the profile averages they drive.

docs/backend-schema.md, `player_skill_votes`: only active admins vote, every
ballot has equal weight, a vote recomputes the half-up average at once, and
no client may overwrite the aggregate without recording a ballot.
"""

from math import floor
from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import GroupMembership, PlayerProfile, PlayerSkillVote
from app.domain.enums import GroupRole, PlayerMobility, SkillAttribute

#: Ballot values for mobility, matching the frontend's 1-3 scale.
MOBILITY_TO_VALUE = {
    PlayerMobility.LENTO: 1,
    PlayerMobility.NEUTRO: 2,
    PlayerMobility.RAPIDO: 3,
}
VALUE_TO_MOBILITY = {value: mobility for mobility, value in MOBILITY_TO_VALUE.items()}


def half_up_mean(values: list[int]) -> int:
    """Round .5 upward, like the frontend's Math.floor(mean + 0.5)."""
    return floor(sum(values) / len(values) + 0.5)


async def active_admin_ids(session: AsyncSession, group_id: UUID) -> set[UUID]:
    rows = await session.execute(
        select(GroupMembership.user_id).where(
            GroupMembership.group_id == group_id,
            GroupMembership.left_at.is_(None),
            GroupMembership.role.in_((GroupRole.OWNER, GroupRole.ADMIN)),
        )
    )
    return set(rows.scalars().all())


async def list_votes(session: AsyncSession, *, group_id: UUID) -> list[PlayerSkillVote]:
    """Ballots that currently count: those of active admins only."""
    admins = await active_admin_ids(session, group_id)
    rows = await session.execute(
        select(PlayerSkillVote).where(PlayerSkillVote.group_id == group_id)
    )
    return [vote for vote in rows.scalars().all() if vote.admin_user_id in admins]


async def recompute(session: AsyncSession, player: PlayerProfile) -> None:
    """Apply the current ballots to the profile. Without any ballot for an
    attribute the profile keeps its existing value."""
    assert player.group_id is not None
    admins = await active_admin_ids(session, player.group_id)
    rows = await session.execute(
        select(PlayerSkillVote).where(PlayerSkillVote.player_id == player.id)
    )
    votes = [vote for vote in rows.scalars().all() if vote.admin_user_id in admins]
    levels = [vote.value for vote in votes if vote.attribute is SkillAttribute.LEVEL]
    mobilities = [vote.value for vote in votes if vote.attribute is SkillAttribute.MOBILITY]
    if levels:
        player.level = half_up_mean(levels)
    if mobilities:
        player.mobility = VALUE_TO_MOBILITY[half_up_mean(mobilities)]
    await session.flush()


async def cast_vote(
    session: AsyncSession,
    *,
    player: PlayerProfile,
    admin_user_id: UUID,
    attribute: SkillAttribute,
    value: int | None,
) -> None:
    """Record, change or (with None) withdraw one ballot. Callers check that
    the voter is an active admin of the player's group."""
    assert player.group_id is not None
    key = (
        PlayerSkillVote.group_id == player.group_id,
        PlayerSkillVote.player_id == player.id,
        PlayerSkillVote.admin_user_id == admin_user_id,
        PlayerSkillVote.attribute == attribute,
    )
    if value is None:
        await session.execute(delete(PlayerSkillVote).where(*key))
        return
    existing = (await session.execute(select(PlayerSkillVote).where(*key))).scalar_one_or_none()
    if existing is None:
        session.add(
            PlayerSkillVote(
                group_id=player.group_id,
                player_id=player.id,
                admin_user_id=admin_user_id,
                attribute=attribute,
                value=value,
            )
        )
    else:
        existing.value = value
    await session.flush()

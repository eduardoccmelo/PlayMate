from uuid import UUID

from fastapi import APIRouter
from sqlalchemy import select

from app.api.deps import (
    GroupAdminDep,
    GroupContext,
    GroupMemberDep,
    GroupOwnerDep,
    SessionDep,
    ViewerDep,
)
from app.db.models import GroupMembership, PlayerProfile, User
from app.domain import groups as groups_domain
from app.domain import players as players_domain
from app.domain import votes as votes_domain
from app.domain.enums import SkillAttribute
from app.domain.errors import ValidationFailed
from app.schemas.groups import (
    ChangePasscodeRequest,
    CreateGroupRequest,
    CreateGroupResponse,
    CreatePlayerRequest,
    GroupResponse,
    JoinCodeResponse,
    JoinGroupRequest,
    MemberResponse,
    PlayerResponse,
    RenameGroupRequest,
    UpdatePlayerRequest,
    VoteRequest,
    VoteResponse,
)

router = APIRouter(tags=["groups"])


@router.get("/groups", response_model=list[GroupResponse])
async def list_groups(session: SessionDep, viewer: ViewerDep) -> list[GroupResponse]:
    memberships = await groups_domain.list_memberships(session, user_id=viewer.user.id)
    responses: list[GroupResponse] = []
    for membership in memberships:
        group = await groups_domain.get_group(session, membership.group_id)
        responses.append(
            GroupResponse(
                id=group.id,
                name=group.name,
                public_slug=group.public_slug,
                timezone=group.timezone,
                role=membership.role,
            )
        )
    return responses


@router.post("/groups", response_model=CreateGroupResponse, status_code=201)
async def create_group(
    body: CreateGroupRequest, session: SessionDep, viewer: ViewerDep
) -> CreateGroupResponse:
    created = await groups_domain.create_group(
        session,
        name=body.name,
        creator_id=viewer.user.id,
        organizer_passcode=body.organizer_passcode,
        timezone=body.timezone,
    )
    return CreateGroupResponse(
        group=GroupResponse.model_validate(created.group), join_code=created.join_code
    )


@router.post("/groups/join", response_model=GroupResponse)
async def join_group(
    body: JoinGroupRequest, session: SessionDep, viewer: ViewerDep
) -> GroupResponse:
    membership = await groups_domain.join_group(
        session,
        join_code=body.join_code,
        user_id=viewer.user.id,
        display_name=body.display_name,
        role=body.role,
        organizer_passcode=body.organizer_passcode,
    )
    group = await groups_domain.get_group(session, membership.group_id)
    return GroupResponse(
        id=group.id,
        name=group.name,
        public_slug=group.public_slug,
        timezone=group.timezone,
        role=membership.role,
    )


@router.get("/groups/{group_id}", response_model=GroupResponse)
async def read_group(context: GroupMemberDep) -> GroupResponse:
    return GroupResponse(
        id=context.group.id,
        name=context.group.name,
        public_slug=context.group.public_slug,
        timezone=context.group.timezone,
        role=context.membership.role,
    )


@router.post("/groups/{group_id}/passcode", status_code=204)
async def change_passcode(
    body: ChangePasscodeRequest, context: GroupOwnerDep, session: SessionDep
) -> None:
    await groups_domain.change_passcode(
        session,
        group_id=context.group.id,
        current_passcode=body.current_passcode,
        new_passcode=body.new_passcode,
    )


@router.post("/groups/{group_id}/leave", status_code=204)
async def leave_group(context: GroupMemberDep, session: SessionDep) -> None:
    await groups_domain.leave_group(
        session, group_id=context.group.id, user_id=context.viewer.user.id
    )


@router.patch("/groups/{group_id}", response_model=GroupResponse)
async def rename_group(
    body: RenameGroupRequest, context: GroupAdminDep, session: SessionDep
) -> GroupResponse:
    group = await groups_domain.rename_group(session, group_id=context.group.id, name=body.name)
    return GroupResponse(
        id=group.id,
        name=group.name,
        public_slug=group.public_slug,
        timezone=group.timezone,
        role=context.membership.role,
    )


@router.post("/groups/{group_id}/join-code", response_model=JoinCodeResponse)
async def rotate_join_code(context: GroupAdminDep, session: SessionDep) -> JoinCodeResponse:
    join_code = await groups_domain.rotate_join_code(session, group_id=context.group.id)
    return JoinCodeResponse(join_code=join_code)


def _player_response(
    player: PlayerProfile, context: GroupContext, member_ids: set[UUID] | None = None
) -> PlayerResponse:
    # Participants never see skill ratings, including their own (rule:
    # ratings come only from admin votes).
    show_skill = context.is_admin
    # A game-only guest: an organizer's manual guest, or an account that
    # reached a game by code without joining the group.
    game_only = player.scope_game_id is not None or (
        member_ids is not None
        and player.owner_user_id is not None
        and player.owner_user_id not in member_ids
    )
    return PlayerResponse(
        access_scope="game" if game_only else "group",
        id=player.id,
        display_name=player.display_name,
        owner_user_id=player.owner_user_id,
        is_guest=player.owner_user_id is None,
        level=player.level if show_skill else None,
        mobility=player.mobility if show_skill else None,
        condition=player.condition,
        position=player.field_position,
    )


@router.get("/groups/{group_id}/players", response_model=list[PlayerResponse])
async def list_players(context: GroupMemberDep, session: SessionDep) -> list[PlayerResponse]:
    players = await players_domain.list_players(session, group_id=context.group.id)
    member_ids = set(
        (
            await session.execute(
                select(GroupMembership.user_id).where(
                    GroupMembership.group_id == context.group.id,
                    GroupMembership.left_at.is_(None),
                )
            )
        ).scalars().all()
    )
    return [_player_response(player, context, member_ids) for player in players]


@router.post("/groups/{group_id}/players", response_model=PlayerResponse, status_code=201)
async def create_player(
    body: CreatePlayerRequest, context: GroupAdminDep, session: SessionDep
) -> PlayerResponse:
    player = await players_domain.create_guest(
        session,
        group_id=context.group.id,
        display_name=body.display_name,
        level=body.level,
        mobility=body.mobility,
        condition=body.condition,
        position=body.position,
        creator_user_id=context.viewer.user.id,
    )
    return _player_response(player, context)


@router.patch("/groups/{group_id}/players/{player_id}", response_model=PlayerResponse)
async def update_player(
    player_id: UUID, body: UpdatePlayerRequest, context: GroupMemberDep, session: SessionDep
) -> PlayerResponse:
    player = await players_domain.get_player(
        session, group_id=context.group.id, player_id=player_id
    )
    changes = body.model_dump(exclude_unset=True)
    if "position" in changes:
        changes["field_position"] = changes.pop("position")
    # None means "not sent" for every column that cannot be cleared.
    changes = {
        field: value for field, value in changes.items() if value is not None or field == "level"
    }
    player = await players_domain.update_player(
        session,
        player=player,
        changes=changes,
        actor_user_id=context.viewer.user.id,
        actor_is_admin=context.is_admin,
    )
    return _player_response(player, context)


@router.delete("/groups/{group_id}/players/{player_id}", status_code=204)
async def archive_player(player_id: UUID, context: GroupAdminDep, session: SessionDep) -> None:
    player = await players_domain.get_player(
        session, group_id=context.group.id, player_id=player_id
    )
    await players_domain.archive_player(session, player=player)


@router.get("/groups/{group_id}/members", response_model=list[MemberResponse])
async def list_members(context: GroupMemberDep, session: SessionDep) -> list[MemberResponse]:
    rows = await session.execute(
        select(GroupMembership, User, PlayerProfile.id)
        .join(User, User.id == GroupMembership.user_id)
        .outerjoin(
            PlayerProfile,
            (PlayerProfile.group_id == GroupMembership.group_id)
            & (PlayerProfile.owner_user_id == GroupMembership.user_id),
        )
        .where(GroupMembership.group_id == context.group.id, GroupMembership.left_at.is_(None))
        .order_by(GroupMembership.joined_at)
    )
    return [
        MemberResponse(
            user_id=membership.user_id,
            display_name=user.display_name,
            role=membership.role,
            joined_at=membership.joined_at,
            player_id=player_id,
        )
        for membership, user, player_id in rows.all()
    ]


@router.get("/groups/{group_id}/votes", response_model=list[VoteResponse])
async def list_votes(context: GroupAdminDep, session: SessionDep) -> list[VoteResponse]:
    """Admins only: ballots are skill data (docs/app-flow.md)."""
    votes = await votes_domain.list_votes(session, group_id=context.group.id)
    return [VoteResponse.model_validate(vote) for vote in votes]


#: Valid ballot values per attribute.
VOTE_RANGES = {SkillAttribute.LEVEL: range(1, 6), SkillAttribute.MOBILITY: range(1, 4)}


@router.put(
    "/groups/{group_id}/players/{player_id}/votes/{attribute}", response_model=PlayerResponse
)
async def cast_vote(
    player_id: UUID,
    attribute: SkillAttribute,
    body: VoteRequest,
    context: GroupAdminDep,
    session: SessionDep,
) -> PlayerResponse:
    """Record, change or (value null) withdraw the caller's ballot. Admins
    may vote on every player in the group, including themselves."""
    if body.value is not None and body.value not in VOTE_RANGES[attribute]:
        raise ValidationFailed(f"A {attribute} vote must be in {VOTE_RANGES[attribute]}")
    player = await players_domain.get_player(
        session, group_id=context.group.id, player_id=player_id
    )
    await votes_domain.cast_vote(
        session,
        player=player,
        admin_user_id=context.viewer.user.id,
        attribute=attribute,
        value=body.value,
    )
    await votes_domain.recompute(session, player)
    await session.refresh(player)
    return _player_response(player, context)

from uuid import UUID

from pydantic import Field

from app.domain.enums import GroupRole, PlayerCondition, PlayerMobility, PlayerPosition
from app.schemas.common import CamelModel


class CreateGroupRequest(CamelModel):
    name: str
    organizer_passcode: str
    timezone: str = "Europe/Lisbon"


class GroupResponse(CamelModel):
    id: UUID
    name: str
    public_slug: str
    timezone: str
    role: GroupRole | None = None


class CreateGroupResponse(CamelModel):
    group: GroupResponse
    #: Shown once, at creation. Only the hash is stored.
    join_code: str


class JoinGroupRequest(CamelModel):
    join_code: str
    display_name: str
    role: GroupRole = GroupRole.PARTICIPANT
    organizer_passcode: str | None = None


class ChangePasscodeRequest(CamelModel):
    current_passcode: str
    new_passcode: str


class RenameGroupRequest(CamelModel):
    name: str = Field(min_length=1, max_length=80)


class JoinCodeResponse(CamelModel):
    join_code: str


class PlayerResponse(CamelModel):
    id: UUID
    display_name: str
    #: The linked account, or None for a manual guest.
    owner_user_id: UUID | None
    is_guest: bool
    #: Skill attributes are withheld (None) from non-admins (docs/app-flow.md).
    level: int | None
    mobility: PlayerMobility | None
    condition: PlayerCondition
    position: PlayerPosition


class CreatePlayerRequest(CamelModel):
    display_name: str = Field(min_length=1, max_length=80)
    level: int | None = Field(default=None, ge=1, le=5)
    mobility: PlayerMobility = PlayerMobility.NEUTRO
    condition: PlayerCondition = PlayerCondition.NEUTRO
    position: PlayerPosition = PlayerPosition.NEUTRO


class UpdatePlayerRequest(CamelModel):
    display_name: str | None = Field(default=None, min_length=1, max_length=80)
    level: int | None = Field(default=None, ge=1, le=5)
    mobility: PlayerMobility | None = None
    condition: PlayerCondition | None = None
    position: PlayerPosition | None = None

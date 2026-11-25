"""Participant-created games, game codes and game-only guests over HTTP."""

from collections.abc import AsyncIterator

import pytest
from httpx import ASGITransport, AsyncClient

from tests.test_api import auth, sign_in

pytestmark = pytest.mark.db

GAME = {"gameDate": "2026-12-01", "startTime": "19:00:00", "durationMinutes": 75, "maxPlayers": 4}


@pytest.fixture
async def client(clean_database: str) -> AsyncIterator[AsyncClient]:
    from app.main import app

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as http:
        yield http


async def group_with_member(client: AsyncClient) -> tuple[str, str, str]:
    """(group_id, admin_token, member_token)"""
    admin = await sign_in(client, "organizer@example.com", "Organizer")
    created = await client.post(
        "/v1/groups", json={"name": "City Night", "organizerPasscode": "hunter2"},
        headers=auth(admin),
    )
    group_id, code = created.json()["group"]["id"], created.json()["joinCode"]
    member = await sign_in(client, "member@example.com", "Member")
    await client.post(
        "/v1/groups/join", json={"joinCode": code, "displayName": "Member"}, headers=auth(member)
    )
    return group_id, admin, member


async def test_a_participant_organizes_only_their_own_game(client: AsyncClient) -> None:
    group_id, admin, member = await group_with_member(client)
    own = await client.post(f"/v1/groups/{group_id}/games", json=GAME, headers=auth(member))
    assert own.status_code == 201, own.text
    own_game = own.json()["game"]
    assert own_game["createdByRole"] == "participant"

    detail = (await client.get(f"/v1/games/{own_game['id']}", headers=auth(member))).json()
    assert detail["viewerAccess"]["canManageGame"] is True
    assert detail["viewerAccess"]["canDrawTeams"] is True
    assert detail["viewerAccess"]["kind"] == "member"

    admins_game = (
        await client.post(f"/v1/groups/{group_id}/games", json=GAME, headers=auth(admin))
    ).json()["game"]
    assert admins_game["createdByRole"] == "admin"
    other = (await client.get(f"/v1/games/{admins_game['id']}", headers=auth(member))).json()
    assert other["viewerAccess"]["canManageGame"] is False
    refused = await client.patch(
        f"/v1/games/{admins_game['id']}", json={"location": "X"}, headers=auth(member)
    )
    assert refused.status_code == 403

    # The group admin still manages the participant's game.
    as_admin = (await client.get(f"/v1/games/{own_game['id']}", headers=auth(admin))).json()
    assert as_admin["viewerAccess"]["canManageGame"] is True

    # Creating a game grants no group-admin rights.
    assert (
        await client.post(
            f"/v1/groups/{group_id}/players", json={"displayName": "X"}, headers=auth(member)
        )
    ).status_code == 403


async def test_a_participant_organizer_does_not_see_which_admin_drew(
    client: AsyncClient,
) -> None:
    group_id, admin, member = await group_with_member(client)
    game_id = (
        await client.post(f"/v1/groups/{group_id}/games", json=GAME, headers=auth(member))
    ).json()["game"]["id"]
    for name in ("Ann", "Bob"):
        added = await client.post(
            f"/v1/games/{game_id}/guests", json={"displayName": name}, headers=auth(member)
        )
        assert added.status_code == 201, added.text
    drawn = await client.post(f"/v1/games/{game_id}/team-balance", headers=auth(admin))
    assert drawn.status_code == 200, drawn.text

    as_organizer = (await client.get(f"/v1/games/{game_id}", headers=auth(member))).json()
    assert as_organizer["balance"]["latest"]["triggeredByName"] is None
    as_admin = (await client.get(f"/v1/games/{game_id}", headers=auth(admin))).json()
    assert as_admin["balance"]["latest"]["triggeredByName"] == "Organizer"


async def test_an_organizer_guest_stays_out_of_the_voting_board(client: AsyncClient) -> None:
    group_id, admin, member = await group_with_member(client)
    game_id = (
        await client.post(f"/v1/groups/{group_id}/games", json=GAME, headers=auth(member))
    ).json()["game"]["id"]
    added = await client.post(
        f"/v1/games/{game_id}/guests", json={"displayName": "Walk-in"}, headers=auth(member)
    )
    assert [p["displayName"] for p in added.json()["confirmed"]] == ["Walk-in"]

    players = (await client.get(f"/v1/groups/{group_id}/players", headers=auth(admin))).json()
    walk_in = next(p for p in players if p["displayName"] == "Walk-in")
    assert walk_in["accessScope"] == "game" and walk_in["isGuest"] is True


async def test_a_non_member_joins_one_game_by_code_without_joining_the_group(
    client: AsyncClient,
) -> None:
    group_id, admin, _ = await group_with_member(client)
    game_id = (
        await client.post(f"/v1/groups/{group_id}/games", json=GAME, headers=auth(admin))
    ).json()["game"]["id"]
    code = (
        await client.post(f"/v1/games/{game_id}/join-code", headers=auth(admin))
    ).json()["joinCode"]

    guest = await sign_in(client, "guest@example.com", "Guest Gus")
    joined = await client.post(
        "/v1/games/join", json={"joinCode": code.lower()}, headers=auth(guest)
    )
    assert joined.status_code == 200, joined.text
    body = joined.json()
    assert body["viewerAccess"]["kind"] == "guest"
    assert body["viewerAccess"]["canViewGroupPlayers"] is False
    assert [p["displayName"] for p in body["confirmed"]] == ["Guest Gus"]

    # Joining again is harmless, and grants no membership.
    again = await client.post("/v1/games/join", json={"joinCode": code}, headers=auth(guest))
    assert again.status_code == 200
    assert (await client.get("/v1/groups", headers=auth(guest))).json() == []
    assert (
        await client.get(f"/v1/groups/{group_id}/players", headers=auth(guest))
    ).status_code == 403

    mine = (await client.get("/v1/me/games", headers=auth(guest))).json()
    assert [(g["groupName"], g["detail"]["game"]["id"]) for g in mine] == [
        ("City Night", game_id)
    ]

    # The guest manages their own entry only.
    entry = body["confirmed"][0]
    left = await client.post(
        f"/v1/games/{game_id}/participants/{entry['id']}/leave", headers=auth(guest)
    )
    assert left.status_code == 200, left.text

    players = (await client.get(f"/v1/groups/{group_id}/players", headers=auth(admin))).json()
    assert next(p for p in players if p["displayName"] == "Guest Gus")["accessScope"] == "game"


async def test_a_member_joining_by_code_uses_their_group_profile(client: AsyncClient) -> None:
    group_id, admin, member = await group_with_member(client)
    game_id = (
        await client.post(f"/v1/groups/{group_id}/games", json=GAME, headers=auth(admin))
    ).json()["game"]["id"]
    code = (
        await client.post(f"/v1/games/{game_id}/join-code", headers=auth(admin))
    ).json()["joinCode"]
    joined = await client.post("/v1/games/join", json={"joinCode": code}, headers=auth(member))
    assert joined.json()["viewerAccess"]["kind"] == "member"
    assert (await client.get("/v1/me/games", headers=auth(member))).json() == []


async def test_a_rotated_or_unknown_game_code_is_refused(client: AsyncClient) -> None:
    group_id, admin, member = await group_with_member(client)
    game_id = (
        await client.post(f"/v1/groups/{group_id}/games", json=GAME, headers=auth(admin))
    ).json()["game"]["id"]
    first = (await client.post(f"/v1/games/{game_id}/join-code", headers=auth(admin))).json()
    await client.post(f"/v1/games/{game_id}/join-code", headers=auth(admin))
    guest = await sign_in(client, "guest@example.com", "Guest")
    stale = await client.post(
        "/v1/games/join", json={"joinCode": first["joinCode"]}, headers=auth(guest)
    )
    assert stale.status_code == 404
    assert (
        await client.post(f"/v1/games/{game_id}/join-code", headers=auth(member))
    ).status_code == 403

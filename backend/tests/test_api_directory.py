"""Group player directory, group admin actions and game deletion over HTTP."""

from collections.abc import AsyncIterator

import pytest
from httpx import ASGITransport, AsyncClient

from tests.test_api import auth, sign_in

pytestmark = pytest.mark.db

GAME = {"gameDate": "2026-06-01", "startTime": "19:00:00", "durationMinutes": 75, "maxPlayers": 4}


@pytest.fixture
async def client(clean_database: str) -> AsyncIterator[AsyncClient]:
    from app.main import app

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as http:
        yield http


async def group_with_member(client: AsyncClient) -> tuple[str, str, str, str]:
    """(group_id, join_code, admin_token, member_token)"""
    admin = await sign_in(client, "organizer@example.com", "Organizer")
    created = await client.post(
        "/v1/groups",
        json={"name": "City Night", "organizerPasscode": "hunter2"},
        headers=auth(admin),
    )
    assert created.status_code == 201, created.text
    group_id = created.json()["group"]["id"]
    join_code = created.json()["joinCode"]
    member = await sign_in(client, "member@example.com", "Member")
    joined = await client.post(
        "/v1/groups/join",
        json={"joinCode": join_code, "displayName": "Member"},
        headers=auth(member),
    )
    assert joined.status_code == 200, joined.text
    return group_id, join_code, admin, member


async def test_the_directory_lists_linked_profiles_and_hides_skill_from_members(
    client: AsyncClient,
) -> None:
    group_id, _, admin, member = await group_with_member(client)

    as_admin = await client.get(f"/v1/groups/{group_id}/players", headers=auth(admin))
    assert as_admin.status_code == 200, as_admin.text
    names = {p["displayName"]: p for p in as_admin.json()}
    assert set(names) == {"Organizer", "Member"}
    assert names["Member"]["isGuest"] is False
    assert names["Member"]["ownerUserId"] is not None

    as_member = await client.get(f"/v1/groups/{group_id}/players", headers=auth(member))
    assert all(p["level"] is None and p["mobility"] is None for p in as_member.json())

    outsider = await sign_in(client, "outsider@example.com", "Outsider")
    refused = await client.get(f"/v1/groups/{group_id}/players", headers=auth(outsider))
    assert refused.status_code == 403


async def test_only_admins_create_guests_and_names_stay_unique(client: AsyncClient) -> None:
    group_id, _, admin, member = await group_with_member(client)
    body = {"displayName": "Guest One", "level": 4, "mobility": "rapido"}

    refused = await client.post(f"/v1/groups/{group_id}/players", json=body, headers=auth(member))
    assert refused.status_code == 403

    created = await client.post(f"/v1/groups/{group_id}/players", json=body, headers=auth(admin))
    assert created.status_code == 201, created.text
    guest = created.json()
    assert guest["isGuest"] is True
    assert guest["level"] == 4

    duplicate = await client.post(
        f"/v1/groups/{group_id}/players",
        json={"displayName": "  guest   ONE "},
        headers=auth(admin),
    )
    assert duplicate.status_code == 409


async def test_a_member_edits_only_their_own_position_and_condition(
    client: AsyncClient,
) -> None:
    group_id, _, admin, member = await group_with_member(client)
    players = (await client.get(f"/v1/groups/{group_id}/players", headers=auth(admin))).json()
    own = next(p for p in players if p["displayName"] == "Member")
    other = next(p for p in players if p["displayName"] == "Organizer")
    url = f"/v1/groups/{group_id}/players"

    ok = await client.patch(
        f"{url}/{own['id']}", json={"position": "goleiro", "condition": "boa"}, headers=auth(member)
    )
    assert ok.status_code == 200, ok.text
    assert ok.json()["position"] == "goleiro"

    own_level = await client.patch(f"{url}/{own['id']}", json={"level": 5}, headers=auth(member))
    assert own_level.status_code == 403
    someone_else = await client.patch(
        f"{url}/{other['id']}", json={"condition": "ruim"}, headers=auth(member)
    )
    assert someone_else.status_code == 403

    admin_edit = await client.patch(f"{url}/{own['id']}", json={"level": 2}, headers=auth(admin))
    assert admin_edit.status_code == 200
    assert admin_edit.json()["level"] == 2


async def test_a_guest_on_an_open_game_cannot_be_archived_until_removed(
    client: AsyncClient,
) -> None:
    group_id, _, admin, _ = await group_with_member(client)
    guest = (
        await client.post(
            f"/v1/groups/{group_id}/players", json={"displayName": "Guest"}, headers=auth(admin)
        )
    ).json()
    game_id = (
        await client.post(f"/v1/groups/{group_id}/games", json=GAME, headers=auth(admin))
    ).json()["game"]["id"]
    joined = await client.post(
        f"/v1/games/{game_id}/participants", json={"playerId": guest["id"]}, headers=auth(admin)
    )
    assert joined.status_code == 201, joined.text
    entry = joined.json()["confirmed"][0]
    assert entry["userId"] is None

    url = f"/v1/groups/{group_id}/players/{guest['id']}"
    assert (await client.delete(url, headers=auth(admin))).status_code == 409

    removed = await client.delete(
        f"/v1/games/{game_id}/participants/{entry['id']}", headers=auth(admin)
    )
    assert removed.status_code == 200, removed.text
    assert (await client.delete(url, headers=auth(admin))).status_code == 204

    players = (await client.get(f"/v1/groups/{group_id}/players", headers=auth(admin))).json()
    assert "Guest" not in {p["displayName"] for p in players}
    rejoin = await client.post(
        f"/v1/games/{game_id}/participants", json={"playerId": guest["id"]}, headers=auth(admin)
    )
    assert rejoin.status_code == 404


async def test_participants_report_their_owning_user(client: AsyncClient) -> None:
    group_id, _, admin, member = await group_with_member(client)
    me = (await client.get("/v1/me", headers=auth(member))).json()
    game = (
        await client.post(f"/v1/groups/{group_id}/games", json=GAME, headers=auth(admin))
    ).json()["game"]
    assert game["createdByUserId"] != me["id"]

    joined = await client.post(
        f"/v1/games/{game['id']}/participants", json={}, headers=auth(member)
    )
    assert joined.json()["confirmed"][0]["userId"] == me["id"]


async def test_admins_rename_and_rotate_the_join_code(client: AsyncClient) -> None:
    group_id, old_code, admin, member = await group_with_member(client)

    assert (
        await client.patch(f"/v1/groups/{group_id}", json={"name": "X"}, headers=auth(member))
    ).status_code == 403
    renamed = await client.patch(
        f"/v1/groups/{group_id}", json={"name": "Sunday League"}, headers=auth(admin)
    )
    assert renamed.status_code == 200, renamed.text
    assert renamed.json()["name"] == "Sunday League"

    assert (
        await client.post(f"/v1/groups/{group_id}/join-code", headers=auth(member))
    ).status_code == 403
    rotated = await client.post(f"/v1/groups/{group_id}/join-code", headers=auth(admin))
    assert rotated.status_code == 200, rotated.text
    new_code = rotated.json()["joinCode"]
    assert new_code != old_code

    newcomer = await sign_in(client, "new@example.com", "Newcomer")
    stale = await client.post(
        "/v1/groups/join",
        json={"joinCode": old_code, "displayName": "Newcomer"},
        headers=auth(newcomer),
    )
    assert stale.status_code == 404
    fresh = await client.post(
        "/v1/groups/join",
        json={"joinCode": new_code, "displayName": "Newcomer"},
        headers=auth(newcomer),
    )
    assert fresh.status_code == 200, fresh.text


async def test_deleting_a_cancelled_game_hides_it(client: AsyncClient) -> None:
    group_id, _, admin, member = await group_with_member(client)
    game_id = (
        await client.post(f"/v1/groups/{group_id}/games", json=GAME, headers=auth(admin))
    ).json()["game"]["id"]
    cancelled = await client.post(f"/v1/games/{game_id}/cancel", json={}, headers=auth(admin))
    assert cancelled.status_code == 200, cancelled.text

    assert (await client.delete(f"/v1/games/{game_id}", headers=auth(member))).status_code == 403
    assert (await client.delete(f"/v1/games/{game_id}", headers=auth(admin))).status_code == 204

    listed = await client.get(f"/v1/groups/{group_id}/games", headers=auth(admin))
    assert listed.json() == []
    assert (await client.get(f"/v1/games/{game_id}", headers=auth(admin))).status_code == 404

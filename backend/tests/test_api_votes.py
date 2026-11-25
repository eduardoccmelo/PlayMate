"""Admin skill ballots and the averages they drive, over HTTP."""

from collections.abc import AsyncIterator

import pytest
from httpx import ASGITransport, AsyncClient

from tests.test_api import auth, sign_in

pytestmark = pytest.mark.db


@pytest.fixture
async def client(clean_database: str) -> AsyncIterator[AsyncClient]:
    from app.main import app

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as http:
        yield http


async def two_admins_and_a_member(client: AsyncClient) -> tuple[str, str, str, str]:
    """(group_id, owner_token, admin_token, member_token)"""
    owner = await sign_in(client, "owner@example.com", "Owner")
    created = await client.post(
        "/v1/groups", json={"name": "City Night", "organizerPasscode": "hunter2"},
        headers=auth(owner),
    )
    group_id, code = created.json()["group"]["id"], created.json()["joinCode"]
    admin = await sign_in(client, "admin@example.com", "Admin")
    joined = await client.post(
        "/v1/groups/join",
        json={"joinCode": code, "displayName": "Admin", "role": "admin",
              "organizerPasscode": "hunter2"},
        headers=auth(admin),
    )
    assert joined.status_code == 200, joined.text
    member = await sign_in(client, "member@example.com", "Member")
    await client.post(
        "/v1/groups/join", json={"joinCode": code, "displayName": "Member"},
        headers=auth(member),
    )
    return group_id, owner, admin, member


async def guest_id(client: AsyncClient, group_id: str, token: str, **body: object) -> str:
    created = await client.post(
        f"/v1/groups/{group_id}/players", json={"displayName": "Guest", **body},
        headers=auth(token),
    )
    assert created.status_code == 201, created.text
    return str(created.json()["id"])


async def test_votes_average_half_up_and_only_admins_vote(client: AsyncClient) -> None:
    group_id, owner, admin, member = await two_admins_and_a_member(client)
    player = await guest_id(client, group_id, owner, level=4)
    url = f"/v1/groups/{group_id}/players/{player}/votes"

    refused = await client.put(f"{url}/level", json={"value": 5}, headers=auth(member))
    assert refused.status_code == 403

    # The creator's entered level is their first ballot: (4 + 5) / 2 = 4.5 -> 5.
    voted = await client.put(f"{url}/level", json={"value": 5}, headers=auth(admin))
    assert voted.status_code == 200, voted.text
    assert voted.json()["level"] == 5

    # Mobility ballots: creator recorded "neutro" (2), admin votes 3 -> 2.5 -> 3.
    fast = await client.put(f"{url}/mobility", json={"value": 3}, headers=auth(admin))
    assert fast.json()["mobility"] == "rapido"

    out_of_range = await client.put(f"{url}/mobility", json={"value": 4}, headers=auth(admin))
    assert out_of_range.status_code == 422

    ballots = await client.get(f"/v1/groups/{group_id}/votes", headers=auth(owner))
    assert {(b["attribute"], b["value"]) for b in ballots.json()} == {
        ("level", 4), ("level", 5), ("mobility", 2), ("mobility", 3),
    }
    assert (await client.get(f"/v1/groups/{group_id}/votes", headers=auth(member))).status_code == 403


async def test_withdrawing_a_ballot_recomputes_from_the_rest(client: AsyncClient) -> None:
    group_id, owner, admin, _ = await two_admins_and_a_member(client)
    player = await guest_id(client, group_id, owner, level=2)
    url = f"/v1/groups/{group_id}/players/{player}/votes/level"
    assert (await client.put(url, json={"value": 5}, headers=auth(admin))).json()["level"] == 4

    withdrawn = await client.put(url, json={"value": None}, headers=auth(admin))
    assert withdrawn.json()["level"] == 2


async def test_an_admin_level_edit_is_recorded_as_their_ballot(client: AsyncClient) -> None:
    group_id, owner, admin, _ = await two_admins_and_a_member(client)
    player = await guest_id(client, group_id, owner, level=1)

    edited = await client.patch(
        f"/v1/groups/{group_id}/players/{player}", json={"level": 4}, headers=auth(admin)
    )
    # Not overwritten to 4: the owner's ballot of 1 still counts -> 2.5 -> 3.
    assert edited.json()["level"] == 3
    ballots = (await client.get(f"/v1/groups/{group_id}/votes", headers=auth(owner))).json()
    assert sorted(b["value"] for b in ballots if b["attribute"] == "level") == [1, 4]


async def test_a_departing_admins_ballots_stop_counting(client: AsyncClient) -> None:
    group_id, owner, admin, _ = await two_admins_and_a_member(client)
    player = await guest_id(client, group_id, owner, level=1)
    url = f"/v1/groups/{group_id}/players/{player}/votes/level"
    assert (await client.put(url, json={"value": 5}, headers=auth(admin))).json()["level"] == 3

    left = await client.post(f"/v1/groups/{group_id}/leave", headers=auth(admin))
    assert left.status_code == 204
    players = (await client.get(f"/v1/groups/{group_id}/players", headers=auth(owner))).json()
    assert next(p for p in players if p["id"] == player)["level"] == 1


async def test_members_lists_roles_and_linked_profiles(client: AsyncClient) -> None:
    group_id, _, _, member = await two_admins_and_a_member(client)
    members = (await client.get(f"/v1/groups/{group_id}/members", headers=auth(member))).json()
    assert [(m["displayName"], m["role"]) for m in members] == [
        ("Owner", "owner"), ("Admin", "admin"), ("Member", "participant"),
    ]
    assert all(m["playerId"] for m in members)

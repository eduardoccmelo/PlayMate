"""Payment tracking, the per-player deadline and overdue handling over HTTP."""

from collections.abc import AsyncIterator

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from tests.test_api import auth, sign_in

pytestmark = pytest.mark.db

GAME = {"gameDate": "2026-12-01", "startTime": "19:00:00", "durationMinutes": 75, "maxPlayers": 2}


@pytest.fixture
async def client(clean_database: str) -> AsyncIterator[AsyncClient]:
    from app.main import app

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as http:
        yield http


async def admin_group(client: AsyncClient) -> tuple[str, str, str]:
    """(group_id, join_code, admin_token)"""
    token = await sign_in(client, "organizer@example.com", "Organizer")
    created = await client.post(
        "/v1/groups",
        json={"name": "City Night", "organizerPasscode": "hunter2"},
        headers=auth(token),
    )
    body = created.json()
    return body["group"]["id"], body["joinCode"], token


async def guest(client: AsyncClient, group_id: str, token: str, name: str) -> str:
    created = await client.post(
        f"/v1/groups/{group_id}/players", json={"displayName": name, "level": 3},
        headers=auth(token),
    )
    assert created.status_code == 201, created.text
    return str(created.json()["id"])


async def expire(database_url: str, game_id: str, name: str) -> None:
    """Move one entry's deadline into the past, as if days had gone by."""
    engine = create_async_engine(database_url)
    async with engine.begin() as connection:
        await connection.execute(
            text(
                "UPDATE game_participants SET payment_due_at = now() - interval '1 minute'"
                " WHERE game_id = :game AND display_name_snapshot = :name"
            ),
            {"game": game_id, "name": name},
        )
    await engine.dispose()


async def test_tracking_without_payment_details_survives_a_reload(client: AsyncClient) -> None:
    """The case from the PR #10 review."""
    group_id, _, token = await admin_group(client)
    created = await client.post(
        f"/v1/groups/{group_id}/games",
        json={**GAME, "paymentTrackingEnabled": True, "paymentDeadlineDays": 3},
        headers=auth(token),
    )
    assert created.status_code == 201, created.text
    game_id = created.json()["game"]["id"]

    reloaded = (await client.get(f"/v1/games/{game_id}", headers=auth(token))).json()["game"]
    assert reloaded["paymentTrackingEnabled"] is True
    assert reloaded["paymentDeadlineDays"] == 3
    assert reloaded["paymentInfo"] == ""


async def test_payment_fields_are_cleared_while_tracking_is_off(client: AsyncClient) -> None:
    group_id, _, token = await admin_group(client)
    created = await client.post(
        f"/v1/groups/{group_id}/games",
        json={**GAME, "paymentDeadlineDays": 3, "paymentInfo": "IBAN"},
        headers=auth(token),
    )
    game = created.json()["game"]
    assert game["paymentTrackingEnabled"] is False
    assert game["paymentDeadlineDays"] is None and game["paymentInfo"] == ""


async def test_a_payment_change_is_refused_when_tracking_is_off(client: AsyncClient) -> None:
    group_id, _, token = await admin_group(client)
    game_id = (
        await client.post(f"/v1/groups/{group_id}/games", json=GAME, headers=auth(token))
    ).json()["game"]["id"]
    joined = await client.post(f"/v1/games/{game_id}/participants", json={}, headers=auth(token))
    entry = joined.json()["confirmed"][0]
    assert entry["paymentDueAt"] is None

    refused = await client.patch(
        f"/v1/games/{game_id}/participants/{entry['id']}/payment",
        json={"paid": True},
        headers=auth(token),
    )
    assert refused.status_code == 409


async def test_joining_sets_a_deadline_and_turning_tracking_off_clears_marks(
    client: AsyncClient,
) -> None:
    group_id, _, token = await admin_group(client)
    game_id = (
        await client.post(
            f"/v1/groups/{group_id}/games",
            json={**GAME, "paymentTrackingEnabled": True, "paymentDeadlineDays": 2},
            headers=auth(token),
        )
    ).json()["game"]["id"]
    joined = await client.post(f"/v1/games/{game_id}/participants", json={}, headers=auth(token))
    entry = joined.json()["confirmed"][0]
    assert entry["paymentDueAt"] is not None

    paid = await client.patch(
        f"/v1/games/{game_id}/participants/{entry['id']}/payment",
        json={"paid": True},
        headers=auth(token),
    )
    assert paid.status_code == 200, paid.text

    off = await client.patch(
        f"/v1/games/{game_id}", json={"paymentTrackingEnabled": False}, headers=auth(token)
    )
    assert off.status_code == 200, off.text
    assert off.json()["paymentDeadlineDays"] is None
    after = (await client.get(f"/v1/games/{game_id}", headers=auth(token))).json()
    assert after["confirmed"][0]["paid"] is False
    assert after["confirmed"][0]["paymentDueAt"] is None


async def test_enabling_a_deadline_later_gives_existing_entries_their_own(
    client: AsyncClient,
) -> None:
    group_id, _, token = await admin_group(client)
    game_id = (
        await client.post(
            f"/v1/groups/{group_id}/games",
            json={**GAME, "paymentTrackingEnabled": True},
            headers=auth(token),
        )
    ).json()["game"]["id"]
    await client.post(f"/v1/games/{game_id}/participants", json={}, headers=auth(token))

    updated = await client.patch(
        f"/v1/games/{game_id}", json={"paymentDeadlineDays": 5}, headers=auth(token)
    )
    assert updated.status_code == 200, updated.text
    detail = (await client.get(f"/v1/games/{game_id}", headers=auth(token))).json()
    assert detail["confirmed"][0]["paymentDueAt"] is not None

    cleared = await client.patch(
        f"/v1/games/{game_id}", json={"paymentDeadlineDays": None}, headers=auth(token)
    )
    assert cleared.json()["paymentDeadlineDays"] is None
    detail = (await client.get(f"/v1/games/{game_id}", headers=auth(token))).json()
    assert detail["confirmed"][0]["paymentDueAt"] is None


async def test_an_overdue_player_moves_to_the_waiting_list_and_stays_there(
    client: AsyncClient, clean_database: str
) -> None:
    group_id, _, token = await admin_group(client)
    game_id = (
        await client.post(
            f"/v1/groups/{group_id}/games",
            json={**GAME, "paymentTrackingEnabled": True, "paymentDeadlineDays": 1},
            headers=auth(token),
        )
    ).json()["game"]["id"]
    for name in ("Ann", "Bob", "Cid"):
        player_id = await guest(client, group_id, token, name)
        joined = await client.post(
            f"/v1/games/{game_id}/participants", json={"playerId": player_id},
            headers=auth(token),
        )
        assert joined.status_code == 201, joined.text

    await expire(clean_database, game_id, "Ann")
    detail = (await client.get(f"/v1/games/{game_id}", headers=auth(token))).json()
    assert [p["displayName"] for p in detail["confirmed"]] == ["Bob", "Cid"]
    assert [p["displayName"] for p in detail["waitingList"]] == ["Ann"]

    # A freed slot is not given back to the overdue player...
    bob = detail["confirmed"][0]
    await client.delete(f"/v1/games/{game_id}/participants/{bob['id']}", headers=auth(token))
    detail = (await client.get(f"/v1/games/{game_id}", headers=auth(token))).json()
    assert [p["displayName"] for p in detail["confirmed"]] == ["Cid"]
    assert [p["displayName"] for p in detail["waitingList"]] == ["Ann"]

    # ...until they pay, which makes them eligible for promotion again.
    ann = detail["waitingList"][0]
    paid = await client.patch(
        f"/v1/games/{game_id}/participants/{ann['id']}/payment",
        json={"paid": True},
        headers=auth(token),
    )
    assert paid.status_code == 200, paid.text
    detail = (await client.get(f"/v1/games/{game_id}", headers=auth(token))).json()
    assert [p["displayName"] for p in detail["confirmed"]] == ["Ann", "Cid"]

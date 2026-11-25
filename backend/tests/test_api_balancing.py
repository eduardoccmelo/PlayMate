"""Server-side team balancing over HTTP: quota, eligibility, invalidation."""

from collections.abc import AsyncIterator

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from tests.test_api import auth, sign_in

pytestmark = pytest.mark.db

GAME = {"gameDate": "2026-12-01", "startTime": "19:00:00", "durationMinutes": 75}


@pytest.fixture
async def client(clean_database: str) -> AsyncIterator[AsyncClient]:
    from app.main import app

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as http:
        yield http


async def sql(database_url: str, statement: str, **params: object) -> None:
    engine = create_async_engine(database_url)
    async with engine.begin() as connection:
        await connection.execute(text(statement), params)
    await engine.dispose()


async def setup(
    client: AsyncClient, names: list[str], max_players: int = 10, **game: object
) -> tuple[str, str, str, str]:
    """(group_id, game_id, admin_token, member_token) with guests listed."""
    token = await sign_in(client, "organizer@example.com", "Organizer")
    created = await client.post(
        "/v1/groups", json={"name": "City Night", "organizerPasscode": "hunter2"},
        headers=auth(token),
    )
    group_id, code = created.json()["group"]["id"], created.json()["joinCode"]
    member = await sign_in(client, "member@example.com", "Member")
    await client.post(
        "/v1/groups/join", json={"joinCode": code, "displayName": "Member"}, headers=auth(member)
    )
    game_id = (
        await client.post(
            f"/v1/groups/{group_id}/games", json={**GAME, "maxPlayers": max_players, **game},
            headers=auth(token),
        )
    ).json()["game"]["id"]
    for name in names:
        player = (
            await client.post(
                f"/v1/groups/{group_id}/players", json={"displayName": name, "level": 3},
                headers=auth(token),
            )
        ).json()["id"]
        joined = await client.post(
            f"/v1/games/{game_id}/participants", json={"playerId": player}, headers=auth(token)
        )
        assert joined.status_code == 201, joined.text
    return group_id, game_id, token, member


def split(detail: dict) -> tuple[frozenset[str], frozenset[str]]:
    def team(side: str) -> frozenset[str]:
        return frozenset(p["displayName"] for p in detail["confirmed"] if p["team"] == side)

    return team("A"), team("B")


async def test_three_draws_then_one_final_rebalance_inside_the_window(
    client: AsyncClient, clean_database: str
) -> None:
    _, game_id, token, member = await setup(client, ["Ann", "Bob", "Cid", "Dan"])
    url = f"/v1/games/{game_id}/team-balance"

    assert (await client.post(url, headers=auth(member))).status_code == 403
    for number in (1, 2, 3):
        drawn = await client.post(url, headers=auth(token))
        assert drawn.status_code == 200, drawn.text
        balance = drawn.json()["balance"]
        assert balance["standardCount"] == number
        assert balance["latest"]["standardBalanceNumber"] == number
        assert balance["latest"]["triggeredByName"] == "Organizer"
    assert (await client.post(url, headers=auth(token))).status_code == 409

    await sql(
        clean_database,
        "UPDATE games SET balance_window_starts_at = now() - interval '1 minute' WHERE id = :id",
        id=game_id,
    )
    final = await client.post(url, headers=auth(token))
    assert final.status_code == 200, final.text
    assert final.json()["balance"]["lateRebalanceUsed"] is True
    assert final.json()["balance"]["latest"]["triggerType"] == "late_rebalance"
    assert final.json()["balance"]["standardCount"] == 3
    assert (await client.post(url, headers=auth(token))).status_code == 409


async def test_a_redraw_prefers_a_different_split(client: AsyncClient) -> None:
    _, game_id, token, _ = await setup(client, ["Ann", "Bob", "Cid", "Dan"])
    url = f"/v1/games/{game_id}/team-balance"
    first = split((await client.post(url, headers=auth(token))).json())
    second = split((await client.post(url, headers=auth(token))).json())
    assert all(first) and all(second)
    assert set(second) != set(first), "swapping A and B is not a new split"


async def test_only_paid_players_are_eligible_with_payment_tracking(client: AsyncClient) -> None:
    _, game_id, token, _ = await setup(
        client, ["Ann", "Bob", "Cid"], paymentTrackingEnabled=True
    )
    url = f"/v1/games/{game_id}/team-balance"
    assert (await client.post(url, headers=auth(token))).status_code == 409

    detail = (await client.get(f"/v1/games/{game_id}", headers=auth(token))).json()
    for entry in detail["confirmed"][:2]:
        await client.patch(
            f"/v1/games/{game_id}/participants/{entry['id']}/payment", json={"paid": True},
            headers=auth(token),
        )
    drawn = (await client.post(url, headers=auth(token))).json()
    assigned = [p["displayName"] for p in drawn["confirmed"] if p["team"]]
    assert len(assigned) == 2
    assert all(p["paid"] for p in drawn["confirmed"] if p["team"])


async def test_a_roster_change_clears_teams_but_keeps_the_count(client: AsyncClient) -> None:
    _, game_id, token, _ = await setup(client, ["Ann", "Bob", "Cid", "Dan"])
    await client.post(f"/v1/games/{game_id}/team-balance", headers=auth(token))

    # A newcomer with no departed counterpart changes the eligible roster.
    joined = await client.post(f"/v1/games/{game_id}/participants", json={}, headers=auth(token))
    assert joined.status_code == 201, joined.text
    detail = (await client.get(f"/v1/games/{game_id}", headers=auth(token))).json()
    assert all(p["team"] is None for p in detail["confirmed"])
    assert detail["game"]["teamsDrawnAt"] is None
    assert detail["balance"]["standardCount"] == 1


async def test_an_identical_replacement_inherits_the_team_place(client: AsyncClient) -> None:
    _, game_id, token, _ = await setup(client, ["Ann", "Bob", "Cid", "Dan", "Eve"], max_players=4)
    drawn = (await client.post(f"/v1/games/{game_id}/team-balance", headers=auth(token))).json()
    ann = next(p for p in drawn["confirmed"] if p["displayName"] == "Ann")

    # Eve (same level, position, mobility and condition) is promoted in Ann's place.
    await client.delete(f"/v1/games/{game_id}/participants/{ann['id']}", headers=auth(token))
    detail = (await client.get(f"/v1/games/{game_id}", headers=auth(token))).json()
    eve = next(p for p in detail["confirmed"] if p["displayName"] == "Eve")
    assert eve["team"] == ann["team"]
    assert all(p["team"] for p in detail["confirmed"])
    assert detail["game"]["teamsDrawnAt"] is not None


async def test_a_rating_change_invalidates_the_split(client: AsyncClient) -> None:
    group_id, game_id, token, _ = await setup(client, ["Ann", "Bob", "Cid", "Dan"])
    drawn = (await client.post(f"/v1/games/{game_id}/team-balance", headers=auth(token))).json()
    ann = next(p for p in drawn["confirmed"] if p["displayName"] == "Ann")

    voted = await client.put(
        f"/v1/groups/{group_id}/players/{ann['playerId']}/votes/level", json={"value": 5},
        headers=auth(token),
    )
    assert voted.status_code == 200, voted.text
    detail = (await client.get(f"/v1/games/{game_id}", headers=auth(token))).json()
    assert all(p["team"] is None for p in detail["confirmed"])


async def test_a_reschedule_moves_the_window_and_is_recorded(client: AsyncClient) -> None:
    _, game_id, token, _ = await setup(client, ["Ann", "Bob"])
    await client.post(f"/v1/games/{game_id}/team-balance", headers=auth(token))
    moved = await client.patch(
        f"/v1/games/{game_id}", json={"startTime": "18:00:00"}, headers=auth(token)
    )
    assert moved.status_code == 200, moved.text
    detail = (await client.get(f"/v1/games/{game_id}", headers=auth(token))).json()
    change = detail["lastScheduleChange"]
    assert change["wasBroughtForward"] is True and change["changedByName"] == "Organizer"
    assert detail["balance"]["windowStartsAt"] < detail["game"]["startsAt"]
    assert detail["balance"]["standardCount"] == 1


async def test_a_finished_game_refuses_a_draw(client: AsyncClient, clean_database: str) -> None:
    _, game_id, token, _ = await setup(client, ["Ann", "Bob"])
    await sql(
        clean_database,
        "UPDATE games SET balance_window_starts_at = now() - interval '2 hours',"
        " balance_window_ends_at = now() - interval '1 minute' WHERE id = :id",
        id=game_id,
    )
    response = await client.post(f"/v1/games/{game_id}/team-balance", headers=auth(token))
    assert response.status_code == 409

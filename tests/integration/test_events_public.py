"""Public GET /events and GET /events/{id} against a real Postgres."""

from datetime import UTC, datetime, timedelta

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncEngine

from app.db.models import EventStatus, SeatingType
from app.db.session import create_session_factory
from app.services.auth import create_admin
from app.services.events import EventChanges, TierSpec, create_event, update_event

NOW = datetime.now(UTC)


@pytest.fixture
async def events(client: AsyncClient, db_engine: AsyncEngine) -> dict[str, int]:
    """Seed a mix of events and return their ids by nickname."""
    ids: dict[str, int] = {}
    async with create_session_factory(db_engine)() as session:
        admin = await create_admin(
            session, email="a@example.com", username="admin", password="a long password!"
        )

        async def add(nickname: str, name: str, city: str, days: int, status: EventStatus) -> None:
            result = await create_event(
                session,
                created_by=admin.id,
                name=name,
                description=None,
                starts_at=NOW + timedelta(days=days),
                venue="Hall",
                city=city,
                seating=SeatingType.GENERAL_ADMISSION,
                tiers=[TierSpec("Floor", 4500, 100)],
            )
            if status != EventStatus.DRAFT:
                await update_event(session, result.event.id, EventChanges(status=status))
            ids[nickname] = result.event.id

        await add("jazz", "Jazz Night", "Leeds", 3, EventStatus.PUBLISHED)
        await add("rock", "Rock 50% Off", "Leeds", 1, EventStatus.PUBLISHED)
        await add("folk", "Folk Festival", "York", 2, EventStatus.PUBLISHED)
        await add("draft", "Secret Draft", "Leeds", 4, EventStatus.DRAFT)
        await add("cancelled", "Cancelled Gig", "Leeds", 5, EventStatus.CANCELLED)
        await add("past", "Last Week's Show", "Leeds", -7, EventStatus.PUBLISHED)
    return ids


async def names(client: AsyncClient, params: dict[str, str | int] | None = None) -> list[str]:
    response = await client.get("/events", params=params)
    assert response.status_code == 200
    return [item["name"] for item in response.json()["items"]]


async def test_list_shows_only_upcoming_published_events_soonest_first(
    client: AsyncClient, events: dict[str, int]
) -> None:
    # No draft, no cancelled, no past event; ordered by start time. No login needed.
    assert await names(client) == ["Rock 50% Off", "Folk Festival", "Jazz Night"]


async def test_query_is_a_case_insensitive_name_search(
    client: AsyncClient, events: dict[str, int]
) -> None:
    assert await names(client, {"query": "JAZZ"}) == ["Jazz Night"]
    assert await names(client, {"query": "fest"}) == ["Folk Festival"]


async def test_wildcard_characters_are_searched_literally(
    client: AsyncClient, events: dict[str, int]
) -> None:
    # Unescaped, "%" would match every event and "_" any single character.
    assert await names(client, {"query": "%"}) == ["Rock 50% Off"]
    assert await names(client, {"query": "_"}) == []


async def test_city_filter_is_case_insensitive(client: AsyncClient, events: dict[str, int]) -> None:
    assert await names(client, {"city": "york"}) == ["Folk Festival"]
    assert await names(client, {"city": "LEEDS"}) == ["Rock 50% Off", "Jazz Night"]


async def test_paging_returns_a_slice_and_the_full_total(
    client: AsyncClient, events: dict[str, int]
) -> None:
    response = await client.get("/events", params={"limit": 1, "offset": 1})

    body = response.json()
    assert [item["name"] for item in body["items"]] == ["Folk Festival"]
    assert (body["total"], body["limit"], body["offset"]) == (3, 1, 1)


@pytest.mark.parametrize("params", [{"limit": 0}, {"limit": 101}, {"offset": -1}])
async def test_out_of_range_paging_is_rejected(client: AsyncClient, params: dict[str, int]) -> None:
    assert (await client.get("/events", params=params)).status_code == 422


async def test_list_items_are_summaries_without_internal_fields(
    client: AsyncClient, events: dict[str, int]
) -> None:
    item = (await client.get("/events")).json()["items"][0]

    assert set(item) == {"id", "name", "starts_at", "venue", "city", "seating"}


async def test_detail_shows_tiers_but_not_who_created_it(
    client: AsyncClient, events: dict[str, int]
) -> None:
    response = await client.get(f"/events/{events['jazz']}")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "PUBLISHED"
    assert body["tiers"] == [
        {"id": body["tiers"][0]["id"], "name": "Floor", "price_cents": 4500, "capacity": 100}
    ]
    assert "created_by" not in body


async def test_a_cancelled_event_is_still_visible_on_its_page(
    client: AsyncClient, events: dict[str, int]
) -> None:
    response = await client.get(f"/events/{events['cancelled']}")

    assert response.status_code == 200
    assert response.json()["status"] == "CANCELLED"


async def test_drafts_and_unknown_ids_are_both_404(
    client: AsyncClient, events: dict[str, int]
) -> None:
    draft = await client.get(f"/events/{events['draft']}")
    unknown = await client.get("/events/99999")

    # Identical answers, so the public can't even tell that a draft exists.
    assert draft.status_code == unknown.status_code == 404
    assert draft.json() == unknown.json()

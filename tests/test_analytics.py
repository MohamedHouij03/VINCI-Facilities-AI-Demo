from __future__ import annotations

from datetime import date

import pandas as pd
from fastapi.testclient import TestClient

from backend.services.analytics_service import detect_recurring, max_events_in_window, resolve_period


def test_max_events_in_window_uses_strict_window_length() -> None:
    dates = [date(2026, 10, 1), date(2026, 10, 15), date(2026, 10, 30), date(2026, 12, 1)]
    count, start, end = max_events_in_window(dates, 30)
    assert (count, start, end) == (3, date(2026, 10, 1), date(2026, 10, 30))
    assert max_events_in_window(dates, 29)[0] == 2  # Oct 1 -> Oct 30 spans 30 days
    assert max_events_in_window([], 30) == (0, None, None)


def test_recurring_detection_threshold_is_configurable() -> None:
    frame = pd.DataFrame(
        {
            "equipment_code": ["E1", "E1", "E1", "E2", "E2"],
            "equipment_name": ["CTA"] * 3 + ["PAC"] * 2,
            "building_code": ["BAT-A"] * 5,
            "building_name": ["A"] * 5,
            "category": ["CVC"] * 5,
            "date": pd.to_datetime(["2026-10-01", "2026-10-10", "2026-10-20", "2026-10-01", "2026-10-05"]),
        }
    )
    default = detect_recurring(frame, threshold=3, window_days=30).set_index("equipment_code")
    assert default.loc["E1", "recurring"] and not default.loc["E2", "recurring"]
    relaxed = detect_recurring(frame, threshold=2, window_days=30).set_index("equipment_code")
    assert relaxed.loc["E2", "recurring"]


def test_dashboard_kpis_are_computed_from_the_seeded_database(client: TestClient) -> None:
    data = client.get("/api/analytics/dashboard").json()
    kpis = data["kpis"]
    assert kpis["total"] == 40
    assert kpis["completed"] + kpis["pending"] == kpis["total"]
    assert kpis["buildings_monitored"] == 5
    assert kpis["recurring_equipment"] == 3  # CTA-A01, GF-A01, TD-C01 by construction of the dataset
    assert sum(item["count"] for item in data["by_month"]) == 40
    assert sum(item["count"] for item in data["by_building"]) == 40
    recurring_codes = {r["equipment_code"] for r in data["recurring"] if r["recurring"]}
    assert recurring_codes == {"CTA-A01", "GF-A01", "TD-C01"}


def test_dashboard_filters_apply_to_every_statistic(client: TestClient) -> None:
    data = client.get(
        "/api/analytics/dashboard",
        params={"building": "BAT-A", "date_from": "2026-10-01", "date_to": "2026-10-31"},
    ).json()
    assert data["kpis"]["buildings_monitored"] == 1
    assert {row["building_code"] for row in data["by_building"]} == {"BAT-A"}
    assert all(row["date"] >= "2026-10-01" for row in data["recent"])
    assert data["kpis"]["recurring_equipment"] == 1  # CTA-A01 only


def test_recurrence_rule_comes_from_configuration(configure) -> None:
    from backend.main import create_app

    configure(recurrence_threshold=2)
    with TestClient(create_app()) as client:
        client.headers.update({"X-API-Key": "test-api-key"})
        data = client.get("/api/analytics/dashboard").json()
    assert data["recurrence_rule"]["threshold"] == 2
    assert data["kpis"]["recurring_equipment"] > 3


def test_period_resolution() -> None:
    today = date(2026, 10, 29)
    assert resolve_period("this_month", today)[:2] == (date(2026, 10, 1), today)
    assert resolve_period("last_month", today)[:2] == (date(2026, 9, 1), date(2026, 9, 30))
    assert resolve_period("all", today)[:2] == (None, None)

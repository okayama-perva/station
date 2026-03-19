from __future__ import annotations

import sys

import app


LOCAL_ALLOWED = set(app.LOCAL_SERVICES)
RAPID_ALLOWED = set(app.RAPID_SERVICES)
EXPRESS_ONLY_ALLOWED = set(app.EXPRESS_ONLY_SERVICES)
LIMITED_ALLOWED = set(app.LIMITED_SERVICES)

EXPECTED_COORDS = {
    "高田": (35.54955, 139.62059),
    "大山": (35.74841, 139.7026233),
    "日吉": (35.55399, 139.64703),
    "青海": (35.6248, 139.781315),
}


def assert_close(actual: float, expected: float, label: str) -> None:
    if abs(actual - expected) > 1e-6:
        raise AssertionError(f"{label}: expected {expected}, got {actual}")


def check_coordinates() -> None:
    for station, (lat, lng) in EXPECTED_COORDS.items():
        coord = app.station_coord(station)
        if not coord:
            raise AssertionError(f"{station}: missing coordinates")
        assert_close(coord["lat"], lat, f"{station} lat")
        assert_close(coord["lng"], lng, f"{station} lng")


def fetch(client, query: str) -> dict:
    response = client.get(query)
    if response.status_code != 200:
        raise AssertionError(f"{query}: status {response.status_code}")
    payload = response.get_json()
    if not isinstance(payload, dict):
        raise AssertionError(f"{query}: invalid json payload")
    if payload.get("error"):
        raise AssertionError(f"{query}: {payload['error']}")
    return payload


def assert_services(payload: dict, allowed: set[str], label: str) -> None:
    results = payload.get("results", [])
    bad = [item for item in results if item.get("service") not in allowed]
    if bad:
        preview = ", ".join(
            f"{item.get('station')}:{item.get('service')}" for item in bad[:10]
        )
        raise AssertionError(f"{label}: unexpected services -> {preview}")


def check_service_filters() -> None:
    client = app.app.test_client()

    local_payload = fetch(client, "/search?target=渋谷&time=30&service=local")
    assert_services(local_payload, LOCAL_ALLOWED, "local")

    rapid_payload = fetch(client, "/search?target=東京&time=40&service=rapid")
    assert_services(rapid_payload, RAPID_ALLOWED, "rapid")

    express_only_payload = fetch(client, "/search?target=渋谷&time=40&service=express_only")
    assert_services(express_only_payload, EXPRESS_ONLY_ALLOWED, "express_only")

    limited_payload = fetch(client, "/search?target=新宿&time=80&service=limited")
    assert_services(limited_payload, LIMITED_ALLOWED, "limited")


def check_representative_routes() -> None:
    client = app.app.test_client()

    rapid_payload = fetch(client, "/search?target=東京&time=40&service=rapid")
    if not any(item.get("base_line") == "JR中央線" and item.get("service") == "快速" for item in rapid_payload["results"]):
        raise AssertionError("rapid: expected JR中央線 快速 result around 東京")

    express_payload = fetch(client, "/search?target=渋谷&time=25&service=express_only")
    if not any(item.get("base_line") == "東急東横線" and item.get("service") == "急行" for item in express_payload["results"]):
        raise AssertionError("express_only: expected 東急東横線 急行 result around 渋谷")

    limited_payload = fetch(client, "/search?target=池袋&time=60&service=limited")
    if not any(item.get("service") in LIMITED_ALLOWED for item in limited_payload["results"]):
        raise AssertionError("limited: expected limited express style result around 池袋")


def main() -> int:
    try:
        check_coordinates()
        check_service_filters()
        check_representative_routes()
    except AssertionError as exc:
        print(f"NG: {exc}")
        return 1

    print("OK: coordinate overrides and service filters look consistent")
    return 0


if __name__ == "__main__":
    sys.exit(main())

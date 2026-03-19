from __future__ import annotations

import sys

import app
import station_search


LOCAL_ALLOWED = set(app.LOCAL_SERVICES)
RAPID_ALLOWED = set(app.RAPID_SERVICES)
EXPRESS_ONLY_ALLOWED = set(app.EXPRESS_ONLY_SERVICES)
LIMITED_ALLOWED = set(app.LIMITED_SERVICES)

SHIBUYA = "\u6e0b\u8c37"
TOKYO = "\u6771\u4eac"
SHINJUKU = "\u65b0\u5bbf"
IKEBUKURO = "\u6c60\u888b"
CHUORINKAN = "\u4e2d\u592e\u6797\u9593"
TSUKIMINO = "\u3064\u304d\u307f\u91ce"
TAKADA = "\u9ad8\u7530"
OYAMA = "\u5927\u5c71"
HIYOSHI = "\u65e5\u5409"
AOMI = "\u9752\u6d77"
JR_CHUO = "JR\u4e2d\u592e\u7dda"
TOKYU_TOYOKO = "\u6771\u6025\u6771\u6a2a\u7dda"
TOKYU_DENENTOSHI = "\u6771\u6025\u7530\u5712\u90fd\u5e02\u7dda"

EXPECTED_COORDS = {
    TAKADA: (35.54955, 139.62059),
    OYAMA: (35.74841, 139.7026233),
    HIYOSHI: (35.55399, 139.64703),
    AOMI: (35.6248, 139.781315),
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

    local_payload = fetch(client, f"/search?target={SHIBUYA}&time=30&service=local")
    assert_services(local_payload, LOCAL_ALLOWED, "local")

    rapid_payload = fetch(client, f"/search?target={TOKYO}&time=40&service=rapid")
    assert_services(rapid_payload, RAPID_ALLOWED, "rapid")

    express_only_payload = fetch(client, f"/search?target={SHIBUYA}&time=40&service=express_only")
    assert_services(express_only_payload, EXPRESS_ONLY_ALLOWED, "express_only")

    limited_payload = fetch(client, f"/search?target={SHINJUKU}&time=80&service=limited")
    assert_services(limited_payload, LIMITED_ALLOWED, "limited")

    express_payload = fetch(client, f"/search?target={SHIBUYA}&time=40&service=express")
    assert_services(
        express_payload,
        RAPID_ALLOWED | EXPRESS_ONLY_ALLOWED | LIMITED_ALLOWED,
        "express",
    )


def check_representative_routes() -> None:
    client = app.app.test_client()

    rapid_payload = fetch(client, f"/search?target={TOKYO}&time=40&service=rapid")
    if not any(item.get("base_line") == JR_CHUO and item.get("service") == "\u5feb\u901f" for item in rapid_payload["results"]):
        raise AssertionError("rapid: expected JR中央線 / 快速 around 東京")

    express_payload = fetch(client, f"/search?target={SHIBUYA}&time=25&service=express_only")
    if not any(item.get("base_line") == TOKYU_TOYOKO and item.get("service") == "\u6025\u884c" for item in express_payload["results"]):
        raise AssertionError("express_only: expected 東急東横線 / 急行 around 渋谷")

    denentoshi_payload = fetch(client, f"/search?target={CHUORINKAN}&time=45&service=express_only")
    if not any(item.get("base_line") == TOKYU_DENENTOSHI and item.get("service") == "\u6025\u884c" for item in denentoshi_payload["results"]):
        raise AssertionError("express_only: expected 東急田園都市線 / 急行 around 中央林間")

    denentoshi_semi_payload = fetch(client, f"/search?target={SHIBUYA}&time=50&service=express_only")
    if not any(item.get("station") == TSUKIMINO and item.get("base_line") == TOKYU_DENENTOSHI and item.get("service") == "\u6025\u884c" for item in denentoshi_semi_payload["results"]):
        raise AssertionError("express_only: expected つきみ野 to appear via 東急田園都市線 / 急行 category around 渋谷")

    limited_payload = fetch(client, f"/search?target={SHIBUYA}&time=40&service=limited")
    if not any(item.get("base_line") == TOKYU_TOYOKO and item.get("service") == "\u7279\u6025" for item in limited_payload["results"]):
        raise AssertionError("limited: expected 東急東横線 / 特急 around 渋谷")


def check_service_normalization() -> None:
    examples = {
        "\u5404\u505c": "\u666e\u901a",
        "\u7a7a\u6e2f\u5feb\u901f": "\u5feb\u901f",
        "\u6e96\u6025": "\u6025\u884c",
        "\u5feb\u901f\u6025\u884c": "\u6025\u884c",
        "\u5feb\u7279": "\u7279\u6025",
        "\u5ddd\u8d8a\u7279\u6025": "\u7279\u6025",
        "\u901a\u52e4\u7279\u6025": "\u7279\u6025",
    }
    for raw, expected in examples.items():
        actual = station_search.normalize_service_name(raw)
        if actual != expected:
            raise AssertionError(f"normalize_service_name({raw}) -> {actual}, expected {expected}")


def main() -> int:
    try:
        check_coordinates()
        check_service_filters()
        check_representative_routes()
        check_service_normalization()
    except AssertionError as exc:
        print(f"NG: {exc}")
        return 1

    print("OK: coordinate overrides and service filters look consistent")
    return 0


if __name__ == "__main__":
    sys.exit(main())

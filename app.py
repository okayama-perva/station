"""駅到達圏検索の Flask アプリ。"""

from pathlib import Path

from flask import Flask, jsonify, render_template, request

from station_search import (
    EXPRESS_SERVICES,
    LOCAL_SERVICES,
    build_graph,
    canonicalize_station_name,
    load_network,
    search_reachable,
)

app = Flask(__name__)

NETWORK_PATH = Path(__file__).parent / "data" / "network.json"
network_mtime = None
MANUAL_COORD_OVERRIDES = {
    "高田": {"lat": 35.54955, "lng": 139.62059},
    "大山": {"lat": 35.74841, "lng": 139.7026233},
    "北山田": {"lat": 35.56109, "lng": 139.5927467},
    "牛田": {"lat": 35.744545, "lng": 139.81177},
    "ときわ台": {"lat": 35.758905, "lng": 139.68876},
    "東雲": {"lat": 35.64082, "lng": 139.80416},
    "中田": {"lat": 35.411155, "lng": 139.51122},
    "中山": {"lat": 35.51437, "lng": 139.53998},
    "高津": {"lat": 35.60346, "lng": 139.617665},
    "日吉": {"lat": 35.55399, "lng": 139.64703},
    "高松": {"lat": 35.710045, "lng": 139.413275},
    "有明": {"lat": 35.63455, "lng": 139.79334},
    "青海": {"lat": 35.6248, "lng": 139.781315},
    "新田": {"lat": 35.85411, "lng": 139.795425},
    "中川": {"lat": 35.563085, "lng": 139.56968},
    "大久保": {"lat": 35.700635, "lng": 139.697445},
}
RAPID_SERVICES = {"快速"}
EXPRESS_ONLY_SERVICES = {"急行"}
LIMITED_SERVICES = {"特急", "快特", "通勤急行"}
network = load_network()
station_aliases = network.get("station_aliases", {})
station_coordinates = network.get("station_coordinates", {})
graph, station_lines, transfer_context, line_catalog = build_graph(network)
all_stations = sorted(set(station_lines.keys()) | set(station_aliases.keys()))


def reverse_route(route: str) -> str:
    parts = [part for part in route.split(" -> ") if part]
    parts.reverse()
    return " -> ".join(parts)


def parse_service_filter(value: str | None):
    if not value or value == "all":
        return {"exclude_shinkansen": True}
    if value == "all_shinkansen":
        return None
    if value == "local":
        return {"mode": "only", "services": LOCAL_SERVICES, "exclude_shinkansen": True}
    if value == "rapid":
        return {"mode": "contains", "services": RAPID_SERVICES, "exclude_shinkansen": True}
    if value == "express_only":
        return {"mode": "contains", "services": EXPRESS_ONLY_SERVICES, "exclude_shinkansen": True}
    if value == "limited":
        return {"mode": "contains", "services": LIMITED_SERVICES, "exclude_shinkansen": True}
    if value == "express":
        return {"mode": "contains", "services": EXPRESS_SERVICES, "exclude_shinkansen": True}
    return None


def refresh_runtime_data():
    global network_mtime, network, station_aliases, station_coordinates
    global graph, station_lines, transfer_context, line_catalog, all_stations

    try:
        current_mtime = NETWORK_PATH.stat().st_mtime
    except FileNotFoundError:
        return

    if network_mtime == current_mtime:
        return

    network = load_network()
    network_mtime = current_mtime
    station_aliases = network.get("station_aliases", {})
    station_coordinates = network.get("station_coordinates", {})
    graph, station_lines, transfer_context, line_catalog = build_graph(network)
    all_stations = sorted(set(station_lines.keys()) | set(station_aliases.keys()))


def station_coord(station: str):
    return MANUAL_COORD_OVERRIDES.get(station) or station_coordinates.get(station)


@app.route("/")
def index():
    refresh_runtime_data()
    return render_template("index.html", stations=all_stations)


@app.route("/search")
def search():
    refresh_runtime_data()
    raw_target = request.args.get("target", "").strip()
    target = canonicalize_station_name(raw_target, station_aliases)
    max_time = request.args.get("time", 30, type=int)
    max_transfers = request.args.get("transfers", type=int)
    service_filter = request.args.get("service", "all")

    if target not in station_lines:
        return jsonify({"error": f"「{raw_target}」はデータに存在しません。"})

    results = search_reachable(
        graph,
        station_lines,
        line_catalog,
        target,
        max_time,
        max_transfers,
        transfer_context,
        parse_service_filter(service_filter),
    )
    results.pop(target, None)

    items = [
        {
            "station": station,
            "time": time,
            "transfers": transfers,
            "route": reverse_route(route),
            "line": line_name,
            "base_line": base_name,
            "service": service,
            "group_key": f"{base_name} [{service}]",
            "lat": (station_coord(station) or {}).get("lat"),
            "lng": (station_coord(station) or {}).get("lng"),
        }
        for station, (time, transfers, route, line_name, base_name, service) in results.items()
    ]
    if service_filter == "express":
        items = [item for item in items if item["service"] in EXPRESS_SERVICES]
    elif service_filter == "rapid":
        items = [item for item in items if item["service"] in RAPID_SERVICES]
    elif service_filter == "express_only":
        items = [item for item in items if item["service"] in EXPRESS_ONLY_SERVICES]
    elif service_filter == "limited":
        items = [item for item in items if item["service"] in LIMITED_SERVICES]
    items.sort(key=lambda x: (x["time"], x["transfers"], x["station"]))

    groups = []
    grouped = {}
    for item in items:
        key = item["group_key"]
        if key not in grouped:
            grouped[key] = {
                "line": item["base_line"],
                "service": item["service"],
                "count": 0,
                "results": [],
            }
            groups.append(grouped[key])
        grouped[key]["results"].append(item)
        grouped[key]["count"] += 1

    groups.sort(key=lambda g: (g["line"], g["service"]))

    return jsonify(
        {
            "target": target,
            "input_target": raw_target,
            "count": len(items),
            "target_coords": station_coord(target),
            "results": items,
            "groups": groups,
        }
    )


if __name__ == "__main__":
    app.run(debug=True, port=5000)

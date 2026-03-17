"""駅到達圏検索の Flask アプリ。"""

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

network = load_network()
station_aliases = network.get("station_aliases", {})
graph, station_lines, transfer_context, line_catalog = build_graph(network)
all_stations = sorted(set(station_lines.keys()) | set(station_aliases.keys()))


def reverse_route(route: str) -> str:
    parts = [part for part in route.split(" -> ") if part]
    parts.reverse()
    return " -> ".join(parts)


def parse_service_filter(value: str | None):
    if not value or value == "all":
        return None
    if value == "local":
        return {"mode": "only", "services": LOCAL_SERVICES}
    if value == "express":
        return {"mode": "contains", "services": EXPRESS_SERVICES}
    return None


@app.route("/")
def index():
    return render_template("index.html", stations=all_stations)


@app.route("/search")
def search():
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
        }
        for station, (time, transfers, route, line_name, base_name, service) in results.items()
    ]
    if service_filter == "express":
        items = [item for item in items if item["service"] in EXPRESS_SERVICES]
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
            "results": items,
            "groups": groups,
        }
    )


if __name__ == "__main__":
    app.run(debug=True, port=5000)

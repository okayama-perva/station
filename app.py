"""駅到達圏検索 - Webアプリ"""
from flask import Flask, render_template, request, jsonify
import json
from pathlib import Path
from station_search import load_network, build_graph, search_reachable

app = Flask(__name__)

network = load_network()
graph, station_lines, transfer_time = build_graph(network)
all_stations = sorted(station_lines.keys())


@app.route("/")
def index():
    return render_template("index.html", stations=all_stations)


@app.route("/search")
def search():
    target = request.args.get("target", "").strip()
    max_time = request.args.get("time", 30, type=int)
    max_transfers = request.args.get("transfers", type=int)  # None if not provided

    if target not in station_lines:
        return jsonify({"error": f"「{target}」はデータに存在しません。"})

    results = search_reachable(graph, station_lines, target, max_time,
                               max_transfers, transfer_time)
    results.pop(target, None)

    items = [{"station": st, "time": t, "transfers": tr, "route": route}
             for st, (t, tr, route) in results.items()]
    items.sort(key=lambda x: (x["time"], x["transfers"], x["station"]))

    return jsonify({"count": len(items), "results": items})


if __name__ == "__main__":
    app.run(debug=True, port=5000)

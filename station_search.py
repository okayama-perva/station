"""駅到達圏検索 - 指定時間以内で到達可能な駅を探索する。"""

import argparse
import heapq
import json
from pathlib import Path


def load_network(data_path: str | None = None) -> dict:
    if data_path is None:
        data_path = Path(__file__).parent / "data" / "network.json"
    with open(data_path, encoding="utf-8") as f:
        return json.load(f)


def canonicalize_station_name(name: str, aliases: dict[str, str] | None = None) -> str:
    if not aliases:
        return name
    return aliases.get(name, name)


def build_graph(network: dict) -> tuple[dict, dict, int, dict]:
    """ネットワークデータからグラフを構築する。

    Returns:
        graph: {station: [(neighbor, time_min, line_name), ...]}
        station_lines: {station: set(line_names)}
        transfer_time: 乗換時間
        line_catalog: {line_name: {base_name, service, operator}}
    """
    graph: dict[str, list] = {}
    station_lines: dict[str, set] = {}
    line_catalog: dict[str, dict] = {}
    transfer_time = network.get("transfer_time", 5)
    station_aliases = network.get("station_aliases", {})

    for line in network["lines"]:
        line_name = line["name"]
        line_catalog[line_name] = {
            "base_name": line.get("base_name", line_name),
            "service": line.get("service", "各駅停車"),
            "operator": line.get("operator"),
        }
        stations = line["stations"]  # [(name, time_to_next), ...]

        for i, entry in enumerate(stations):
            st_name = canonicalize_station_name(entry[0], station_aliases)
            graph.setdefault(st_name, [])
            station_lines.setdefault(st_name, set()).add(line_name)

            if i < len(stations) - 1:
                next_name = canonicalize_station_name(stations[i + 1][0], station_aliases)
                travel = entry[1]
                graph.setdefault(next_name, [])
                graph[st_name].append((next_name, travel, line_name))
                graph[next_name].append((st_name, travel, line_name))

        if line.get("loop", False) and len(stations) > 2:
            first = canonicalize_station_name(stations[0][0], station_aliases)
            last = canonicalize_station_name(stations[-1][0], station_aliases)
            travel = stations[-1][1]
            graph[last].append((first, travel, line_name))
            graph[first].append((last, travel, line_name))

    return graph, station_lines, transfer_time, line_catalog


def search_reachable(
    graph,
    station_lines,
    line_catalog,
    target: str,
    max_time: int,
    max_transfers: int | None = None,
    transfer_time: int = 5,
    allowed_services: set[str] | None = None,
):
    """指定時間以内で到達可能な全駅を探索する。"""
    pq = []
    best = {}

    for line in station_lines.get(target, set()):
        service = line_catalog.get(line, {}).get("service", "各駅停車")
        if allowed_services and service not in allowed_services:
            continue
        heapq.heappush(pq, (0, 0, target, line, [f"{target}({line})"]))

    results = {}

    while pq:
        time, transfers, station, cur_line, path = heapq.heappop(pq)

        if time > max_time:
            continue
        if max_transfers is not None and transfers > max_transfers:
            continue

        state_key = (station, cur_line)
        if state_key in best:
            best_time, best_transfers = best[state_key]
            if time > best_time or (time == best_time and transfers >= best_transfers):
                continue
        best[state_key] = (time, transfers)

        if station not in results or (time, transfers) < (results[station][0], results[station][1]):
            meta = line_catalog.get(cur_line, {})
            results[station] = (
                time,
                transfers,
                " -> ".join(reversed(path)),
                cur_line,
                meta.get("base_name", cur_line),
                meta.get("service", "各駅停車"),
            )

        for neighbor, travel, line_name in graph.get(station, []):
            service = line_catalog.get(line_name, {}).get("service", "各駅停車")
            if allowed_services and service not in allowed_services:
                continue

            new_time = time + travel
            if new_time > max_time:
                continue

            if line_name == cur_line:
                new_transfers = transfers
                new_path = path + [neighbor]
            else:
                new_transfers = transfers + 1
                new_time += transfer_time
                if new_time > max_time:
                    continue
                if max_transfers is not None and new_transfers > max_transfers:
                    continue
                new_path = path + [f"乗換@{station}", f"{neighbor}({line_name})"]

            next_state = (neighbor, line_name)
            if next_state in best:
                best_time, best_transfers = best[next_state]
                if new_time > best_time or (new_time == best_time and new_transfers >= best_transfers):
                    continue

            heapq.heappush(pq, (new_time, new_transfers, neighbor, line_name, new_path))

    return results


def main():
    parser = argparse.ArgumentParser(description="駅到達圏検索")
    parser.add_argument("target", help="出発駅名")
    parser.add_argument("time", type=int, help="最大所要時間（分）")
    parser.add_argument(
        "-t",
        "--transfers",
        type=int,
        default=None,
        help="最大乗換回数。未指定なら制限なし",
    )
    parser.add_argument("-d", "--data", default=None, help="ネットワークデータJSONパス")
    parser.add_argument(
        "--sort",
        choices=["time", "name", "transfers"],
        default="time",
        help="ソート順",
    )
    args = parser.parse_args()

    network = load_network(args.data)
    station_aliases = network.get("station_aliases", {})
    graph, station_lines, default_transfer, line_catalog = build_graph(network)
    transfer_time = default_transfer
    target = canonicalize_station_name(args.target, station_aliases)

    if target not in station_lines:
        print(f"エラー: 「{args.target}」はデータに存在しません。")
        candidates = [s for s in station_lines if args.target in s]
        if candidates:
            print("候補:")
            for candidate in candidates[:10]:
                print(f"  {candidate}")
        return

    results = search_reachable(
        graph,
        station_lines,
        line_catalog,
        target,
        args.time,
        args.transfers,
        transfer_time,
    )
    results.pop(target, None)

    if not results:
        print(f"{target}まで{args.time}分以内に到達できる駅はありません。")
        return

    items = [
        (station, time, transfers, route, base_name, service)
        for station, (time, transfers, route, _line_name, base_name, service) in results.items()
    ]
    if args.sort == "time":
        items.sort(key=lambda x: (x[1], x[2], x[0]))
    elif args.sort == "transfers":
        items.sort(key=lambda x: (x[2], x[1], x[0]))
    else:
        items.sort(key=lambda x: x[0])

    transfers_label = (
        f"乗換{args.transfers}回以下" if args.transfers is not None else "乗換制限なし"
    )
    print(f"\n{'=' * 60}")
    print(f" {target} まで {args.time}分以内 ({transfers_label})")
    print(f" 該当駅数: {len(items)}駅")
    print(f"{'=' * 60}")
    print(f" {'駅名':<10} {'時間':>5} {'乗換':>4}  経路")
    print(f"{'-' * 60}")
    for station, time, transfers, route, base_name, service in items:
        print(f" {station:<10} {time:>3}分  {transfers:>2}回  [{base_name}/{service}] {route}")
    print(f"{'=' * 60}")


if __name__ == "__main__":
    main()

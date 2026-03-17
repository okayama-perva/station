"""駅到達圏検索の探索ロジック。"""

from __future__ import annotations

import argparse
import heapq
import json
from pathlib import Path
from typing import Any


LOCAL_SERVICES = {"各駅停車", "各停", "普通"}
EXPRESS_SERVICES = {"急行", "特急", "快速", "快特", "通勤急行"}
SHINKANSEN_KEYWORD = "新幹線"


def load_network(data_path: str | None = None) -> dict:
    if data_path is None:
        data_path = Path(__file__).parent / "data" / "network.json"
    with open(data_path, encoding="utf-8") as f:
        return json.load(f)


def canonicalize_station_name(name: str, aliases: dict[str, str] | None = None) -> str:
    if not aliases:
        return name
    return aliases.get(name, name)


def normalize_segment_time(value: Any) -> int:
    if isinstance(value, dict):
        if "weekday_offpeak" in value:
            return int(value["weekday_offpeak"])
        return int(next(iter(value.values())))
    return int(value)


def pair_key(a: str, b: str) -> str:
    return " | ".join(sorted((a, b)))


def resolve_transfer_time(
    transfer_context: dict[str, Any],
    station: str,
    from_line: str,
    to_line: str,
) -> int:
    default_time = int(transfer_context.get("default", 5))
    station_overrides = transfer_context.get("overrides", {}).get(station)
    if station_overrides is None:
        return default_time
    if isinstance(station_overrides, int):
        return station_overrides

    pairs = station_overrides.get("pairs", {})
    key = pair_key(from_line, to_line)
    if key in pairs:
        return int(pairs[key])
    return int(station_overrides.get("default", default_time))


def is_shinkansen_line(meta: dict[str, Any] | None) -> bool:
    if not meta:
        return False
    base_name = str(meta.get("base_name", ""))
    line_name = str(meta.get("name", ""))
    return SHINKANSEN_KEYWORD in base_name or SHINKANSEN_KEYWORD in line_name


def build_graph(network: dict) -> tuple[dict, dict, dict, dict]:
    graph: dict[str, list] = {}
    station_lines: dict[str, set[str]] = {}
    line_catalog: dict[str, dict[str, Any]] = {}

    station_aliases = network.get("station_aliases", {})
    transfer_context = {
        "default": network.get("transfer_time", 5),
        "overrides": network.get("transfer_overrides", {}),
    }

    for line in network["lines"]:
        line_name = line["name"]
        line_catalog[line_name] = {
            "name": line_name,
            "base_name": line.get("base_name", line_name),
            "service": line.get("service", "各駅停車"),
            "operator": line.get("operator"),
        }
        stations = line["stations"]

        for i, entry in enumerate(stations):
            station_name = canonicalize_station_name(entry[0], station_aliases)
            graph.setdefault(station_name, [])
            station_lines.setdefault(station_name, set()).add(line_name)

            if i < len(stations) - 1:
                next_name = canonicalize_station_name(stations[i + 1][0], station_aliases)
                graph.setdefault(next_name, [])
                segment_time = normalize_segment_time(entry[1])
                graph[station_name].append((next_name, segment_time, line_name))
                graph[next_name].append((station_name, segment_time, line_name))

        if line.get("loop", False) and len(stations) > 2:
            first = canonicalize_station_name(stations[0][0], station_aliases)
            last = canonicalize_station_name(stations[-1][0], station_aliases)
            segment_time = normalize_segment_time(stations[-1][1])
            graph[last].append((first, segment_time, line_name))
            graph[first].append((last, segment_time, line_name))

    return graph, station_lines, transfer_context, line_catalog


def search_reachable(
    graph: dict,
    station_lines: dict[str, set[str]],
    line_catalog: dict[str, dict[str, Any]],
    target: str,
    max_time: int,
    max_transfers: int | None = None,
    transfer_context: dict[str, Any] | None = None,
    service_filter: dict[str, Any] | None = None,
):
    transfer_context = transfer_context or {"default": 5, "overrides": {}}
    filter_mode = (service_filter or {}).get("mode")
    filter_services = set((service_filter or {}).get("services", set()))
    exclude_shinkansen = bool((service_filter or {}).get("exclude_shinkansen"))

    pq: list[tuple[int, int, str, str, bool, list[str]]] = []
    best: dict[tuple[str, str, bool], tuple[int, int]] = {}

    for line in station_lines.get(target, set()):
        meta = line_catalog.get(line, {})
        if exclude_shinkansen and is_shinkansen_line(meta):
            continue
        service = meta.get("service", "各駅停車")
        if filter_mode == "only" and service not in filter_services:
            continue
        used_match = service in filter_services if filter_mode == "contains" else True
        heapq.heappush(pq, (0, 0, target, line, used_match, [f"{target}({line})"]))

    results = {}

    while pq:
        time, transfers, station, current_line, used_match, path = heapq.heappop(pq)

        if time > max_time:
            continue
        if max_transfers is not None and transfers > max_transfers:
            continue

        state_key = (station, current_line, used_match)
        if state_key in best:
            best_time, best_transfers = best[state_key]
            if time > best_time or (time == best_time and transfers >= best_transfers):
                continue
        best[state_key] = (time, transfers)

        if (filter_mode != "contains" or used_match) and (
            station not in results or (time, transfers) < (results[station][0], results[station][1])
        ):
            meta = line_catalog.get(current_line, {})
            results[station] = (
                time,
                transfers,
                " -> ".join(path),
                current_line,
                meta.get("base_name", current_line),
                meta.get("service", "各駅停車"),
            )

        for neighbor, segment_time, line_name in graph.get(station, []):
            meta = line_catalog.get(line_name, {})
            if exclude_shinkansen and is_shinkansen_line(meta):
                continue
            service = meta.get("service", "各駅停車")
            if filter_mode == "only" and service not in filter_services:
                continue
            next_used_match = used_match or (service in filter_services if filter_mode == "contains" else False)

            new_time = time + int(segment_time)
            if new_time > max_time:
                continue

            if line_name == current_line:
                new_transfers = transfers
                new_path = path + [neighbor]
            else:
                new_transfers = transfers + 1
                new_time += resolve_transfer_time(transfer_context, station, current_line, line_name)
                if new_time > max_time:
                    continue
                if max_transfers is not None and new_transfers > max_transfers:
                    continue
                new_path = path + [f"乗換@{station}", f"{neighbor}({line_name})"]

            next_state = (neighbor, line_name, next_used_match)
            if next_state in best:
                best_time, best_transfers = best[next_state]
                if new_time > best_time or (new_time == best_time and new_transfers >= best_transfers):
                    continue

            heapq.heappush(pq, (new_time, new_transfers, neighbor, line_name, next_used_match, new_path))

    return results


def main():
    parser = argparse.ArgumentParser(description="駅到達圏検索")
    parser.add_argument("target", help="終着駅")
    parser.add_argument("time", type=int, help="最大所要時間（分）")
    parser.add_argument("-t", "--transfers", type=int, default=None, help="最大乗換回数")
    parser.add_argument("-d", "--data", default=None, help="ネットワークデータ JSON パス")
    parser.add_argument("--sort", choices=["time", "name", "transfers"], default="time", help="ソート順")
    args = parser.parse_args()

    network = load_network(args.data)
    station_aliases = network.get("station_aliases", {})
    graph, station_lines, transfer_context, line_catalog = build_graph(network)
    target = canonicalize_station_name(args.target, station_aliases)

    if target not in station_lines:
        print(f"エラー: 「{args.target}」はデータに存在しません。")
        candidates = [station for station in station_lines if args.target in station]
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
        transfer_context,
        None,
    )
    results.pop(target, None)

    if not results:
        print(f"{target} へ {args.time} 分以内に到達できる駅はありません。")
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

    transfer_label = f"乗換{args.transfers}回まで" if args.transfers is not None else "乗換制限なし"
    print(f"\n{'=' * 60}")
    print(f" {target} へ {args.time}分以内 ({transfer_label})")
    print(f" 到達駅数: {len(items)}駅")
    print(f"{'=' * 60}")
    print(f" {'駅名':<10} {'時間':>5} {'乗換':>4}  経路")
    print(f"{'-' * 60}")
    for station, time, transfers, route, base_name, service in items:
        print(f" {station:<10} {time:>3}分 {transfers:>3}回 [{base_name}/{service}] {route}")
    print(f"{'=' * 60}")


if __name__ == "__main__":
    main()

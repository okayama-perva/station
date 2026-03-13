"""駅到達圏検索 - 指定駅に到達可能な駅を時間・乗り換え回数で検索"""

import json
import heapq
from pathlib import Path


def load_network(data_path: str = None) -> dict:
    if data_path is None:
        data_path = Path(__file__).parent / "data" / "network.json"
    with open(data_path, encoding="utf-8") as f:
        return json.load(f)


def build_graph(network: dict) -> tuple[dict, dict]:
    """路線データからグラフを構築。
    Returns:
        graph: {station: [(neighbor, time_min, line_name), ...]}
        station_lines: {station: set(line_names)}
    """
    graph: dict[str, list] = {}
    station_lines: dict[str, set] = {}
    transfer_time = network.get("transfer_time", 5)

    for line in network["lines"]:
        line_name = line["name"]
        stations = line["stations"]  # [(name, time_to_next), ...]

        for i, entry in enumerate(stations):
            st_name = entry[0]
            graph.setdefault(st_name, [])
            station_lines.setdefault(st_name, set()).add(line_name)

            if i < len(stations) - 1:
                next_name = stations[i + 1][0]
                travel = entry[1]  # この駅から次の駅への所要時間
                graph.setdefault(next_name, [])
                graph[st_name].append((next_name, travel, line_name))
                graph[next_name].append((st_name, travel, line_name))

        # ループ路線（山手線等）
        if line.get("loop", False) and len(stations) > 2:
            first = stations[0][0]
            last = stations[-1][0]
            travel = stations[-1][1]
            graph[last].append((first, travel, line_name))
            graph[first].append((last, travel, line_name))

    return graph, station_lines, transfer_time


def search_reachable(graph, station_lines, target: str, max_time: int,
                     max_transfers: int = None, transfer_time: int = 5):
    """目的駅に到達可能な全駅を探索（逆方向Dijkstra）。

    Returns: [(station, time, transfers, route_summary), ...]
    """
    # state: (累計時間, 乗り換え回数, 現在駅, 現在路線, 経路)
    # 目的駅から逆探索
    INF = float("inf")
    # (time, transfers, station, current_line, path)
    pq = []
    # best[station] = (best_time, best_transfers)
    best = {}

    # 目的駅を全路線から開始
    for line in station_lines.get(target, set()):
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
            bt, btr = best[state_key]
            if time > bt or (time == bt and transfers >= btr):
                continue
        best[state_key] = (time, transfers)

        # この駅の結果を記録（最短時間・最小乗り換え優先）
        if station not in results or (time, transfers) < (results[station][0], results[station][1]):
            results[station] = (time, transfers, " → ".join(reversed(path)))

        for neighbor, travel, line_name in graph.get(station, []):
            new_time = time + travel
            if new_time > max_time:
                continue

            if line_name == cur_line:
                new_transfers = transfers
                new_path = path + [f"{neighbor}"]
            else:
                new_transfers = transfers + 1
                new_time += transfer_time
                if new_time > max_time:
                    continue
                if max_transfers is not None and new_transfers > max_transfers:
                    continue
                new_path = path + [f"乗換@{station}", f"{neighbor}({line_name})"]

            ns_key = (neighbor, line_name)
            if ns_key in best:
                bt, btr = best[ns_key]
                if new_time > bt or (new_time == bt and new_transfers >= btr):
                    continue

            heapq.heappush(pq, (new_time, new_transfers, neighbor, line_name, new_path))

    return results


def main():
    import argparse
    parser = argparse.ArgumentParser(description="駅到達圏検索")
    parser.add_argument("target", help="目的駅名（例: 渋谷）")
    parser.add_argument("time", type=int, help="最大所要時間（分）")
    parser.add_argument("-t", "--transfers", type=int, default=None,
                        help="最大乗り換え回数（省略時: 制限なし）")
    parser.add_argument("-d", "--data", default=None, help="ネットワークデータJSONパス")
    parser.add_argument("--sort", choices=["time", "name", "transfers"], default="time",
                        help="ソート順（デフォルト: time）")
    args = parser.parse_args()

    network = load_network(args.data)
    graph, station_lines, default_transfer = build_graph(network)
    transfer_time = default_transfer

    if args.target not in station_lines:
        print(f"エラー: 「{args.target}」はデータに存在しません。")
        # 部分一致候補を表示
        candidates = [s for s in station_lines if args.target in s]
        if candidates:
            print("候補:")
            for c in candidates[:10]:
                print(f"  {c}")
        return

    results = search_reachable(graph, station_lines, args.target, args.time,
                               args.transfers, transfer_time)

    # 目的駅自身を除外
    results.pop(args.target, None)

    if not results:
        print(f"{args.target}まで{args.time}分以内に到達できる駅はありません。")
        return

    items = [(st, t, tr, route) for st, (t, tr, route) in results.items()]
    if args.sort == "time":
        items.sort(key=lambda x: (x[1], x[2], x[0]))
    elif args.sort == "transfers":
        items.sort(key=lambda x: (x[2], x[1], x[0]))
    else:
        items.sort(key=lambda x: x[0])

    transfers_label = f"乗り換え{args.transfers}回以内" if args.transfers is not None else "乗り換え制限なし"
    print(f"\n{'='*60}")
    print(f" {args.target} まで {args.time}分以内 ({transfers_label})")
    print(f" 該当駅数: {len(items)}駅")
    print(f"{'='*60}")
    print(f" {'駅名':<10} {'時間':>5} {'乗換':>4}  経路")
    print(f"{'-'*60}")
    for st, t, tr, route in items:
        print(f" {st:<10} {t:>3}分  {tr:>2}回  {route}")
    print(f"{'='*60}")


if __name__ == "__main__":
    main()

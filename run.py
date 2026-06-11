#!/usr/bin/env python3
"""2026 世界杯夺冠概率预测 — 入口脚本。

用法：
    python3 run.py                 # 默认模拟 10000 届
    python3 run.py --sims 50000    # 自定义模拟次数
    python3 run.py --refresh       # 强制重新下载最新数据（如小组赛已开打）
    python3 run.py --seed 42       # 固定随机种子以复现结果

输出：
    控制台预测表 + output/forecast.csv + output/group_match_probs.csv
"""

import argparse
import csv
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from src import fetch
from src.elo import compute_ratings, HOME_ADVANTAGE
from src.model import GoalModel
from src.simulate import Tournament, Simulator, HOSTS, STAGE_ORDER

OUTPUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "output")


def main():
    ap = argparse.ArgumentParser(description="2026 世界杯蒙特卡洛预测")
    ap.add_argument("--sims", type=int, default=10000, help="模拟届数（默认 10000）")
    ap.add_argument("--refresh", action="store_true", help="强制刷新数据缓存")
    ap.add_argument("--seed", type=int, default=None, help="随机种子")
    args = ap.parse_args()

    print("[1/4] 获取真实数据（FIFA 官方赛程 + 历史赛果库）...")
    history_path = fetch.history_csv_path(refresh=args.refresh)
    fifa_results = fetch.fixtures(refresh=args.refresh)

    print("[2/4] 回放历史赛果计算 Elo 评分...")
    t0 = time.time()
    ratings, samples = compute_ratings(history_path)
    print(f"  完成：{len(ratings)} 支球队，耗时 {time.time() - t0:.1f}s")

    print("[3/4] 用历史进球数据校准泊松模型...")
    model = GoalModel(samples)
    print(
        f"  λ(d) = exp({model.a:.4f} + {model.b:.6f}·d)，"
        f"校准样本 {model.n_samples} 条"
    )

    tournament = Tournament(fifa_results)

    # 参赛队 Elo 一览
    elo_sorted = sorted(
        tournament.teams, key=lambda x: ratings[x], reverse=True
    )
    print("\n  本届 48 队 Elo 前 10：")
    for x in elo_sorted[:10]:
        host_mark = "（东道主）" if x in HOSTS else ""
        print(f"    {ratings[x]:7.1f}  {x}{host_mark}")

    print(f"\n[4/4] 蒙特卡洛模拟 {args.sims} 届...")
    t0 = time.time()
    sim = Simulator(tournament, ratings, model, seed=args.seed)
    probs = sim.run(args.sims)
    print(f"  完成，耗时 {time.time() - t0:.1f}s")

    # 输出
    team_group = {
        team: g for g, members in tournament.groups.items() for team in members
    }
    rows = sorted(probs.items(), key=lambda kv: kv[1]["champion"], reverse=True)

    print(f"\n{'球队':<18s}{'组':>3s}{'Elo':>8s}{'32强':>8s}{'16强':>8s}"
          f"{'8强':>8s}{'4强':>8s}{'决赛':>8s}{'夺冠':>8s}")
    print("-" * 78)
    for team, p in rows[:20]:
        print(
            f"{team:<18s}{team_group[team]:>3s}{ratings[team]:>8.0f}"
            f"{p['round_of_32']:>7.1%} {p['round_of_16']:>7.1%} "
            f"{p['quarter_final']:>7.1%} {p['semi_final']:>7.1%} "
            f"{p['final']:>7.1%} {p['champion']:>7.1%}"
        )

    os.makedirs(OUTPUT_DIR, exist_ok=True)

    forecast_csv = os.path.join(OUTPUT_DIR, "forecast.csv")
    with open(forecast_csv, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["team", "group", "elo"] + STAGE_ORDER[1:])
        for team, p in rows:
            w.writerow(
                [team, team_group[team], round(ratings[team], 1)]
                + [round(p[s], 4) for s in STAGE_ORDER[1:]]
            )

    # 全部 72 场小组赛的解析胜平负概率
    match_csv = os.path.join(OUTPUT_DIR, "group_match_probs.csv")
    with open(match_csv, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["group", "home", "away", "p_home_win", "p_draw", "p_away_win"])
        for g, h, a in tournament.group_matches:
            d = (ratings[h] + (HOME_ADVANTAGE if h in HOSTS else 0)
                 - ratings[a] - (HOME_ADVANTAGE if a in HOSTS else 0))
            pw, pd, pl = model.outcome_probs(d)
            w.writerow([g, h, a, round(pw, 4), round(pd, 4), round(pl, 4)])

    meta = {
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "n_sims": args.sims,
        "seed": args.seed,
        "data_sources": {
            "fixtures": fetch.FIFA_FIXTURES_URL,
            "history": fetch.HISTORY_URL,
        },
        "goal_model": {"a": model.a, "b": model.b, "n_samples": model.n_samples},
    }
    with open(os.path.join(OUTPUT_DIR, "run_meta.json"), "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)

    print(f"\n结果已保存：\n  {forecast_csv}\n  {match_csv}")


if __name__ == "__main__":
    main()

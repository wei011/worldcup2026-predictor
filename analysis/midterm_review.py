#!/usr/bin/env python3
"""期中复盘：小组赛 + 32 强战罢，模型公开交作业。

两件事：
1. 复盘 —— 用 FIFA 官方真实赛果逐场给开赛前的预测打分：
   方向命中率、Brier score（分阶段）、被打脸最狠的场次、最有底气的命中。
2. 重模拟 —— 条件在已发生的真实赛果上（已赛比赛用真实胜者，
   未赛比赛用模型抽样），对剩余赛程做蒙特卡洛，输出最新夺冠概率，
   并与开赛前夜（2026-06-14 发布）的预测对比。

用法：
    python3 analysis/midterm_review.py                # 默认 20000 届
    python3 analysis/midterm_review.py --sims 5000
    python3 analysis/midterm_review.py --refresh      # 先拉最新赛果
"""

import argparse
import json
import os
import sys
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src import fetch
from src.elo import compute_ratings
from src.model import GoalModel
from src.names import normalize
from src.simulate import Simulator, Tournament, STAGE_ORDER
from today import DISPLAY, predict, match_record

OUT_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "output"
)

# 开赛前夜（2026-06-14 公众号发布文章）公开的夺冠概率，用于对比。
# 来源：当日 run.py --sims 20000 输出，已存档于发布文章。
PRE_TOURNAMENT_TITLE_PROBS = {
    "Spain": 0.244, "Argentina": 0.189, "France": 0.096, "England": 0.061,
    "Mexico": 0.059, "Brazil": 0.049, "Colombia": 0.046, "Ecuador": 0.029,
    "Portugal": 0.029, "Netherlands": 0.022,
}


def cn(team):
    return DISPLAY.get(team, (team,))[0]


# ---------- 第 1 部分：复盘 ----------

def review(ratings, model, fixtures):
    """逐场复盘已结束的比赛，返回明细与分阶段汇总。"""
    rows = []
    for m in sorted(fixtures, key=lambda x: x["MatchNumber"]):
        r = match_record(m)
        if not (r["home"] and r["away"] and r["played"] and r["hs"] is not None):
            continue
        w, dr, l, _ = predict(ratings, model, r)
        if r["hs"] > r["as"]:
            actual, vec, p_actual = "主胜", (1, 0, 0), w
        elif r["hs"] < r["as"]:
            actual, vec, p_actual = "客胜", (0, 0, 1), l
        else:
            actual, vec, p_actual = "平局", (0, 1, 0), dr
        pred = max((w, "主胜"), (dr, "平局"), (l, "客胜"))[1]
        brier = sum((p - a) ** 2 for p, a in zip((w, dr, l), vec))
        rows.append({
            "match": m["MatchNumber"], "date": r["date"],
            "stage": r["stage"], "home": r["home"], "away": r["away"],
            "score": f"{r['hs']}:{r['as']}", "actual": actual, "pred": pred,
            "ok": pred == actual, "p_actual": p_actual, "brier": brier,
            "probs": (w, dr, l),
        })

    by_stage = defaultdict(lambda: {"n": 0, "hit": 0, "brier": 0.0})
    for row in rows:
        s = by_stage[row["stage"]]
        s["n"] += 1
        s["hit"] += row["ok"]
        s["brier"] += row["brier"]
    for s in by_stage.values():
        s["brier"] /= s["n"]

    return rows, dict(by_stage)


# ---------- 第 2 部分：条件重模拟 ----------

class MidtermSimulator(Simulator):
    """条件在真实赛果上的模拟器：已赛比赛按真实结果走，未赛比赛抽样。"""

    def __init__(self, tournament, ratings, goal_model, fixtures, seed=None):
        super().__init__(tournament, ratings, goal_model, seed=seed)
        # 已赛淘汰赛：场次号 -> (真实胜者, 真实负者)
        self.actual_ko = {}
        # 已定但未赛的淘汰赛：场次号 -> (主队, 客队)
        self.fixed_pairing = {}
        for m in fixtures:
            stage = m["StageName"][0]["Description"]
            if stage == "First Stage":
                continue
            home = away = None
            if m.get("Home") and m["Home"].get("TeamName"):
                home = normalize(m["Home"]["TeamName"][0]["Description"])
            if m.get("Away") and m["Away"].get("TeamName"):
                away = normalize(m["Away"]["TeamName"][0]["Description"])
            num = m["MatchNumber"]
            if m.get("MatchStatus") == 0 and m.get("Winner") is not None:
                wid = m["Winner"]
                hid = m["Home"].get("IdTeam")
                winner, loser = (home, away) if str(wid) == str(hid) else (away, home)
                self.actual_ko[num] = (winner, loser)
            elif home and away:
                self.fixed_pairing[num] = (home, away)

    def run_once(self):
        reached = {team: "group" for team in self.t.teams}
        match_winner, match_loser = {}, {}

        def resolve(ph, num):
            # 已定对阵/已赛比赛不需要回到小组赛占位符
            if ph.startswith("W"):
                return match_winner[int(ph[1:])]
            if ph.startswith("RU"):
                return match_loser[int(ph[2:])]
            raise KeyError(ph)

        ko_record = {}
        for num, stage, pha, phb in self.t.ko_matches:
            if num in self.actual_ko:
                w, l = self.actual_ko[num]
                t1, t2 = w, l
            else:
                if num in self.fixed_pairing:
                    t1, t2 = self.fixed_pairing[num]
                else:
                    t1, t2 = resolve(pha, num), resolve(phb, num)
                w, l = self.play_knockout(t1, t2)
            if stage != "third_place":
                for x in (t1, t2):
                    reached[x] = stage
            match_winner[num], match_loser[num] = w, l
            ko_record[num] = (t1, t2, w)
            if stage == "final":
                reached[w] = "champion"
        return reached, ko_record


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sims", type=int, default=20000)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--refresh", action="store_true")
    args = ap.parse_args()

    print("[1/3] 加载真实数据与模型...")
    history = fetch.history_csv_path(refresh=args.refresh)
    fixtures = fetch.fixtures(refresh=args.refresh)
    ratings, samples, score_samples = compute_ratings(history)
    model = GoalModel(samples, score_samples)
    tournament = Tournament(fixtures)

    # ----- 复盘 -----
    print("[2/3] 逐场复盘已结束比赛...")
    rows, by_stage = review(ratings, model, fixtures)
    n = len(rows)
    hit = sum(r["ok"] for r in rows)
    brier = sum(r["brier"] for r in rows) / n
    misses = sorted(rows, key=lambda r: -r["brier"])[:5]
    hits = sorted([r for r in rows if r["ok"]], key=lambda r: -r["p_actual"])[:5]
    draws = [r for r in rows if r["actual"] == "平局"]
    draws_called = [r for r in draws if r["ok"]]

    print(f"\n  总战绩：{hit}/{n} = {hit/n:.1%}   平均 Brier {brier:.3f}（乱猜基准 0.667）")
    for stage, s in by_stage.items():
        print(f"    {stage:<14} {s['hit']}/{s['n']} = {s['hit']/s['n']:.1%}   Brier {s['brier']:.3f}")
    print(f"  实际平局 {len(draws)} 场，模型喊对 {len(draws_called)} 场")
    print("\n  被打脸最狠（Brier 最高）：")
    for r in misses:
        print(f"    {r['date']} {cn(r['home'])} {r['score']} {cn(r['away'])}"
              f"  模型给{r['actual']}仅 {r['p_actual']:.0%}  Brier {r['brier']:.3f}")

    # ----- 条件重模拟 -----
    print(f"\n[3/3] 条件重模拟剩余赛程 {args.sims} 届...")
    sim = MidtermSimulator(tournament, ratings, model, fixtures, seed=args.seed)
    full = sim.run_full(args.sims, progress_every=5000)
    probs = full["team_probs"]

    alive = sorted(
        [(t, p) for t, p in probs.items() if p["champion"] > 0],
        key=lambda kv: -kv[1]["champion"],
    )
    print(f"\n  {'球队':<12}{'8强':>8}{'4强':>8}{'决赛':>8}{'夺冠':>8}{'开赛前':>9}{'变化':>9}")
    for t, p in alive:
        pre = PRE_TOURNAMENT_TITLE_PROBS.get(t, 0.0)
        delta = p["champion"] - pre
        print(f"  {cn(t):<12}{p['quarter_final']:>8.1%}{p['semi_final']:>8.1%}"
              f"{p['final']:>8.1%}{p['champion']:>8.1%}{pre:>9.1%}{delta:>+9.1%}")

    os.makedirs(OUT_DIR, exist_ok=True)
    out = {
        "review": {
            "n": n, "hit": hit, "hit_rate": hit / n, "brier": brier,
            "by_stage": by_stage,
            "draws_total": len(draws), "draws_called": len(draws_called),
            "top_misses": misses, "top_hits": hits,
        },
        "resim": {
            "n_sims": args.sims,
            "alive": [
                {"team": t, "cn": cn(t),
                 "qf": p["quarter_final"], "sf": p["semi_final"],
                 "final": p["final"], "champion": p["champion"],
                 "pre": PRE_TOURNAMENT_TITLE_PROBS.get(t, 0.0)}
                for t, p in alive
            ],
        },
        "all_rows": rows,
    }
    path = os.path.join(OUT_DIR, "midterm_review.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    print(f"\n结果已保存：{path}")


if __name__ == "__main__":
    main()

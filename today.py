#!/usr/bin/env python3
"""查看指定日期（默认今天）的世界杯比赛：

- 未开赛的比赛：输出模型预测的胜 / 平 / 负概率与最可能比分
- 已结束的比赛：对比真实赛果，给出模型"战绩单"（命中率 + Brier score）

数据全部来自 FIFA 官方接口的真实赛程与赛果，不含任何手写数据。

用法：
    python3 today.py                 # 今天的比赛（用缓存）
    python3 today.py --date 2026-06-14
    python3 today.py --refresh       # 强制拉取最新赛果
    python3 today.py --scorecard     # 额外打印开赛至今的模型战绩单
"""

import argparse
import datetime as dt
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from src import fetch
from src.elo import compute_ratings, HOME_ADVANTAGE
from src.model import GoalModel
from src.names import normalize
from src.simulate import HOSTS

# 队名 -> (中文名, 旗帜 emoji)，仅用于展示
DISPLAY = {
    "Mexico": ("墨西哥", "🇲🇽"), "South Africa": ("南非", "🇿🇦"),
    "United States": ("美国", "🇺🇸"), "Paraguay": ("巴拉圭", "🇵🇾"),
    "Canada": ("加拿大", "🇨🇦"), "Argentina": ("阿根廷", "🇦🇷"),
    "Spain": ("西班牙", "🇪🇸"), "France": ("法国", "🇫🇷"),
    "England": ("英格兰", "🏴󠁧󠁢󠁥󠁮󠁧󠁿"), "Brazil": ("巴西", "🇧🇷"),
    "Portugal": ("葡萄牙", "🇵🇹"), "Netherlands": ("荷兰", "🇳🇱"),
    "Germany": ("德国", "🇩🇪"), "Belgium": ("比利时", "🇧🇪"),
    "Colombia": ("哥伦比亚", "🇨🇴"), "Ecuador": ("厄瓜多尔", "🇪🇨"),
    "Croatia": ("克罗地亚", "🇭🇷"), "Italy": ("意大利", "🇮🇹"),
    "Uruguay": ("乌拉圭", "🇺🇾"), "Japan": ("日本", "🇯🇵"),
    "Korea Republic": ("韩国", "🇰🇷"), "South Korea": ("韩国", "🇰🇷"),
    "Morocco": ("摩洛哥", "🇲🇦"), "Senegal": ("塞内加尔", "🇸🇳"),
    "Switzerland": ("瑞士", "🇨🇭"), "Denmark": ("丹麦", "🇩🇰"),
    "Haiti": ("海地", "🇭🇹"), "Scotland": ("苏格兰", "🏴󠁧󠁢󠁳󠁣󠁴󠁿"),
    "Australia": ("澳大利亚", "🇦🇺"), "Turkey": ("土耳其", "🇹🇷"),
    "Curaçao": ("库拉索", "🇨🇼"), "Ivory Coast": ("科特迪瓦", "🇨🇮"),
    "Czech Republic": ("捷克", "🇨🇿"),
    "Bosnia and Herzegovina": ("波黑", "🇧🇦"),
}


def label(team):
    cn, flag = DISPLAY.get(team, (team, "🏳️"))
    return f"{flag} {cn}"


def adv(team):
    return HOME_ADVANTAGE if team in HOSTS else 0.0


def load_models(refresh=False):
    """拉取真实数据并返回 (ratings, goal_model, fixture_records)。"""
    history = fetch.history_csv_path(refresh=refresh)
    fixtures = fetch.fixtures(refresh=refresh)
    ratings, samples, score_samples = compute_ratings(history)
    model = GoalModel(samples, score_samples)
    recs = [match_record(m) for m in fixtures]
    recs = [r for r in recs if r["home"] and r["away"]]  # 淘汰赛未定队伍跳过
    return ratings, model, recs


def predict(ratings, model, r):
    """返回 (胜, 平, 负, 最可能比分)。"""
    d = ratings[r["home"]] + adv(r["home"]) - ratings[r["away"]] - adv(r["away"])
    w, dr, l = model.outcome_probs(d)
    la, lb = model.lam(d), model.lam(-d)
    best, bp = (0, 0), -1
    for i in range(6):
        for j in range(6):
            p = (math.exp(-la) * la**i / math.factorial(i)) * \
                (math.exp(-lb) * lb**j / math.factorial(j))
            if p > bp:
                bp, best = p, (i, j)
    return w, dr, l, best


def scorecard_stats(ratings, model, recs):
    """返回 (已结束比赛明细列表, 命中数, 总场次, 平均Brier)。"""
    played = sorted([r for r in recs if r["played"] and r["hs"] is not None],
                    key=lambda r: (r["date"], r["time_utc"]))
    rows, hit, brier = [], 0, 0.0
    for r in played:
        w, dr, l, _ = predict(ratings, model, r)
        if r["hs"] > r["as"]:
            actual, probs = "主胜", (1, 0, 0)
        elif r["hs"] < r["as"]:
            actual, probs = "客胜", (0, 0, 1)
        else:
            actual, probs = "平局", (0, 1, 0)
        pred_max = max((w, "主胜"), (dr, "平局"), (l, "客胜"))[1]
        ok = pred_max == actual
        hit += ok
        brier += sum((p - a) ** 2 for p, a in zip((w, dr, l), probs))
        rows.append({**r, "w": w, "dr": dr, "l": l, "actual": actual, "ok": ok})
    n = len(played)
    return rows, hit, n, (brier / n if n else 0.0)


def match_record(m):
    home = m["Home"]["TeamName"][0]["Description"] if m.get("Home") else None
    away = m["Away"]["TeamName"][0]["Description"] if m.get("Away") else None
    return {
        "date": m["Date"][:10],
        "time_utc": m["Date"][11:16],
        "home": normalize(home) if home else None,
        "away": normalize(away) if away else None,
        "hs": m.get("HomeTeamScore"),
        "as": m.get("AwayTeamScore"),
        "played": m.get("MatchStatus") == 0,
        "stage": m["StageName"][0]["Description"],
        "group": (m.get("GroupName") or [{}])[0].get("Description", ""),
        "city": (m.get("Stadium") or {}).get("CityName", [{}])[0].get("Description", "")
        if isinstance((m.get("Stadium") or {}).get("CityName"), list) else "",
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", default=None, help="YYYY-MM-DD，默认今天")
    ap.add_argument("--refresh", action="store_true")
    ap.add_argument("--scorecard", action="store_true", help="打印开赛至今战绩单")
    args = ap.parse_args()

    target = args.date or dt.date.today().isoformat()

    print("获取真实数据（FIFA 官方赛程/赛果 + 历史赛果库）...")
    ratings, model, recs = load_models(refresh=args.refresh)

    # ---------- 今日比赛 ----------
    today = sorted([r for r in recs if r["date"] == target], key=lambda r: r["time_utc"])
    print(f"\n{'='*60}\n  {target} 比赛 —— 共 {len(today)} 场")
    if not today:
        print("  这一天没有已排定对阵的比赛。")
    for r in today:
        w, dr, l, (gh, ga) = predict(ratings, model, r)
        tag = r["group"] or r["stage"]
        print(f"\n  [{tag}] {r['time_utc']} UTC"
              + (f" · {r['city']}" if r["city"] else ""))
        print(f"  {label(r['home'])}  vs  {label(r['away'])}")
        if r["played"] and r["hs"] is not None:
            res = "主胜" if r["hs"] > r["as"] else ("客胜" if r["hs"] < r["as"] else "平局")
            print(f"  ✅ 已结束：{r['hs']} - {r['as']}（{res}）")
            print(f"     赛前模型：胜 {w:.0%} / 平 {dr:.0%} / 负 {l:.0%}")
        else:
            bar = lambda p: "█" * round(p * 20)
            print(f"     胜 {w:5.1%} {bar(w)}")
            print(f"     平 {dr:5.1%} {bar(dr)}")
            print(f"     负 {l:5.1%} {bar(l)}")
            print(f"     模型最可能比分：{gh} - {ga}")

    # ---------- 战绩单 ----------
    if args.scorecard:
        rows, hit, n, brier = scorecard_stats(ratings, model, recs)
        if rows:
            print(f"\n{'='*60}\n  开赛至今模型战绩单（{n} 场已结束）\n")
            print(f"  {'日期':<11}{'对阵':<22}{'赛果':<8}{'模型(胜/平/负)':<18}{'命中'}")
            for r in rows:
                cn_h = DISPLAY.get(r["home"], (r["home"],))[0]
                cn_a = DISPLAY.get(r["away"], (r["away"],))[0]
                vs = f"{cn_h}-{cn_a}"
                print(f"  {r['date']:<11}{vs:<20}{r['hs']}:{r['as']}   "
                      f"{r['actual']:<6}{r['w']:.0%}/{r['dr']:.0%}/{r['l']:.0%}"
                      f"      {'✅' if r['ok'] else '❌'}")
            print(f"\n  方向命中率：{hit}/{n} = {hit/n:.0%}")
            print(f"  平均 Brier score：{brier:.3f}（越低越好，三类基准 0.667）")


if __name__ == "__main__":
    main()

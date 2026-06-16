#!/usr/bin/env python3
"""攻防分离模型 vs Elo 双泊松：样本外回测（纯标准库）。

动机：德国 7:1 库拉索——单一 Elo 维度抓不住"库拉索防线极弱"。
攻防分离（Maher 1982 / 二元泊松）给每支球队独立的【进攻】和【防守】强度：
    λ主 = exp(c + 主场 + 攻[主] − 防[客])
    λ客 = exp(c +        攻[客] − 防[主])
理论上能比 Elo 更细地刻画"强攻 vs 弱守"，从而更准地预测大比分。

公平性处理：
- Elo 基线用"赛前"评分（持续滚动更新），是很强的对手。
- 攻防强度若一次性拟合会过时，故采用【滚动重拟合】：预测第 Y 年的比赛时，
  只用 [Y−WINDOW, Y) 的历史拟合攻防强度，与 Elo 的滚动性对齐。
- 两个模型都用同一套双泊松 → 胜平负/比分，唯一差异是 λ 的来源。

用法：python3 analysis/backtest_attack_defense.py [--test-since 2022-01-01] [--window 4]
"""

import argparse
import csv
import math
import os
import sys
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src import fetch
from src.elo import (BASE_RATING, HOME_ADVANTAGE, expected_score, k_factor,
                     margin_multiplier)

MAXG = 16


def load_matches(history_path, since=1998):
    """回放 Elo，返回每场 dict：含赛前 Elo 差 + 队名 + 中立标记 + 比分。"""
    ratings = defaultdict(lambda: BASE_RATING)
    out = []
    with open(history_path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            try:
                hs, aws = int(row["home_score"]), int(row["away_score"])
            except (ValueError, TypeError):
                continue
            h, a = row["home_team"], row["away_team"]
            neutral = row["neutral"].strip().upper() == "TRUE"
            adv = 0.0 if neutral else HOME_ADVANTAGE
            diff = ratings[h] + adv - ratings[a]
            if int(row["date"][:4]) >= since:
                out.append({"date": row["date"], "home": h, "away": a,
                            "hs": hs, "as": aws, "neutral": neutral, "diff": diff})
            res = 1.0 if hs > aws else (0.5 if hs == aws else 0.0)
            k = k_factor(row["tournament"]) * margin_multiplier(hs - aws)
            d = k * (res - expected_score(diff))
            ratings[h] += d
            ratings[a] -= d
    return out


# ---------- 攻防分离：迭代比例拟合 (Maher) ----------

def fit_attack_defence(matches, n_iter=40):
    teams = {m["home"] for m in matches} | {m["away"] for m in matches}
    gs, gc = defaultdict(float), defaultdict(float)
    by_team = defaultdict(list)
    tot_goals = 0
    for m in matches:
        gs[m["home"]] += m["hs"]; gc[m["home"]] += m["as"]
        gs[m["away"]] += m["as"]; gc[m["away"]] += m["hs"]
        by_team[m["home"]].append(m); by_team[m["away"]].append(m)
        tot_goals += m["hs"] + m["as"]
    att = {t: 0.0 for t in teams}
    dfn = {t: 0.0 for t in teams}
    c = math.log(max(tot_goals / (2 * len(matches)), 0.3))
    h = 0.25

    def mean(d):
        return sum(d.values()) / len(d)

    for _ in range(n_iter):
        for t in teams:                       # 进攻
            den = 0.0
            for m in by_team[t]:
                if m["home"] == t:
                    den += math.exp(c + (0 if m["neutral"] else h) - dfn[m["away"]])
                else:
                    den += math.exp(c - dfn[m["home"]])
            att[t] = math.log(max(gs[t], 0.5)) - math.log(max(den, 1e-9))
        ma = mean(att)
        for t in teams:
            att[t] -= ma
        for t in teams:                       # 防守
            den = 0.0
            for m in by_team[t]:
                if m["home"] == t:            # 对手客队进球
                    den += math.exp(c + att[m["away"]])
                else:                         # 对手主队进球（可能含主场）
                    den += math.exp(c + (0 if m["neutral"] else h) + att[m["home"]])
            dfn[t] = math.log(max(den, 1e-9)) - math.log(max(gc[t], 0.5))
        md = mean(dfn)
        for t in teams:
            dfn[t] -= md
        # 重新校准全局进球水平 c 与主场 h
        et = eh = ah = 0.0
        for m in matches:
            lh = math.exp(c + (0 if m["neutral"] else h) + att[m["home"]] - dfn[m["away"]])
            la = math.exp(c + att[m["away"]] - dfn[m["home"]])
            et += lh + la
            if not m["neutral"]:
                eh += lh; ah += m["hs"]
        c += math.log(max(tot_goals, 1) / max(et, 1e-9))
        if eh > 0:
            h += math.log(max(ah, 1) / eh)
    return att, dfn, c, h


def ad_lams(m, att, dfn, c, h):
    lh = math.exp(c + (0 if m["neutral"] else h)
                  + att.get(m["home"], 0.0) - dfn.get(m["away"], 0.0))
    la = math.exp(c + att.get(m["away"], 0.0) - dfn.get(m["home"], 0.0))
    return min(8.0, max(0.05, lh)), min(8.0, max(0.05, la))


# ---------- Elo 双泊松基线 ----------

def fit_elo_poisson(matches):
    """IRLS 拟合 ln E[goals]=a+b·diff。"""
    xs, ys = [], []
    for m in matches:
        xs += [m["diff"], -m["diff"]]; ys += [m["hs"], m["as"]]
    a, b = 0.0, 0.0
    for _ in range(40):
        s11 = s1x = sxx = z1 = zx = 0.0
        for x, y in zip(xs, ys):
            mu = math.exp(min(a + b * x, 3.0))
            zz = (a + b * x) + (y - mu) / mu
            s11 += mu; s1x += mu * x; sxx += mu * x * x
            z1 += mu * zz; zx += mu * x * zz
        det = s11 * sxx - s1x * s1x
        if abs(det) < 1e-12:
            break
        a = (z1 * sxx - zx * s1x) / det
        b = (s11 * zx - s1x * z1) / det
    return a, b


def elo_lams(m, a, b):
    lh = min(6.0, max(0.1, math.exp(a + b * m["diff"])))
    la = min(6.0, max(0.1, math.exp(a - b * m["diff"])))
    return lh, la


# ---------- 评估 ----------

def pmf(k, mu):
    return math.exp(-mu + k * math.log(mu) - math.lgamma(k + 1))


def score_match(lh, la, hs, aws):
    ph = [pmf(i, lh) for i in range(MAXG + 1)]
    pa = [pmf(j, la) for j in range(MAXG + 1)]
    w = sum(ph[i] * pa[j] for i in range(MAXG + 1) for j in range(i))
    dr = sum(ph[i] * pa[i] for i in range(MAXG + 1))
    l = max(1e-12, 1 - w - dr)
    nll = -math.log(max(ph[min(hs, MAXG)] * pa[min(aws, MAXG)], 1e-12))
    y = 0 if hs > aws else (1 if hs == aws else 2)
    probs = [w, dr, l]
    brier = sum((probs[k] - (1 if k == y else 0)) ** 2 for k in range(3))
    acc = max(range(3), key=lambda k: probs[k]) == y
    p_big = sum(ph[i] * pa[j] for i in range(MAXG + 1) for j in range(MAXG + 1)
                if abs(i - j) >= 3)
    return nll, brier, acc, p_big


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--test-since", default="2022-01-01")
    ap.add_argument("--window", type=int, default=4, help="攻防滚动拟合窗口(年)")
    ap.add_argument("--refresh", action="store_true")
    args = ap.parse_args()

    print("拉取真实历史赛果并回放 Elo...")
    matches = load_matches(fetch.history_csv_path(refresh=args.refresh), since=1998)
    test = [m for m in matches if m["date"] >= args.test_since]
    print(f"  测试集 {len(test)} 场（{args.test_since} 至今，样本外）")

    elo_train = [m for m in matches if m["date"] < args.test_since]
    a, b = fit_elo_poisson(elo_train)

    print(f"  攻防强度滚动拟合（每年用前 {args.window} 年）...")
    ad_by_year = {}
    for yr in sorted({m["date"][:4] for m in test}):
        y = int(yr)
        win = [m for m in matches if y - args.window <= int(m["date"][:4]) < y]
        ad_by_year[yr] = fit_attack_defence(win) if len(win) > 300 else None

    agg = {"Elo双泊松": [0, 0, 0, 0.0], "攻防分离": [0, 0, 0, 0.0]}
    big_actual = 0
    n = 0
    for m in test:
        if m["hs"] > MAXG or m["as"] > MAXG:
            continue
        n += 1
        big_actual += abs(m["hs"] - m["as"]) >= 3
        r = score_match(*elo_lams(m, a, b), m["hs"], m["as"])
        for i in range(4):
            agg["Elo双泊松"][i] += r[i]
        ad = ad_by_year.get(m["date"][:4])
        lh, la = ad_lams(m, *ad) if ad else elo_lams(m, a, b)
        r = score_match(lh, la, m["hs"], m["as"])
        for i in range(4):
            agg["攻防分离"][i] += r[i]

    print(f"\n  {'模型':<14}{'比分NLL↓':>10}{'Brier↓':>9}{'命中率↑':>9}{'大胜预测':>9}")
    print("  " + "-" * 52)
    for name, (nll, brier, acc, big) in agg.items():
        print(f"  {name:<14}{nll/n:>10.4f}{brier/n:>9.4f}{acc/n:>8.1%}{big/n:>9.1%}")
    print(f"\n  对照：实际大胜(净胜≥3)比例 {big_actual/n:.1%}　测试 {n} 场")

    print("\n  抽查（攻防分离的进攻/防守强度，攻越大越能进、防越小越能守）：")
    ad = ad_by_year.get(max(ad_by_year))
    if ad:
        att, dfn, c, h = ad
        for t in ["Germany", "Curaçao", "Ecuador", "Ivory Coast", "Spain", "Brazil"]:
            if t in att:
                print(f"    {t:<14} 攻 {att[t]:+.2f}  防 {dfn[t]:+.2f}")


if __name__ == "__main__":
    main()

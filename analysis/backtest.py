#!/usr/bin/env python3
"""模型变体回测对比（纯标准库，严格样本外）。

目的：诊断"系统性低估平局"的问题，并量化几种优化方法到底带来多少提升。

流程：
  1. 按时间逐场回放 Elo，记录每场比赛 (日期, 赛前Elo差, 主客比分)；
     —— 关键：记录的是"赛前"评分，无未来信息泄漏。
  2. 按日期切分：训练集（拟合进球模型参数）/ 测试集（样本外评估）。
  3. 比较 4 个变体在测试集上的表现：
        V0 基线   ：双独立泊松 λ(d)=exp(a+b·d)
        V1 +DC    ：Dixon-Coles 低比分相关性修正（拟合 ρ）
        V2 +时间衰减：用时间衰减权重重拟合 λ
        V3 DC+衰减 ：两者叠加
  4. 评估指标：
        Brier(W/D/L)、LogLoss、方向命中率，
        以及"预测平局率 vs 真实平局率"（直接检验诊断）。

用法：python3 analysis/backtest.py [--split 2018-01-01] [--halflife 8]
"""

import argparse
import csv
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src import fetch
from src.elo import (BASE_RATING, HOME_ADVANTAGE, expected_score, k_factor,
                     margin_multiplier)

MAXG = 10  # 比分网格上限


# ---------- 1. 走 Elo，记录每场赛前快照 ----------

def replay(history_path, since=1998):
    from collections import defaultdict
    ratings = defaultdict(lambda: BASE_RATING)
    matches = []  # (date, diff_含主场, hs, as)
    with open(history_path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            try:
                hs, aws = int(row["home_score"]), int(row["away_score"])
            except (ValueError, TypeError):
                continue
            h, a = row["home_team"], row["away_team"]
            adv = 0.0 if row["neutral"].strip().upper() == "TRUE" else HOME_ADVANTAGE
            diff = ratings[h] + adv - ratings[a]
            if int(row["date"][:4]) >= since:
                matches.append((row["date"], diff, hs, aws))
            res = 1.0 if hs > aws else (0.5 if hs == aws else 0.0)
            k = k_factor(row["tournament"]) * margin_multiplier(hs - aws)
            d = k * (res - expected_score(diff))
            ratings[h] += d
            ratings[a] -= d
    return matches


# ---------- 2. 泊松回归（IRLS，支持样本权重） ----------

def fit_poisson(xs, ys, ws):
    """拟合 ln(E[y]) = a + b·x，加权 Poisson GLM。返回 (a, b)。"""
    a, b = 0.0, 0.0
    for _ in range(50):
        s11 = s1x = sxx = z1 = zx = 0.0
        for x, y, w in zip(xs, ys, ws):
            eta = a + b * x
            mu = math.exp(min(eta, 3.0))
            wt = w * mu
            zz = eta + (y - mu) / mu
            s11 += wt
            s1x += wt * x
            sxx += wt * x * x
            z1 += wt * zz
            zx += wt * x * zz
        det = s11 * sxx - s1x * s1x
        if abs(det) < 1e-12:
            break
        na = (z1 * sxx - zx * s1x) / det
        nb = (s11 * zx - s1x * z1) / det
        if abs(na - a) < 1e-9 and abs(nb - b) < 1e-9:
            a, b = na, nb
            break
        a, b = na, nb
    return a, b


def lam(a, b, d):
    eta = max(-12.0, min(2.0, a + b * d))  # 先夹指数再取 exp，防溢出
    return min(4.0, max(0.15, math.exp(eta)))


# ---------- 3. 概率：双泊松 + 可选 Dixon-Coles ----------

def _pois(k, lm):
    return math.exp(-lm) * lm ** k / math.factorial(k)


def tau(i, j, lh, la, rho):
    if i == 0 and j == 0:
        return 1 - lh * la * rho
    if i == 0 and j == 1:
        return 1 + lh * rho
    if i == 1 and j == 0:
        return 1 + la * rho
    if i == 1 and j == 1:
        return 1 - rho
    return 1.0


def wdl(a, b, d, rho=0.0):
    """返回 (P主胜, P平, P负)。rho=0 即纯双泊松。"""
    lh, la = lam(a, b, d), lam(a, b, -d)
    ph = [_pois(i, lh) for i in range(MAXG + 1)]
    pa = [_pois(j, la) for j in range(MAXG + 1)]
    w = dr = l = 0.0
    for i in range(MAXG + 1):
        for j in range(MAXG + 1):
            p = ph[i] * pa[j]
            if rho and (i <= 1 and j <= 1):
                p *= tau(i, j, lh, la, rho)
            if p < 0:
                p = 0.0
            if i > j:
                w += p
            elif i == j:
                dr += p
            else:
                l += p
    t = w + dr + l
    return w / t, dr / t, l / t


def fit_rho(train, a, b):
    """在训练集上用比分似然网格搜索最优 ρ（负值=提升平局）。"""
    best, brho = -1e18, 0.0
    for k in range(-18, 19):
        rho = k * 0.01
        ll = 0.0
        for _, d, hs, aws in train:
            if hs > MAXG or aws > MAXG:
                continue
            lh, la = lam(a, b, d), lam(a, b, -d)
            p = _pois(hs, lh) * _pois(aws, la)
            if hs <= 1 and aws <= 1:
                p *= tau(hs, aws, lh, la, rho)
            ll += math.log(max(p, 1e-12))
        if ll > best:
            best, brho = ll, rho
    return brho


# ---------- 4. 评估 ----------

def outcome(hs, aws):
    return 0 if hs > aws else (1 if hs == aws else 2)  # 主胜/平/负


def evaluate(test, predict):
    n = len(test)
    brier = logloss = acc = pred_draw = 0.0
    actual_draw = 0
    for _, d, hs, aws in test:
        p = predict(d)  # (w, dr, l)
        y = outcome(hs, aws)
        oneh = [1 if k == y else 0 for k in range(3)]
        brier += sum((p[k] - oneh[k]) ** 2 for k in range(3))
        logloss += -math.log(max(p[y], 1e-12))
        acc += (max(range(3), key=lambda k: p[k]) == y)
        pred_draw += p[1]
        actual_draw += (y == 1)
    return {
        "brier": brier / n, "logloss": logloss / n, "acc": acc / n,
        "pred_draw": pred_draw / n, "actual_draw": actual_draw / n, "n": n,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--split", default="2018-01-01", help="训练/测试分界日期")
    ap.add_argument("--halflife", type=float, default=8.0, help="时间衰减半衰期(年)")
    ap.add_argument("--refresh", action="store_true")
    args = ap.parse_args()

    print("拉取真实历史赛果并回放 Elo...")
    hist = fetch.history_csv_path(refresh=args.refresh)
    matches = replay(hist, since=1998)
    train = [m for m in matches if m[0] < args.split]
    test = [m for m in matches if m[0] >= args.split]
    print(f"  训练集 {len(train)} 场（1998 ~ {args.split}）"
          f" / 测试集 {len(test)} 场（{args.split} ~ 今）")

    # 训练样本：每场拆成主、客两条 (diff, goals)
    def samples(weighted):
        xs, ys, ws = [], [], []
        ref = int(args.split[:4])
        for date, d, hs, aws in train:
            w = 1.0
            if weighted:
                age = ref - int(date[:4])
                w = 0.5 ** (age / args.halflife)
            xs += [d, -d]; ys += [hs, aws]; ws += [w, w]
        return xs, ys, ws

    print("\n拟合参数...")
    a0, b0 = fit_poisson(*samples(False))
    aw, bw = fit_poisson(*samples(True))
    rho0 = fit_rho(train, a0, b0)
    rhow = fit_rho(train, aw, bw)
    print(f"  基线 λ(d)=exp({a0:.4f}{b0:+.6f}·d)")
    print(f"  衰减 λ(d)=exp({aw:.4f}{bw:+.6f}·d)（半衰期 {args.halflife:.0f}年）")
    print(f"  Dixon-Coles ρ：基线 {rho0:+.2f}  衰减 {rhow:+.2f}（负值=提升平局）")

    variants = [
        ("V0 基线双泊松", lambda d: wdl(a0, b0, d)),
        ("V1 +Dixon-Coles", lambda d: wdl(a0, b0, d, rho0)),
        ("V2 +时间衰减", lambda d: wdl(aw, bw, d)),
        ("V3 DC+时间衰减", lambda d: wdl(aw, bw, d, rhow)),
    ]

    print(f"\n{'='*72}")
    print(f"  样本外回测（测试集 {len(test)} 场，真实平局率 "
          f"{sum(1 for m in test if m[2]==m[3])/len(test):.1%}）\n")
    print(f"  {'变体':<18}{'Brier↓':>9}{'LogLoss↓':>10}{'命中率↑':>9}"
          f"{'预测平局率':>11}")
    print("  " + "-" * 66)
    base_brier = None
    for name, fn in variants:
        r = evaluate(test, fn)
        if base_brier is None:
            base_brier = r["brier"]
        tag = "" if name.startswith("V0") else \
            f"  ({(r['brier']-base_brier)/base_brier*100:+.1f}%)"
        print(f"  {name:<18}{r['brier']:>9.4f}{r['logloss']:>10.4f}"
              f"{r['acc']:>8.1%}{r['pred_draw']:>10.1%}{tag}")
    print(f"\n  对照：真实平局率 {evaluate(test, variants[0][1])['actual_draw']:.1%}"
          "（基线预测平局率越接近它越好）")
    print("  Brier/LogLoss 越低越好；括号内为相对基线的 Brier 变化。")

    # ---------- 分层：优化到底在哪类比赛上见效 ----------
    slices = {
        "① 实际打平的比赛": [m for m in test if m[2] == m[3]],
        "② 大热门(|Elo差|>200)": [m for m in test if abs(m[1]) > 200],
        "③ 大热门里被逼平的": [m for m in test
                              if abs(m[1]) > 200 and m[2] == m[3]],
    }
    print(f"\n{'='*72}\n  分层 Brier（看优化在哪类比赛见效）—— 这正是昨天失误的类型\n")
    print(f"  {'比赛类型':<24}{'场数':>6}{'V0基线':>10}{'V3 DC+衰减':>12}{'改善':>9}")
    print("  " + "-" * 64)
    for label, sub in slices.items():
        if not sub:
            continue
        e0 = evaluate(sub, variants[0][1])["brier"]  # 注意：勿用 b0/b3，会覆盖拟合系数
        e3 = evaluate(sub, variants[3][1])["brier"]
        print(f"  {label:<24}{len(sub):>6}{e0:>10.4f}{e3:>12.4f}"
              f"{(e3-e0)/e0*100:>8.1f}%")


if __name__ == "__main__":
    main()

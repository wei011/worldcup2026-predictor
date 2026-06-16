#!/usr/bin/env python3
"""针对"比分幅度/爆冷"问题的回测：对比几种进球分布模型（纯标准库，严格样本外）。

动机：德国 7:1 库拉索——模型猜对了赢家，却严重低估了进球数；
泊松分布尾巴太薄，抓不住"豪强血洗鱼腩"的长尾。本脚本逐一回测：

    V0 基线泊松(λ夹板4.0)   —— 当前线上模型的进球分布
    V1 泊松(λ夹板放宽到6.0) —— 验证"夹板是不是元凶"
    V2 负二项分布(拟合离散度) —— 给高比分更肥的尾巴
    V3 负二项 + Dixon-Coles  —— 长尾 + 平局修正叠加

评估指标（测试集 2018-至今，样本外）：
    比分NLL    : 真实比分的负对数似然（越低=越能解释真实比分，含大比分）
    胜平负Brier : 方向概率质量（越低越好）
    命中率      : argmax 是否等于真实胜平负
    大胜召回    : 实际净胜≥3 的比赛里，模型赛前给"净胜≥3"多少概率（越高=越能预见血洗）

用法：python3 analysis/backtest_goals.py [--split 2018-01-01]
"""

import argparse
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from analysis.backtest import replay, fit_poisson
from src import fetch

MAXG = 16  # 比分网格上限（要够大以容纳 7+ 球）


def lam(a, b, d, cap):
    eta = max(-12.0, min(2.5, a + b * d))
    return min(cap, max(0.15, math.exp(eta)))


def pois_pmf(k, mu):
    return math.exp(-mu + k * math.log(mu) - math.lgamma(k + 1))


def nb_pmf(k, mu, r):
    """负二项：均值 mu、离散度 r（r→∞ 退化为泊松，r 越小尾巴越肥）。"""
    p = r / (r + mu)
    return math.exp(
        math.lgamma(k + r) - math.lgamma(r) - math.lgamma(k + 1)
        + r * math.log(p) + k * math.log(1 - p)
    )


def dc_tau(i, j, lh, la, rho):
    if i == 0 and j == 0:
        return 1 - lh * la * rho
    if i == 1 and j == 1:
        return 1 - rho
    if i == 0 and j == 1:
        return 1 + lh * rho
    if i == 1 and j == 0:
        return 1 + la * rho
    return 1.0


def grid(a, b, d, cap, dist, r, rho):
    """返回 16x16 比分联合概率矩阵（已归一化）。"""
    lh, la = lam(a, b, d, cap), lam(a, b, -d, cap)
    if dist == "pois":
        ph = [pois_pmf(i, lh) for i in range(MAXG + 1)]
        pa = [pois_pmf(j, la) for j in range(MAXG + 1)]
    else:
        ph = [nb_pmf(i, lh, r) for i in range(MAXG + 1)]
        pa = [nb_pmf(j, la, r) for j in range(MAXG + 1)]
    M = [[ph[i] * pa[j] for j in range(MAXG + 1)] for i in range(MAXG + 1)]
    if rho:
        for i in (0, 1):
            for j in (0, 1):
                M[i][j] *= dc_tau(i, j, lh, la, rho)
    s = sum(sum(row) for row in M)
    return [[v / s for v in row] for row in M], lh, la


def fit_nb_r(train, a, b, cap):
    """在训练集比分上网格搜索负二项离散度 r（最大化比分似然）。"""
    best, br = -math.inf, 20.0
    for r in [3, 4, 5, 6, 8, 10, 14, 20, 30, 50]:
        ll = 0.0
        for _, d, hs, aws in train:
            if hs > MAXG or aws > MAXG:
                continue
            lh, la = lam(a, b, d, cap), lam(a, b, -d, cap)
            ll += math.log(max(nb_pmf(hs, lh, r) * nb_pmf(aws, la, r), 1e-12))
        if ll > best:
            best, br = ll, r
    return br


def fit_rho(train, a, b, cap):
    best, brho = -math.inf, 0.0
    for k in range(-15, 1):
        rho = k * 0.01
        ll = 0.0
        for _, d, hs, aws in train:
            if hs > 1 and aws > 1:
                continue
            lh, la = lam(a, b, d, cap), lam(a, b, -d, cap)
            p = pois_pmf(hs, lh) * pois_pmf(aws, la) * dc_tau(hs, aws, lh, la, rho)
            ll += math.log(max(p, 1e-12))
        if ll > best:
            best, brho = ll, rho
    return brho


def evaluate(test, a, b, cap, dist, r, rho):
    n = 0
    nll = brier = acc = 0.0
    big_actual = big_pred_sum = 0
    for _, d, hs, aws in test:
        if hs > MAXG or aws > MAXG:
            continue
        n += 1
        M, lh, la = grid(a, b, d, cap, dist, r, rho)
        # 比分似然
        nll += -math.log(max(M[hs][aws], 1e-12))
        # 胜平负
        w = sum(M[i][j] for i in range(MAXG + 1) for j in range(i))
        dr = sum(M[i][i] for i in range(MAXG + 1))
        l = 1 - w - dr
        y = 0 if hs > aws else (1 if hs == aws else 2)
        oneh = [1 if k == y else 0 for k in range(3)]
        probs = [w, dr, l]
        brier += sum((probs[k] - oneh[k]) ** 2 for k in range(3))
        acc += (max(range(3), key=lambda k: probs[k]) == y)
        # 大胜（净胜≥3）校准
        p_big = sum(M[i][j] for i in range(MAXG + 1) for j in range(MAXG + 1)
                    if abs(i - j) >= 3)
        big_pred_sum += p_big
        if abs(hs - aws) >= 3:
            big_actual += 1
    return {
        "nll": nll / n, "brier": brier / n, "acc": acc / n,
        "big_pred": big_pred_sum / n, "big_actual": big_actual / n, "n": n,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--split", default="2018-01-01")
    ap.add_argument("--refresh", action="store_true")
    args = ap.parse_args()

    print("拉取真实历史赛果并回放 Elo...")
    hist = fetch.history_csv_path(refresh=args.refresh)
    matches = replay(hist, since=1998)
    train = [m for m in matches if m[0] < args.split]
    test = [m for m in matches if m[0] >= args.split]
    print(f"  训练 {len(train)} 场 / 测试 {len(test)} 场（样本外）")

    xs, ys, ws = [], [], []
    for _, d, hs, aws in train:
        xs += [d, -d]; ys += [hs, aws]; ws += [1.0, 1.0]
    a, b = fit_poisson(xs, ys, ws)
    r = fit_nb_r(train, a, b, 4.0)
    rho = fit_rho(train, a, b, 4.0)
    print(f"  λ(d)=exp({a:.4f}{b:+.6f}·d) | 负二项 r={r:.0f} | DC ρ={rho:+.2f}\n")

    variants = [
        ("V0 基线泊松(夹板4.0)", dict(cap=4.0, dist="pois", r=r, rho=0.0)),
        ("V1 泊松(夹板放宽6.0)", dict(cap=6.0, dist="pois", r=r, rho=0.0)),
        ("V2 负二项(肥尾)",     dict(cap=6.0, dist="nb", r=r, rho=0.0)),
        ("V3 负二项+DixonColes", dict(cap=6.0, dist="nb", r=r, rho=rho)),
    ]
    print(f"  {'变体':<22}{'比分NLL↓':>10}{'Brier↓':>9}{'命中率↑':>9}"
          f"{'大胜预测':>9}{'实际大胜':>9}")
    print("  " + "-" * 70)
    for name, kw in variants:
        e = evaluate(test, a, b, **kw)
        print(f"  {name:<22}{e['nll']:>10.4f}{e['brier']:>9.4f}{e['acc']:>8.1%}"
              f"{e['big_pred']:>9.1%}{e['big_actual']:>9.1%}")
    print("\n  比分NLL：真实比分的负对数似然，越低=越能解释含大比分在内的真实结果。")
    print("  大胜预测 vs 实际大胜：净胜≥3 的概率校准，越接近越好（检验能否预见血洗）。")


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""喂"近期状态"特征：Elo 之外，近期进攻/防守势头有没有增量价值？（纯标准库，样本外）

思路：当前进球模型只用 Elo 差。这里额外喂入两个【从现有真实数据提取、模型没用过】
的赛前特征——每队最近 K 场的场均进球(攻势)与场均失球(守势)——做多元泊松回归：
    ln λ主 = β0 + β1·Elo差 + β2·主队近期攻势 + β3·客队近期守势
    ln λ客 = β0 − β1·Elo差 + β2·客队近期攻势 + β3·主队近期守势
对比只用 Elo 的基线，看 β2/β3 是否带来样本外提升。所有特征均为"赛前"快照，无泄漏。

用法：python3 analysis/backtest_form.py [--test-since 2022-01-01] [--k 10]
"""

import argparse
import math
import os
import sys
from collections import defaultdict, deque

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from analysis.backtest_attack_defense import load_matches, pmf, score_match
from src import fetch

MAXG = 16


def attach_form(matches, k):
    """给每场附加赛前近期状态特征（场均进球/失球，最近 k 场）。"""
    hist = defaultdict(lambda: deque(maxlen=k))  # team -> [(gf, ga), ...]
    gsum = gcnt = 0.0
    for m in matches:
        gsum += m["hs"] + m["as"]; gcnt += 2
    league_avg = gsum / gcnt  # 全局场均进球，作为无历史时的兜底

    def form(t):
        dq = hist[t]
        if len(dq) < 3:
            return league_avg, league_avg
        gf = sum(x[0] for x in dq) / len(dq)
        ga = sum(x[1] for x in dq) / len(dq)
        return gf, ga

    for m in matches:
        hgf, hga = form(m["home"])
        agf, aga = form(m["away"])
        m["h_gf"], m["h_ga"] = hgf, hga
        m["a_gf"], m["a_ga"] = agf, aga
        m["lavg"] = league_avg
        hist[m["home"]].append((m["hs"], m["as"]))
        hist[m["away"]].append((m["as"], m["hs"]))
    return league_avg


def solve(A, rhs):
    """解小型线性方程组 A x = rhs（高斯消元）。"""
    n = len(rhs)
    M = [row[:] + [rhs[i]] for i, row in enumerate(A)]
    for col in range(n):
        piv = max(range(col, n), key=lambda r: abs(M[r][col]))
        M[col], M[piv] = M[piv], M[col]
        if abs(M[col][col]) < 1e-12:
            return None
        for r in range(n):
            if r != col:
                f = M[r][col] / M[col][col]
                for cc in range(col, n + 1):
                    M[r][cc] -= f * M[col][cc]
    return [M[i][n] / M[i][i] for i in range(n)]


def fit_poisson_mv(rows, p):
    """多元泊松 IRLS。rows: [(x_vec, y)]，返回 beta(长度 p)。"""
    beta = [0.0] * p
    for _ in range(40):
        A = [[0.0] * p for _ in range(p)]
        rhs = [0.0] * p
        for x, y in rows:
            eta = sum(beta[j] * x[j] for j in range(p))
            mu = math.exp(min(eta, 3.0))
            z = eta + (y - mu) / mu
            for i in range(p):
                rhs[i] += mu * z * x[i]
                for j in range(p):
                    A[i][j] += mu * x[i] * x[j]
        nb = solve(A, rhs)
        if nb is None:
            break
        if max(abs(nb[i] - beta[i]) for i in range(p)) < 1e-9:
            beta = nb
            break
        beta = nb
    return beta


def feats(m, with_form):
    """返回 (主队进球特征向量, 客队进球特征向量)。"""
    la = m["lavg"]
    if not with_form:
        return [1.0, m["diff"]], [1.0, -m["diff"]]
    # 中心化近期特征（减去联赛均值），列：[截距, Elo差, 本方攻势, 对方守势]
    home = [1.0, m["diff"], m["h_gf"] - la, m["a_ga"] - la]
    away = [1.0, -m["diff"], m["a_gf"] - la, m["h_ga"] - la]
    return home, away


def lam_of(beta, x):
    return min(6.0, max(0.1, math.exp(sum(beta[j] * x[j] for j in range(len(beta))))))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--test-since", default="2022-01-01")
    ap.add_argument("--k", type=int, default=10, help="近期场数")
    ap.add_argument("--refresh", action="store_true")
    args = ap.parse_args()

    print("拉取真实历史赛果并回放 Elo...")
    matches = load_matches(fetch.history_csv_path(refresh=args.refresh), since=1998)
    attach_form(matches, args.k)
    train = [m for m in matches if m["date"] < args.test_since]
    test = [m for m in matches if m["date"] >= args.test_since]
    print(f"  训练 {len(train)} / 测试 {len(test)} 场（样本外，近期窗口 {args.k} 场）")

    variants = [("V0 仅 Elo", False), ("V1 Elo + 近期状态", True)]
    fitted = {}
    for name, wf in variants:
        rows = []
        for m in train:
            h, a = feats(m, wf)
            rows.append((h, m["hs"])); rows.append((a, m["as"]))
        fitted[name] = fit_poisson_mv(rows, len(rows[0][0]))

    print(f"\n  {'模型':<18}{'比分NLL↓':>10}{'Brier↓':>9}{'命中率↑':>9}")
    print("  " + "-" * 46)
    for name, wf in variants:
        beta = fitted[name]
        nll = brier = acc = 0.0
        n = 0
        for m in test:
            if m["hs"] > MAXG or m["as"] > MAXG:
                continue
            n += 1
            h, a = feats(m, wf)
            r = score_match(lam_of(beta, h), lam_of(beta, a), m["hs"], m["as"])
            nll += r[0]; brier += r[1]; acc += r[2]
        print(f"  {name:<18}{nll/n:>10.4f}{brier/n:>9.4f}{acc/n:>8.1%}")
    print(f"\n  V1 拟合系数 β = {[round(x,4) for x in fitted['V1 Elo + 近期状态']]}")
    print("  （顺序：截距 / Elo差 / 本方近期攻势 / 对方近期守势；后两者越偏离0说明越有增量信息）")


if __name__ == "__main__":
    main()

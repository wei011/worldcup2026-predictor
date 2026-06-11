"""Elo 评分计算：逐场回放全部真实历史赛果，得到每支国家队的当前 Elo。

方法论与 World Football Elo Ratings（eloratings.net）一致：
- 初始分 1500
- K 值按赛事重要性分级：世界杯正赛 60、洲际大赛 50、预选赛 40、
  其他赛事 30、友谊赛 20
- 净胜球放大系数：净胜 1 球 ×1.0，2 球 ×1.5，N>=3 球 ×(11+N)/8
- 主场优势：非中立场地主队 +100 Elo

同时在回放过程中收集 (Elo 差, 实际进球数) 样本，供进球模型校准使用。
"""

import csv
from collections import defaultdict

BASE_RATING = 1500.0
HOME_ADVANTAGE = 100.0

_MAJOR_TOURNAMENTS = (
    "fifa world cup",
    "uefa euro",
    "copa américa",
    "copa america",
    "african cup of nations",
    "africa cup of nations",
    "afc asian cup",
    "concacaf championship",
    "gold cup",
    "oceania nations cup",
    "confederations cup",
    "uefa nations league finals",
)


def k_factor(tournament):
    t = tournament.lower()
    if "friendly" in t:
        return 20.0
    if "qualification" in t or "qualifying" in t:
        return 40.0
    if t == "fifa world cup":
        return 60.0
    if any(t == m or t.startswith(m) for m in _MAJOR_TOURNAMENTS):
        return 50.0
    return 30.0


def margin_multiplier(goal_diff):
    gd = abs(goal_diff)
    if gd <= 1:
        return 1.0
    if gd == 2:
        return 1.5
    return (11 + gd) / 8.0


def expected_score(rating_diff):
    return 1.0 / (1.0 + 10.0 ** (-rating_diff / 400.0))


def compute_ratings(history_path, calibration_since=1998):
    """回放历史赛果，返回 (ratings, calibration_samples)。

    calibration_samples: [(elo_diff_含主场, 该方实际进球数), ...]
    只采集 calibration_since 年之后的样本——此时各队评分已充分收敛，
    且更接近现代足球的进球水平。
    """
    ratings = defaultdict(lambda: BASE_RATING)
    samples = []

    with open(history_path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            try:
                hs = int(row["home_score"])
                aws = int(row["away_score"])
            except (ValueError, TypeError):
                continue  # 未完赛/数据缺失的场次

            home, away = row["home_team"], row["away_team"]
            neutral = row["neutral"].strip().upper() == "TRUE"
            adv = 0.0 if neutral else HOME_ADVANTAGE
            diff = ratings[home] + adv - ratings[away]

            if int(row["date"][:4]) >= calibration_since:
                samples.append((diff, hs))
                samples.append((-diff, aws))

            if hs > aws:
                result = 1.0
            elif hs == aws:
                result = 0.5
            else:
                result = 0.0

            k = k_factor(row["tournament"]) * margin_multiplier(hs - aws)
            delta = k * (result - expected_score(diff))
            ratings[home] += delta
            ratings[away] -= delta

    return dict(ratings), samples

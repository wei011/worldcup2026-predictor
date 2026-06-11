"""进球模型：把 Elo 差转换成两队的进球期望（泊松强度 λ）。

参数不是拍脑袋定的，而是用历史真实赛果校准：
把 1998 年以来每场比赛拆成两条 (Elo 差 d, 实际进球数 g) 样本，
按 d 分桶求平均进球，再对 ln(平均进球) ~ d 做加权最小二乘，
得到 λ(d) = exp(a + b·d)。

模拟比分时按 λ 抽样泊松分布，胜/平/负与净胜球自然涌现，
小组赛积分、净胜球等真实判定规则都能直接套用。
"""

import math

BIN_WIDTH = 50
MAX_ABS_DIFF = 600
MIN_BIN_SAMPLES = 200
LAMBDA_MIN, LAMBDA_MAX = 0.15, 4.0  # 安全夹板，防止极端 Elo 差外推失真


class GoalModel:
    def __init__(self, samples):
        bins = {}
        for d, g in samples:
            b = round(d / BIN_WIDTH) * BIN_WIDTH
            if abs(b) > MAX_ABS_DIFF:
                continue
            tot, n = bins.get(b, (0, 0))
            bins[b] = (tot + g, n + 1)

        points = [
            (b, tot / n, n)
            for b, (tot, n) in bins.items()
            if n >= MIN_BIN_SAMPLES and tot > 0
        ]
        if len(points) < 5:
            raise RuntimeError("校准样本不足，无法拟合进球模型")

        # 加权最小二乘：ln(mean_goals) = a + b * elo_diff
        s = sx = sy = sxx = sxy = 0.0
        for x, mean_g, w in points:
            y = math.log(mean_g)
            s += w
            sx += w * x
            sy += w * y
            sxx += w * x * x
            sxy += w * x * y
        self.b = (s * sxy - sx * sy) / (s * sxx - sx * sx)
        self.a = (sy - self.b * sx) / s
        self.n_samples = sum(n for _, _, n in points)

    def lam(self, elo_diff):
        return min(LAMBDA_MAX, max(LAMBDA_MIN, math.exp(self.a + self.b * elo_diff)))

    @staticmethod
    def poisson_sample(lam, rng):
        # Knuth 算法，λ<=4 时足够高效
        limit = math.exp(-lam)
        k, p = 0, 1.0
        while p > limit:
            k += 1
            p *= rng.random()
        return k - 1

    def outcome_probs(self, elo_diff, max_goals=12):
        """解析计算单场胜/平/负概率（双泊松，截断到 max_goals）。"""
        la, lb = self.lam(elo_diff), self.lam(-elo_diff)
        pa = [math.exp(-la) * la**i / math.factorial(i) for i in range(max_goals + 1)]
        pb = [math.exp(-lb) * lb**i / math.factorial(i) for i in range(max_goals + 1)]
        win = draw = loss = 0.0
        for i, p1 in enumerate(pa):
            for j, p2 in enumerate(pb):
                if i > j:
                    win += p1 * p2
                elif i == j:
                    draw += p1 * p2
                else:
                    loss += p1 * p2
        total = win + draw + loss
        return win / total, draw / total, loss / total

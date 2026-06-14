"""进球模型：把 Elo 差转换成两队的进球期望（泊松强度 λ）。

参数不是拍脑袋定的，而是用历史真实赛果校准：
把 1998 年以来每场比赛拆成两条 (Elo 差 d, 实际进球数 g) 样本，
按 d 分桶求平均进球，再对 ln(平均进球) ~ d 做加权最小二乘，
得到 λ(d) = exp(a + b·d)。

在双泊松之上叠加 Dixon-Coles (1997) 低比分相关性修正：独立双泊松会
系统性低估平局（实测预测平局率 20.8% vs 真实 23.1%），DC 用一个参数 ρ
对四种低比分（0:0/1:1/0:1/1:0）的联合概率做修正，把被压低的平局概率
调回真实频率。ρ 同样由历史比分用极大似然拟合，不是手设的。
依据见 analysis/backtest.py 的样本外回测。

模拟比分时按 λ 抽样泊松分布，胜/平/负与净胜球自然涌现，
小组赛积分、净胜球等真实判定规则都能直接套用。
"""

import math

BIN_WIDTH = 50
MAX_ABS_DIFF = 600
MIN_BIN_SAMPLES = 200
LAMBDA_MIN, LAMBDA_MAX = 0.15, 4.0  # 安全夹板，防止极端 Elo 差外推失真
RHO_GRID = [k * 0.01 for k in range(-18, 19)]  # Dixon-Coles ρ 搜索范围


def dc_tau(i, j, lam_a, lam_b, rho):
    """Dixon-Coles 低比分修正系数；仅对 i,j∈{0,1} 生效，其余返回 1。

    lam_a 为"这一方"(i 球) 的强度，lam_b 为对手 (j 球) 的强度。
    ρ<0 时提升 0:0 与 1:1（平局），压低 1:0 与 0:1。
    """
    if i == 0 and j == 0:
        return 1.0 - lam_a * lam_b * rho
    if i == 1 and j == 1:
        return 1.0 - rho
    if i == 0 and j == 1:
        return 1.0 + lam_a * rho
    if i == 1 and j == 0:
        return 1.0 + lam_b * rho
    return 1.0


class GoalModel:
    def __init__(self, samples, score_samples=None):
        """samples: [(elo_diff, 该方进球)]，用于拟合 λ(d)。
        score_samples: 可选 [(elo_diff, 主队进球, 客队进球)]，用于拟合 DC 的 ρ；
        不提供则 ρ=0，退化为纯双泊松（向后兼容）。
        """
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

        self.rho = self._fit_rho(score_samples) if score_samples else 0.0
        self.n_score_samples = len(score_samples) if score_samples else 0

    def _fit_rho(self, score_samples):
        """在历史比分上用极大似然网格搜索最优 ρ。"""
        best_ll, best_rho = -math.inf, 0.0
        for rho in RHO_GRID:
            ll = 0.0
            for d, hs, aws in score_samples:
                if hs > 1 and aws > 1:
                    continue  # τ=1 的格子不影响 ρ 的相对似然，可跳过加速
                la, lb = self.lam(d), self.lam(-d)
                p = (math.exp(-la) * la ** hs / math.factorial(hs)
                     * math.exp(-lb) * lb ** aws / math.factorial(aws))
                p *= dc_tau(hs, aws, la, lb, rho)
                ll += math.log(max(p, 1e-12))
            if ll > best_ll:
                best_ll, best_rho = ll, rho
        return best_rho

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
        """解析计算单场胜/平/负概率（双泊松 + Dixon-Coles 修正）。"""
        la, lb = self.lam(elo_diff), self.lam(-elo_diff)
        pa = [math.exp(-la) * la**i / math.factorial(i) for i in range(max_goals + 1)]
        pb = [math.exp(-lb) * lb**i / math.factorial(i) for i in range(max_goals + 1)]
        win = draw = loss = 0.0
        for i, p1 in enumerate(pa):
            for j, p2 in enumerate(pb):
                p = p1 * p2
                if self.rho and i <= 1 and j <= 1:
                    p *= dc_tau(i, j, la, lb, self.rho)
                if p < 0:
                    p = 0.0
                if i > j:
                    win += p
                elif i == j:
                    draw += p
                else:
                    loss += p
        total = win + draw + loss
        return win / total, draw / total, loss / total

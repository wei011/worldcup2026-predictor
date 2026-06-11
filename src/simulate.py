"""蒙特卡洛模拟整届 2026 世界杯。

赛制结构（小组、对阵图、第三名晋级槽位）全部解析自 FIFA 官方赛程数据
中的真实占位符（如 "1A"、"2B"、"3ABCDF"、"W73"、"RU101"），不手写对阵图。

模拟规则：
- 小组赛排名：积分 → 净胜球 → 进球数 →（仍并列时）相互战绩 → 抽签
- 12 个小组第三名按 积分 → 净胜球 → 进球数 → 抽签 取前 8 名晋级，
  并按对阵图中各槽位允许的小组集合做约束分配（随机化回溯求可行解）
- 淘汰赛打平：加时按常规时间 1/3 强度的泊松再抽样；仍平则点球大战，
  双方各 50% 胜率
- 主场优势：东道主（美国、墨西哥、加拿大）比赛时 +100 Elo
"""

import random
from collections import defaultdict

from .elo import HOME_ADVANTAGE
from .names import normalize

HOSTS = {"United States", "Mexico", "Canada"}

STAGE_ORDER = [
    "group",        # 进入正赛（48 队全部计入）
    "round_of_32",
    "round_of_16",
    "quarter_final",
    "semi_final",
    "final",
    "champion",
]

_STAGE_BY_NAME = {
    "Round of 32": "round_of_32",
    "Round of 16": "round_of_16",
    "Quarter-final": "quarter_final",
    "Semi-final": "semi_final",
    "Play-off for third place": "third_place",
    "Final": "final",
}


class Tournament:
    """从 FIFA 原始赛程记录解析出可模拟的赛制结构。"""

    def __init__(self, fifa_results):
        self.group_matches = []          # (组别, 主队, 客队)
        self.groups = defaultdict(set)   # 组别 -> 队名集合
        self.ko_matches = []             # (场次号, 阶段, 占位符A, 占位符B)

        for m in sorted(fifa_results, key=lambda x: x["MatchNumber"]):
            stage = m["StageName"][0]["Description"]
            if stage == "First Stage":
                g = m["GroupName"][0]["Description"].split()[-1]
                h = normalize(m["Home"]["TeamName"][0]["Description"])
                a = normalize(m["Away"]["TeamName"][0]["Description"])
                self.group_matches.append((g, h, a))
                self.groups[g].update((h, a))
            else:
                self.ko_matches.append(
                    (
                        m["MatchNumber"],
                        _STAGE_BY_NAME[stage],
                        m["PlaceHolderA"],
                        m["PlaceHolderB"],
                    )
                )

        self.teams = sorted(t for g in self.groups.values() for t in g)
        assert len(self.teams) == 48, f"应有 48 队，解析到 {len(self.teams)}"
        assert len(self.group_matches) == 72
        assert len(self.ko_matches) == 32


def _adv(team):
    return HOME_ADVANTAGE if team in HOSTS else 0.0


class Simulator:
    def __init__(self, tournament, ratings, goal_model, seed=None):
        self.t = tournament
        self.model = goal_model
        self.rng = random.Random(seed)
        missing = [x for x in tournament.teams if x not in ratings]
        if missing:
            raise RuntimeError(f"以下球队在历史数据中无 Elo 评分：{missing}")
        self.ratings = ratings

    # ---------- 单场 ----------

    def _diff(self, t1, t2):
        return self.ratings[t1] + _adv(t1) - self.ratings[t2] - _adv(t2)

    def play(self, t1, t2):
        d = self._diff(t1, t2)
        g1 = self.model.poisson_sample(self.model.lam(d), self.rng)
        g2 = self.model.poisson_sample(self.model.lam(-d), self.rng)
        return g1, g2

    def play_knockout(self, t1, t2):
        g1, g2 = self.play(t1, t2)
        if g1 == g2:  # 加时：约为常规时间 1/3 的进球强度
            d = self._diff(t1, t2)
            g1 += self.model.poisson_sample(self.model.lam(d) / 3.0, self.rng)
            g2 += self.model.poisson_sample(self.model.lam(-d) / 3.0, self.rng)
        if g1 == g2:  # 点球大战：50/50
            return (t1, t2) if self.rng.random() < 0.5 else (t2, t1)
        return (t1, t2) if g1 > g2 else (t2, t1)

    # ---------- 小组赛 ----------

    def _rank_group(self, teams, results):
        # stats: 队 -> [积分, 净胜球, 进球]
        stats = {x: [0, 0, 0] for x in teams}
        for h, a, gh, ga in results:
            stats[h][1] += gh - ga
            stats[a][1] += ga - gh
            stats[h][2] += gh
            stats[a][2] += ga
            if gh > ga:
                stats[h][0] += 3
            elif gh < ga:
                stats[a][0] += 3
            else:
                stats[h][0] += 1
                stats[a][0] += 1

        order = sorted(teams, key=lambda x: stats[x], reverse=True)

        # 积分/净胜球/进球全部相同的队之间：相互战绩，再不行抽签
        resolved = []
        i = 0
        while i < len(order):
            j = i
            while j < len(order) and stats[order[j]] == stats[order[i]]:
                j += 1
            tied = order[i:j]
            if len(tied) > 1:
                tied_set = set(tied)
                h2h = {x: [0, 0, 0] for x in tied}
                for h, a, gh, ga in results:
                    if h in tied_set and a in tied_set:
                        h2h[h][1] += gh - ga
                        h2h[a][1] += ga - gh
                        h2h[h][2] += gh
                        h2h[a][2] += ga
                        if gh > ga:
                            h2h[h][0] += 3
                        elif gh < ga:
                            h2h[a][0] += 3
                        else:
                            h2h[h][0] += 1
                            h2h[a][0] += 1
                tied.sort(
                    key=lambda x: (h2h[x][0], h2h[x][1], h2h[x][2], self.rng.random()),
                    reverse=True,
                )
            resolved.extend(tied)
            i = j
        return resolved, stats

    # ---------- 第三名分配 ----------

    def _assign_thirds(self, slots, qualified_letters):
        """slots: [(场次号, 允许的小组字母集合)]；返回 场次号->小组字母。

        随机化回溯：FIFA 对阵图保证任意 8/12 组合存在可行分配。
        """
        letters = list(qualified_letters)
        self.rng.shuffle(letters)
        slot_order = sorted(
            slots, key=lambda s: len(s[1] & qualified_letters)
        )

        assignment = {}

        def backtrack(idx, remaining):
            if idx == len(slot_order):
                return True
            num, allowed = slot_order[idx]
            for letter in list(remaining):
                if letter in allowed:
                    assignment[num] = letter
                    remaining.remove(letter)
                    if backtrack(idx + 1, remaining):
                        return True
                    remaining.add(letter)
                    del assignment[num]
            return False

        if not backtrack(0, set(letters)):
            raise RuntimeError(f"第三名分配无可行解：{sorted(qualified_letters)}")
        return assignment

    # ---------- 整届 ----------

    def run_once(self):
        """模拟一届。

        返回 (reached, ko_record)：
        - reached: 队 -> 到达的最远阶段（STAGE_ORDER 中的名字）
        - ko_record: 淘汰赛场次号 -> (A方球队, B方球队, 胜者)
        """
        reached = {team: "group" for team in self.t.teams}

        # 小组赛
        group_results = defaultdict(list)
        for g, h, a in self.t.group_matches:
            gh, ga = self.play(h, a)
            group_results[g].append((h, a, gh, ga))

        winners, runners, third_pool = {}, {}, {}
        for g, teams in self.t.groups.items():
            order, stats = self._rank_group(list(teams), group_results[g])
            winners[g], runners[g] = order[0], order[1]
            third_pool[g] = (order[2], stats[order[2]])

        # 12 个第三名取最好的 8 个
        third_ranked = sorted(
            third_pool.items(),
            key=lambda kv: (kv[1][1][0], kv[1][1][1], kv[1][1][2], self.rng.random()),
            reverse=True,
        )
        qualified_letters = {g for g, _ in third_ranked[:8]}

        third_slots = []
        for num, stage, pha, phb in self.t.ko_matches:
            for ph in (pha, phb):
                if ph and ph.startswith("3"):
                    third_slots.append((num, set(ph[1:])))
        third_assignment = self._assign_thirds(third_slots, qualified_letters)

        # 淘汰赛（按场次号顺序，占位符逐场解析）
        match_winner, match_loser = {}, {}

        def resolve(ph, num):
            if ph.startswith("W"):
                return match_winner[int(ph[1:])]
            if ph.startswith("RU"):
                return match_loser[int(ph[2:])]
            if ph.startswith("1"):
                return winners[ph[1]]
            if ph.startswith("2"):
                return runners[ph[1]]
            if ph.startswith("3"):
                return third_pool[third_assignment[num]][0]
            raise ValueError(f"未知占位符: {ph}")

        ko_record = {}
        for num, stage, pha, phb in self.t.ko_matches:
            t1, t2 = resolve(pha, num), resolve(phb, num)
            if stage != "third_place":
                reached[t1] = stage
                reached[t2] = stage
            w, l = self.play_knockout(t1, t2)
            match_winner[num], match_loser[num] = w, l
            ko_record[num] = (t1, t2, w)
            if stage == "final":
                reached[w] = "champion"

        return reached, ko_record

    def run(self, n_sims, progress_every=2000, on_progress=None):
        return self.run_full(n_sims, progress_every, on_progress)["team_probs"]

    def run_full(self, n_sims, progress_every=2000, on_progress=None):
        """完整模拟，除各队阶段概率外，还统计淘汰赛每场的参赛/获胜分布。"""
        counts = {team: defaultdict(int) for team in self.t.teams}
        ko_side_a = defaultdict(lambda: defaultdict(int))
        ko_side_b = defaultdict(lambda: defaultdict(int))
        ko_winner = defaultdict(lambda: defaultdict(int))
        stage_idx = {s: i for i, s in enumerate(STAGE_ORDER)}

        for i in range(n_sims):
            reached, ko_record = self.run_once()
            for team, stage in reached.items():
                # 到达某阶段意味着也到达了之前所有阶段
                for s in STAGE_ORDER[: stage_idx[stage] + 1]:
                    counts[team][s] += 1
            for num, (t1, t2, w) in ko_record.items():
                ko_side_a[num][t1] += 1
                ko_side_b[num][t2] += 1
                ko_winner[num][w] += 1
            if progress_every and (i + 1) % progress_every == 0:
                print(f"  已模拟 {i + 1}/{n_sims} 届")
            if on_progress:
                on_progress(i + 1, n_sims)

        def dist(counter, top=5):
            ranked = sorted(counter.items(), key=lambda kv: kv[1], reverse=True)
            return [[team, c / n_sims] for team, c in ranked[:top]]

        return {
            "team_probs": {
                team: {s: c[s] / n_sims for s in STAGE_ORDER}
                for team, c in counts.items()
            },
            "ko_stats": {
                num: {
                    "side_a": dist(ko_side_a[num]),
                    "side_b": dist(ko_side_b[num]),
                    "winner": dist(ko_winner[num]),
                }
                for num in ko_side_a
            },
            "n_sims": n_sims,
        }

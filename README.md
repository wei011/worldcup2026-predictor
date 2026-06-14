# ⚽ WorldCup 2026 Predictor

> 用真实数据预测 2026 美加墨世界杯 —— Elo 评分 × 泊松进球模型 × 蒙特卡洛模拟，自带世界杯主题 Web 界面。
>
> Predict the 2026 FIFA World Cup with real data: Elo ratings, a calibrated Poisson goal model, and Monte-Carlo tournament simulation — zero dependencies, beautiful web UI included.

![Python](https://img.shields.io/badge/python-3.8%2B-blue)
![Dependencies](https://img.shields.io/badge/dependencies-0-brightgreen)
![License](https://img.shields.io/badge/license-MIT-yellow)
![Data](https://img.shields.io/badge/data-100%25%20real%20APIs-orange)
[![Update live scorecard](https://github.com/wei011/worldcup2026-predictor/actions/workflows/update-scorecard.yml/badge.svg)](https://github.com/wei011/worldcup2026-predictor/actions/workflows/update-scorecard.yml)

**为什么值得一试：**

- 🚫 **零第三方依赖** —— 纯 Python 标准库 + 原生 HTML/CSS/JS，`git clone` 完直接跑，没有 `pip install`，没有 node_modules
- 📡 **数据 100% 来自真实公开接口** —— 没有一行手写的比赛数据、没有拍脑袋的实力值，连淘汰赛对阵图都是从 FIFA 官方占位符解析的
- 🔑 **不需要任何 API Key** —— 两个数据源全部免费、无需注册
- 📖 **方法论完全透明** —— 每个模型参数要么来自公开标准（World Football Elo），要么由历史数据拟合得出，README 里全部明示
- 🖥️ **CLI 和 Web 双界面** —— 既能跑批出 CSV，也有一个好看的深色主题预测仪表盘
- 🔬 **会自我检验、持续优化** —— 每天自动用真实赛果给模型打分（Brier score），并据此迭代：已用样本外回测找出"低估平局"的偏差，集成 Dixon-Coles 修正。赢了记 ✅、被爆冷记 ❌，成绩公开可查

---

## 🚀 快速开始

```bash
git clone https://github.com/wei011/worldcup2026-predictor.git
cd worldcup2026-predictor

# Web 界面（推荐）
python3 webapp/server.py --port 8026
# 打开 http://localhost:8026

# 或者命令行
python3 run.py --sims 20000

# 看今天有哪些比赛 + 模型预测 + 开赛至今的战绩单
python3 today.py --scorecard

# 对比"老算法 vs 优化后"：--no-dc 关闭 Dixon-Coles 平局修正
python3 today.py --date 2026-06-13 --no-dc      # 老算法（基线双泊松）
python3 today.py --date 2026-06-13              # 优化后（含平局修正）

# 复现样本外回测，看每种优化到底带来多少提升
python3 analysis/backtest.py
```

就这么多。首次运行会自动下载并缓存数据（约 5 MB，十几秒），之后秒级启动。

CLI 输出示例（2 万届模拟，开赛前夜）：

```
球队                  组     Elo     32强     16强      8强      4强      决赛      夺冠
------------------------------------------------------------------------------
Spain               H    2211  99.8%   79.5%   61.6%   49.6%   35.9%   24.4%
Argentina           J    2189  98.9%   71.7%   57.8%   43.4%   29.9%   18.9%
France              I    2122  96.8%   73.5%   49.8%   32.4%   17.7%    9.6%
England             L    2083  97.8%   67.9%   38.4%   23.1%   12.3%    6.1%
Mexico              A    1976  98.1%   72.3%   43.6%   24.4%   12.1%    5.9%
...
```

<!-- SCORECARD:START -->

## 🔴 实时战绩追踪：看着模型被真实赛果检验

世界杯已经开打。每天由 GitHub Actions 自动拉取 FIFA 官方真实赛果，对比赛前预测，给出模型的“成绩单”——这才是一个预测项目最该接受的考验。

> 🗓️ **数据截至 2026-06-14 (UTC) 自动更新** · 本地随时复现：`python3 today.py --scorecard`

**已结束 8 场　·　方向命中 5/8 (62%)　·　平均 Brier score 0.610**（三分类瞎猜基准 0.667，越低越好）

| 日期 | 对阵 | 赛果 | 模型(胜/平/负) | 命中 |
|---|---|---|---|---|
| 06-11 | 墨西哥 vs 南非 | 2:0 | 85% / 11% / 4% | ✅ |
| 06-12 | 韩国 vs 捷克 | 2:1 | 52% / 27% / 22% | ✅ |
| 06-12 | 加拿大 vs 波黑 | 1:1 | 73% / 18% / 9% | ❌ |
| 06-13 | 美国 vs 巴拉圭 | 4:1 | 49% / 27% / 24% | ✅ |
| 06-13 | 卡塔尔 vs 瑞士 | 1:1 | 7% / 16% / 78% | ❌ |
| 06-13 | 巴西 vs 摩洛哥 | 1:1 | 44% / 28% / 28% | ❌ |
| 06-14 | 海地 vs 苏格兰 | 0:1 | 18% / 25% / 57% | ✅ |
| 06-14 | 澳大利亚 vs 土耳其 | 2:0 | 41% / 29% / 30% | ✅ |

模型不藏着掖着：赢了就赢了，被爆冷也照实记上。整届赛事的 Brier score 会一路累积到 7/19 决赛——评价预测模型的正确方式，不是“猜对几场”，而是**概率校准得准不准**。

<!-- SCORECARD:END -->

## 🖥️ Web 界面功能

| 页面 | 内容 |
|---|---|
| 📊 总览 | 晋级概率排行（32强/16强/8强/4强/决赛/夺冠六档切换）、头号热门、东道主行情、揭幕战预测 |
| 🏟️ 小组赛 | 12 个小组卡片：国旗、Elo、出线率进度条、东道主标识 |
| 📅 赛程预测 | 72 场小组赛逐场胜平负概率条，按日期分组，支持小组筛选 + 球队搜索，含球场城市 |
| 🛤️ 对阵图 | 32 强 → 决赛完整淘汰赛树，每个槽位显示模拟中最常出现的球队及概率 |
| 🧪 模拟实验室 | 在线重跑 2k–50k 届模拟（实时进度条）、模型参数、48 队 Elo 排行 |

点击任意球队弹出详情卡：晋级漏斗 + 小组赛逐场胜率。前端为原生 JS 单页应用，48 队国旗 emoji + 中文名内置。

## 📡 数据来源（全部真实接口，无手写数据）

| 数据 | 来源 | 鉴权 |
|---|---|---|
| 2026 世界杯赛程、分组、淘汰赛对阵图（104 场） | [FIFA 官方 API](https://api.fifa.com/api/v3/calendar/matches?idCompetition=17&idSeason=285023&count=200&language=en) | 无需 |
| 历史国际比赛赛果，1872 至今约 4.9 万场 | [martj42/international_results](https://github.com/martj42/international_results) | 无需 |

代码内置完整性校验：赛程必须恰好 104 场、历史库必须 >40000 行、48 支参赛队必须全部能算出 Elo——任何一条不满足直接报错，绝不带病运行。两数据源仅有的 8 处队名差异（如 `Korea Republic` vs `South Korea`）在 [src/names.py](src/names.py) 中显式映射，且已逐一核对。

数据缓存在 `data/`（24 小时有效），小组赛开打后重启服务/加 `--refresh` 即可让真实赛果进入模型。

## 🧠 方法论

三层管线，每层都可独立替换：

```
历史赛果回放 ──► Elo 评分          （World Football Elo 标准公式）
      │
      └──────► (Elo差, 进球数) 样本 ──► 拟合 λ(d) = exp(a + b·d)   （泊松进球模型）
                                              │
FIFA 官方赛程/对阵图 ────────────────────────► 蒙特卡洛模拟整届赛事 × N
```

**1. Elo 评分**（[src/elo.py](src/elo.py)）：逐场回放 1872 年以来全部赛果。K 值按赛事分级（世界杯 60 / 洲际大赛 50 / 预选赛 40 / 其他 30 / 友谊赛 20），净胜球放大系数（2 球 ×1.5，N≥3 球 ×(11+N)/8），非中立主场 +100。

**2. 进球模型**（[src/model.py](src/model.py)）：把 1998 年以来每场比赛拆成 (Elo 差, 实际进球) 样本（约 5.2 万条），分桶 + 加权最小二乘拟合出 λ(d)。比分服从双泊松 → 净胜球、积分规则全部自然涌现。在此之上叠加 **Dixon-Coles (1997) 低比分修正**：独立双泊松会系统性低估平局（样本外实测预测平局率 20.8% vs 真实 23.1%），用一个参数 ρ 修正 0:0/1:1/0:1/1:0 四种低比分的联合概率，把平局概率调回真实频率。ρ 同样由历史比分极大似然拟合（≈ −0.05，负值=提升平局），**不是手设的**。完整样本外回测见 [analysis/backtest.py](analysis/backtest.py)。

**3. 蒙特卡洛**（[src/simulate.py](src/simulate.py)）：小组排名按 FIFA 规则（积分→净胜球→进球→相互战绩→抽签）；12 个第三名取最好 8 个，槽位分配用随机化回溯满足官方对阵图约束；淘汰赛打平进加时（1/3 强度泊松）再点球（50/50）。

所有模型假设集中明示：

| 假设 | 取值 | 依据 |
|---|---|---|
| 主场优势 | +100 Elo | World Football Elo 标准参数 |
| 东道主 | 美/加/墨全程享主场优势 | 简化假设 |
| 加时进球强度 | 常规时间 1/3 | 30 分钟 / 90 分钟 |
| 点球胜率 | 50/50 | 点球可预测性极低 |
| λ 夹板 | [0.15, 4.0] | 防极端外推 |
| Dixon-Coles ρ | ≈ −0.05（拟合） | 修正双泊松对平局的低估 |

## 🆕 模型迭代日志

这个项目不是发布完就锁死的——它每天被真实赛果检验，并据此持续优化。每一次迭代都遵循同一套研究纪律：**发现偏差 → 定位机理 → 用数据拟合修正 → 样本外回测验证**。

- **每日战绩自动追踪** —— `today.py` + GitHub Actions 每天拉取 FIFA 真实赛果，重算方向命中率与 Brier score，自动刷新本 README 的实时战绩段。
- **样本外回测框架**（[analysis/backtest.py](analysis/backtest.py)）—— 严格按时间切训练/测试集（8112 场样本外），用统一指标（Brier / LogLoss / 分层）对比模型变体，杜绝"挑顺眼的比赛自夸"。
- **Dixon-Coles 平局修正** —— 回测确诊基线双泊松**系统性低估平局**（预测 20.8% vs 真实 23.1%），集成 DC 修正后平局校准回到 22%，在"实际平局""大热门被逼平"等失误场景上 Brier 改善 3–4%。诚实声明：整体提升约 0.1%、命中率仍 ~60%（足球预测天花板）——收益是**更校准**，不是更会猜。用 `today.py --no-dc` 可一键对比优化前后。

## 🔌 JSON API

Web 服务同时是一个本地预测 API：

```
GET  /api/status      启动/模拟进度
GET  /api/meta        球队、分组、104 场赛程（含球场）、模型参数
GET  /api/forecast    各队阶段概率 + 淘汰赛逐场参赛/获胜分布
POST /api/simulate    {"sims": 20000, "seed": 42} 重跑模拟
```

拿它喂你自己的前端、机器人或竞猜小程序都行。

## 📁 项目结构

```
worldcup-predictor/
├── run.py              # CLI 入口：夺冠概率模拟
├── today.py            # 每日比赛预测 + 真实赛果战绩单
├── src/
│   ├── fetch.py        # 数据下载与缓存（真实接口 + 完整性校验）
│   ├── names.py        # 两数据源队名映射（8 条，已核对）
│   ├── elo.py          # Elo 逐场回放
│   ├── model.py        # 泊松进球模型 + Dixon-Coles 平局修正（历史数据拟合）
│   └── simulate.py     # 赛制解析 + 蒙特卡洛
├── analysis/
│   └── backtest.py     # 样本外回测：对比模型变体（Brier/LogLoss/分层）
├── webapp/
│   ├── server.py       # 标准库 http.server + JSON API
│   └── static/         # 原生 HTML/CSS/JS 前端
└── output/             # CLI 预测结果（CSV/JSON）
```

## 🛠️ 改造它

想验证自己的足球理论？几个现成的切入点：

- **换评分系统**：把 `elo.py` 换成你的 Glicko / TrueSkill / xG 模型，只要输出 `{队名: 分数}` 字典
- **换进球模型**：Dixon-Coles 低比分修正已内置（见 `src/model.py` 的 ρ）；下一步可把球队身价、近期 xG 加进 λ
- **校准检验**：用 `output/group_match_probs.csv` 对赛果算 Brier score，和博彩赔率比一比
- **接别的赛事**：`fetch.py` 里换一个 `idCompetition`/`idSeason`，欧洲杯、女足世界杯同理可用

## ⚠️ 局限性

单场足球可预测性天花板很低（顶级模型对胜平负命中率约 55–60%），本项目输出的是**概率分布**而非答案。Elo 不知道伤病和临场状态；国家队跨洲交手稀疏会损耗评分可比性。请勿用于赌博决策。

## 📄 License

[MIT](LICENSE) — 随便用，注明出处即可。觉得有意思的话给个 ⭐，世界杯期间一起看模型被爆冷打脸。

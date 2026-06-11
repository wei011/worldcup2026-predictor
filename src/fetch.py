"""数据获取层：所有数据均来自真实公开接口，本模块不包含任何手写的比赛/球队数据。

数据源：
1. 历史国际比赛赛果（1872 年至今，约 4.9 万场）
   https://raw.githubusercontent.com/martj42/international_results/master/results.csv
   （martj42/international_results 开源数据集，逐场真实赛果）
2. 2026 世界杯官方赛程、分组与淘汰赛对阵图（共 104 场）
   https://api.fifa.com/api/v3/calendar/matches?idCompetition=17&idSeason=285023
   （FIFA 官方数据接口，idSeason=285023 即 FIFA World Cup 2026）

下载结果缓存在 data/ 目录，默认 24 小时内复用缓存。
"""

import json
import os
import time
import urllib.request

DATA_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data"
)

HISTORY_URL = (
    "https://raw.githubusercontent.com/martj42/international_results/master/results.csv"
)
FIFA_FIXTURES_URL = (
    "https://api.fifa.com/api/v3/calendar/matches"
    "?idCompetition=17&idSeason=285023&count=200&language=en"
)

CACHE_MAX_AGE = 24 * 3600


def _download(url, filename, refresh=False):
    dest = os.path.join(DATA_DIR, filename)
    if (
        not refresh
        and os.path.exists(dest)
        and time.time() - os.path.getmtime(dest) < CACHE_MAX_AGE
    ):
        return dest
    print(f"  下载 {url}")
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=120) as resp:
        data = resp.read()
    os.makedirs(DATA_DIR, exist_ok=True)
    tmp = dest + ".tmp"
    with open(tmp, "wb") as f:
        f.write(data)
    os.replace(tmp, dest)
    return dest


def history_csv_path(refresh=False):
    """返回历史赛果 CSV 的本地路径，必要时先下载。"""
    path = _download(HISTORY_URL, "results.csv", refresh)
    with open(path, encoding="utf-8") as f:
        lines = sum(1 for _ in f)
    if lines < 40000:
        raise RuntimeError(f"历史赛果数据异常：仅 {lines} 行，疑似下载不完整")
    return path


def fixtures(refresh=False):
    """返回 FIFA 官方 2026 世界杯全部 104 场比赛的原始 JSON 记录列表。"""
    path = _download(FIFA_FIXTURES_URL, "fifa_wc2026.json", refresh)
    with open(path, encoding="utf-8") as f:
        doc = json.load(f)
    results = doc.get("Results", [])
    if len(results) != 104:
        raise RuntimeError(
            f"FIFA 赛程数据异常：取到 {len(results)} 场，应为 104 场"
        )
    return results

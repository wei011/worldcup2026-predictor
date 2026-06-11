#!/usr/bin/env python3
"""2026 世界杯预测 Web 服务（纯标准库，无第三方依赖）。

用法：
    python3 webapp/server.py [--port 8026]

启动后访问 http://localhost:8026
服务启动时在后台线程完成：下载/读取真实数据 → 计算 Elo → 校准进球模型
→ 跑一轮初始模拟。前端通过 /api/status 轮询进度。

API:
    GET  /api/status     启动/模拟进度
    GET  /api/meta       球队、小组、全部 104 场赛程（含场馆）、模型参数
    GET  /api/forecast   各队阶段概率 + 淘汰赛逐场参赛/获胜分布
    POST /api/simulate   {"sims": 10000, "seed": null} 重跑模拟
"""

import argparse
import json
import os
import sys
import threading
import time
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from src import fetch
from src.elo import compute_ratings, HOME_ADVANTAGE
from src.model import GoalModel
from src.names import normalize
from src.simulate import Tournament, Simulator, HOSTS

STATIC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")

STATE = {
    "ready": False,
    "running": False,
    "phase": "正在启动",
    "progress": 0,
    "total": 0,
    "error": None,
}
DATA = {}  # ratings / model / tournament / meta / forecast
_LOCK = threading.Lock()


def _loc(field):
    return field[0]["Description"] if field else None


def _build_meta(fifa_results, tournament, ratings, model):
    teams = [
        {
            "name": team,
            "group": g,
            "elo": round(ratings[team], 1),
            "host": team in HOSTS,
        }
        for g, members in sorted(tournament.groups.items())
        for team in sorted(members, key=lambda x: -ratings[x])
    ]

    matches = []
    for m in sorted(fifa_results, key=lambda x: x["MatchNumber"]):
        stage = m["StageName"][0]["Description"]
        stadium = m.get("Stadium") or {}
        rec = {
            "num": m["MatchNumber"],
            "stage": stage,
            "date": m.get("Date"),
            "stadium": _loc(stadium.get("Name")),
            "city": _loc(stadium.get("CityName")),
        }
        if stage == "First Stage":
            h = normalize(m["Home"]["TeamName"][0]["Description"])
            a = normalize(m["Away"]["TeamName"][0]["Description"])
            d = (ratings[h] + (HOME_ADVANTAGE if h in HOSTS else 0)
                 - ratings[a] - (HOME_ADVANTAGE if a in HOSTS else 0))
            pw, pd, pl = model.outcome_probs(d)
            rec.update({
                "group": m["GroupName"][0]["Description"].split()[-1],
                "home": h, "away": a,
                "p_home": round(pw, 4), "p_draw": round(pd, 4),
                "p_away": round(pl, 4),
            })
        else:
            rec.update({"ph_a": m.get("PlaceHolderA"), "ph_b": m.get("PlaceHolderB")})
        matches.append(rec)

    return {
        "teams": teams,
        "matches": matches,
        "hosts": sorted(HOSTS),
        "kickoff": min(x["date"] for x in matches if x["date"]),
        "model": {
            "a": round(model.a, 4),
            "b": round(model.b, 6),
            "n_samples": model.n_samples,
        },
        "sources": {
            "fixtures": fetch.FIFA_FIXTURES_URL,
            "history": fetch.HISTORY_URL,
        },
    }


def _run_simulation(sims, seed):
    STATE.update(running=True, phase=f"蒙特卡洛模拟", progress=0, total=sims)
    t0 = time.time()
    sim = Simulator(DATA["tournament"], DATA["ratings"], DATA["model"], seed=seed)

    def on_progress(i, n):
        if i % 200 == 0 or i == n:
            STATE.update(progress=i, total=n)

    full = sim.run_full(sims, progress_every=0, on_progress=on_progress)
    DATA["forecast"] = {
        "n_sims": sims,
        "seed": seed,
        "elapsed": round(time.time() - t0, 1),
        "finished_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "team_probs": full["team_probs"],
        "ko_stats": full["ko_stats"],
    }
    STATE.update(running=False, phase="就绪", progress=0, total=0)


def _bootstrap(initial_sims):
    try:
        STATE["phase"] = "获取真实数据（FIFA 赛程 + 历史赛果）"
        history_path = fetch.history_csv_path()
        fifa_results = fetch.fixtures()

        STATE["phase"] = "回放 4.9 万场历史赛果计算 Elo"
        ratings, samples = compute_ratings(history_path)

        STATE["phase"] = "校准泊松进球模型"
        model = GoalModel(samples)
        tournament = Tournament(fifa_results)

        DATA.update(ratings=ratings, model=model, tournament=tournament)
        DATA["meta"] = _build_meta(fifa_results, tournament, ratings, model)

        _run_simulation(initial_sims, None)
        STATE["ready"] = True
    except Exception as e:  # noqa: BLE001 — 启动失败需呈现给前端
        STATE.update(error=str(e), phase="启动失败")
        raise


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=STATIC_DIR, **kwargs)

    def log_message(self, fmt, *args):
        pass  # 静默访问日志

    def end_headers(self):
        self.send_header("Cache-Control", "no-cache")
        super().end_headers()

    def _json(self, obj, code=200):
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == "/api/status":
            return self._json(STATE)
        if self.path == "/api/meta":
            if "meta" not in DATA:
                return self._json({"error": "尚未就绪"}, 503)
            return self._json(DATA["meta"])
        if self.path == "/api/forecast":
            if "forecast" not in DATA:
                return self._json({"error": "尚未就绪"}, 503)
            return self._json(DATA["forecast"])
        return super().do_GET()

    def do_POST(self):
        if self.path != "/api/simulate":
            return self._json({"error": "not found"}, 404)
        if not STATE["ready"]:
            return self._json({"error": "服务尚未就绪"}, 503)
        if STATE["running"]:
            return self._json({"error": "已有模拟在运行中"}, 409)

        length = int(self.headers.get("Content-Length") or 0)
        try:
            payload = json.loads(self.rfile.read(length) or b"{}")
        except json.JSONDecodeError:
            return self._json({"error": "无效的 JSON"}, 400)

        sims = int(payload.get("sims") or 10000)
        sims = max(500, min(sims, 100000))
        seed = payload.get("seed")
        seed = int(seed) if seed not in (None, "") else None

        with _LOCK:
            if STATE["running"]:
                return self._json({"error": "已有模拟在运行中"}, 409)
            threading.Thread(
                target=_run_simulation, args=(sims, seed), daemon=True
            ).start()
        return self._json({"started": True, "sims": sims, "seed": seed})


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8026)
    ap.add_argument("--initial-sims", type=int, default=10000)
    args = ap.parse_args()

    threading.Thread(target=_bootstrap, args=(args.initial_sims,), daemon=True).start()

    server = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    print(f"⚽ 2026 世界杯预测中心: http://localhost:{args.port}")
    server.serve_forever()


if __name__ == "__main__":
    main()

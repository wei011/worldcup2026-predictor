#!/usr/bin/env python3
"""用真实赛果重新生成 README 里的「实时战绩追踪」板块。

被 .github/workflows/update-scorecard.yml 每天定时调用：
拉取 FIFA 官方最新赛果 → 计算模型战绩单 → 替换 README 中
<!-- SCORECARD:START --> 与 <!-- SCORECARD:END --> 之间的内容。

本地也可手动运行：python3 scripts/update_scorecard.py
"""

import datetime as dt
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from today import DISPLAY, label, load_models, predict, scorecard_stats

README = os.path.join(ROOT, "README.md")
START = "<!-- SCORECARD:START -->"
END = "<!-- SCORECARD:END -->"
MAX_TABLE_ROWS = 10  # README 里只列最近 N 场，完整明细看 today.py


def cn(team):
    return DISPLAY.get(team, (team,))[0]


def build_block(ratings, model, recs, today_str):
    rows, hit, n, brier = scorecard_stats(ratings, model, recs)
    lines = [START, ""]
    lines.append("## 🔴 实时战绩追踪：看着模型被真实赛果检验")
    lines.append("")
    lines.append(
        "世界杯已经开打。每天由 GitHub Actions 自动拉取 FIFA 官方真实赛果，"
        "对比赛前预测，给出模型的“成绩单”——这才是一个预测项目最该接受的考验。"
    )
    lines.append("")
    lines.append(f"> 🗓️ **数据截至 {today_str} (UTC) 自动更新** · "
                 "本地随时复现：`python3 today.py --scorecard`")
    lines.append("")

    if n == 0:
        lines.append("_小组赛尚未产生结果，开赛后此处会自动出现战绩单。_")
    else:
        lines.append(f"**已结束 {n} 场　·　方向命中 {hit}/{n} ({hit/n:.0%})"
                     f"　·　平均 Brier score {brier:.3f}**"
                     "（三分类瞎猜基准 0.667，越低越好）")
        lines.append("")
        lines.append("| 日期 | 对阵 | 赛果 | 模型(胜/平/负) | 命中 |")
        lines.append("|---|---|---|---|---|")
        for r in rows[-MAX_TABLE_ROWS:]:
            vs = f"{cn(r['home'])} vs {cn(r['away'])}"
            mark = "✅" if r["ok"] else "❌"
            lines.append(
                f"| {r['date'][5:]} | {vs} | {r['hs']}:{r['as']} | "
                f"{r['w']:.0%} / {r['dr']:.0%} / {r['l']:.0%} | {mark} |"
            )
        if n > MAX_TABLE_ROWS:
            lines.append("")
            lines.append(f"_（仅显示最近 {MAX_TABLE_ROWS} 场，"
                         "完整明细运行 `python3 today.py --scorecard`）_")
        lines.append("")
        lines.append("模型不藏着掖着：赢了就赢了，被爆冷也照实记上。整届赛事的 "
                     "Brier score 会一路累积到 7/19 决赛——评价预测模型的正确方式，"
                     "不是“猜对几场”，而是**概率校准得准不准**。")

    lines.append("")
    lines.append(END)
    return "\n".join(lines)


def main():
    today_str = dt.date.today().isoformat()
    print(f"拉取真实数据并生成战绩单（{today_str}）...")
    ratings, model, recs = load_models(refresh=True)
    block = build_block(ratings, model, recs, today_str)

    with open(README, encoding="utf-8") as f:
        text = f.read()

    if START not in text or END not in text:
        sys.exit(f"README 中缺少 {START} / {END} 标记，无法定位注入区间。")

    pre = text.split(START)[0]
    post = text.split(END, 1)[1]
    new_text = pre + block + post

    if new_text == text:
        print("战绩单无变化，README 未改动。")
        return
    with open(README, "w", encoding="utf-8") as f:
        f.write(new_text)
    print("README 战绩单已更新。")


if __name__ == "__main__":
    main()

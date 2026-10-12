#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把资料库数据表读回的内容，转成页面 applyGoals/applyLogs 期望的行结构（带类型）。

页面消费的数据来自 window.__SMART_PAGE__.database 返回的行对象（字段值为原生类型），
而命令行读到的是一张表格式的文本。这个脚本负责把文本转回原生类型，
再交给 tools/render_check.js 驱动页面自己的渲染逻辑做回归校验。

用法：
  python3 fetch_rows.py --goals-table <id> --logs-table <id> --notes-table <id> \
      [--skill-dir <资料库 skill 目录>] [--out-dir .cache]

--skill-dir 不传时读取环境变量 CODEBUDDY_SKILL_DIR。
"""

import argparse
import csv
import io
import json
import os
import subprocess
import sys

GOAL_FIELDS = {"目标名": "text", "单位": "text", "总量": "num", "截止日": "date",
               "创建日": "date", "配色": "text", "障碍": "text", "对策": "text",
               "示例": "bool", "目标ID": "text"}
LOG_FIELDS = {"日期": "date", "目标名": "text", "打卡量": "num", "单位": "text",
              "分钟": "num", "补记": "bool", "目标ID": "text", "记录ID": "text"}
NOTE_FIELDS = {"周起始日": "date", "保持": "text", "问题": "text",
               "尝试": "text", "下周预案": "text"}


def fetch_table(skill_dir, db):
    script = os.path.join(skill_dir, "database", "get_database_content.py")
    out = subprocess.run([sys.executable, script, "--database-id", db],
                         capture_output=True, timeout=90)
    if out.returncode != 0:
        raise SystemExit("读取数据表失败：%s\n%s" % (db, out.stderr.decode("utf-8", "replace")))
    payload = json.loads(out.stdout.decode("utf-8"))
    return list(csv.reader(io.StringIO(payload["content"])))


def cast(kind, raw):
    raw = raw if raw is not None else ""
    if kind == "bool":
        return raw.strip().lower() == "true"
    if kind == "num":
        raw = raw.strip()
        return "" if raw == "" else float(raw)
    if kind == "date":
        return raw[:10]
    return raw


def to_rows(skill_dir, db, spec):
    table = fetch_table(skill_dir, db)
    if not table:
        return []
    head, body = table[0], table[1:]
    rows = []
    for line in body:
        if not any(x.strip() for x in line):
            continue
        rows.append({k: cast(spec[k], v) for k, v in zip(head, line) if k in spec})
    return rows


def main():
    ap = argparse.ArgumentParser(description="导出页面行结构（用于渲染回归校验）")
    ap.add_argument("--goals-table", required=True)
    ap.add_argument("--logs-table", required=True)
    ap.add_argument("--notes-table", required=True)
    ap.add_argument("--skill-dir", default=os.environ.get("CODEBUDDY_SKILL_DIR", ""),
                    help="资料库 skill 目录；也可用环境变量 CODEBUDDY_SKILL_DIR")
    ap.add_argument("--out-dir", default=".cache")
    args = ap.parse_args()
    if not args.skill_dir or not os.path.isdir(args.skill_dir):
        raise SystemExit("未找到资料库 skill 目录，请用 --skill-dir 指定（或设置 CODEBUDDY_SKILL_DIR）")

    os.makedirs(args.out_dir, exist_ok=True)
    sets = [("rows_goals.json", args.goals_table, GOAL_FIELDS),
            ("rows_logs.json", args.logs_table, LOG_FIELDS),
            ("rows_notes.json", args.notes_table, NOTE_FIELDS)]
    counts = {}
    for name, db, spec in sets:
        rows = to_rows(args.skill_dir, db, spec)
        with open(os.path.join(args.out_dir, name), "w", encoding="utf-8") as f:
            json.dump(rows, f, ensure_ascii=False)
        counts[name] = len(rows)

    print("已导出: " + ", ".join("%s=%d" % (k, v) for k, v in counts.items()))
    logs = json.load(open(os.path.join(args.out_dir, "rows_logs.json"), encoding="utf-8"))
    if logs:
        print("补记 %d 条 | 未填分钟 %d 条" % (
            sum(1 for r in logs if r.get("补记") is True),
            sum(1 for r in logs if r.get("分钟") == "")))


if __name__ == "__main__":
    main()

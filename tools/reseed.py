#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""一键重置「学习目标管理台」的示例数据：删掉旧示例 → 按今天重新生成 → 写回三张表。

为什么需要它：示例数据为了演示出「昨日漏打卡 / 逾期 / 用掉本周休息日」这些状态，
日期必须相对「生成当天」计算；代价是隔几天状态就失效（不是代码坏了）。本脚本
就是过期后的标准动作，重跑一次即可。

安全性：只删除带示例标记的行，你自己新增的数据不会被碰。

  学习目标      示例 = true，或 目标ID 以 seed- 开头
  每日打卡记录   记录ID 以 lg- 开头，或 目标ID 以 seed- 开头
  每周复盘      示例 = true（本表需要「示例」checkbox 字段；没有就跳过，不猜）

用法：
  python3 tools/reseed.py --goals-table <id> --logs-table <id> --notes-table <id> \
      --skill-dir <资料库 skill 目录> --yes

  --dry-run   只统计将要删除 / 写入的条数，不改动线上数据
  --yes       确认执行删除（不传则只做 dry-run）
  --keep      只写新示例，不删除旧示例（会重复，一般不用）
"""

import argparse
import json
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import gen_seed  # noqa: E402

BATCH = 100


def run(skill_dir, script, body):
    """调资料库 skill 的脚本；失败时把原始输出抛出来，便于定位。"""
    path = os.path.join(skill_dir, "database", script)
    out = subprocess.run([sys.executable, path, "--stdin"],
                         input=json.dumps(body, ensure_ascii=False),
                         capture_output=True, timeout=180,
                         encoding="utf-8", errors="replace")
    text = (out.stdout or "").strip()
    if out.returncode != 0:
        raise SystemExit("%s 调用失败：%s\n%s" % (script, text, out.stderr))
    try:
        res = json.loads(text)
    except json.JSONDecodeError:
        return {"raw": text}
    if isinstance(res, dict) and res.get("error"):
        raise SystemExit("%s 返回错误：%s" % (script, res["error"]))
    return res


def query_all(skill_dir, db):
    """分页拉全量记录（返回带 record_id 的 dict 列表）。"""
    rows, cursor = [], ""
    while True:
        body = {"database_id": db, "page_size": BATCH}
        if cursor:
            body["start_cursor"] = cursor
        res = run(skill_dir, "query_database_record.py", body)
        rows.extend(res.get("results", []))
        if not res.get("has_more") or not res.get("next_cursor"):
            break
        cursor = res["next_cursor"]
    return rows


def is_seed_goal(r):
    return r.get("示例") is True or str(r.get("目标ID", "")).startswith("seed-")


def is_seed_log(r):
    return (str(r.get("记录ID", "")).startswith("lg-")
            or str(r.get("目标ID", "")).startswith("seed-"))


def is_seed_note(r):
    return r.get("示例") is True


def delete(skill_dir, db, ids):
    """按 100 条一批删除；返回已删除条数。"""
    for i in range(0, len(ids), BATCH):
        run(skill_dir, "batch_delete_database_records.py",
            {"database_id": db, "record_ids": ids[i:i + BATCH]})
    return len(ids)


def add(skill_dir, db, records):
    """按 100 条一批写入；返回写入条数（服务端不回条数时按本批长度计）。"""
    done = 0
    for i in range(0, len(records), BATCH):
        chunk = records[i:i + BATCH]
        res = run(skill_dir, "batch_add_database_records.py",
                  {"database_id": db, "records": chunk})
        got = 0
        for key in ("record_ids", "ids", "results", "records"):
            v = res.get(key) if isinstance(res, dict) else None
            if isinstance(v, list) and v:
                got = len(v)
                break
        done += got or len(chunk)
    return done


def main():
    ap = argparse.ArgumentParser(description="重置学习目标管理台的示例数据")
    ap.add_argument("--goals-table", required=True)
    ap.add_argument("--logs-table", required=True)
    ap.add_argument("--notes-table", default="")
    ap.add_argument("--skill-dir", default=os.environ.get("CODEBUDDY_SKILL_DIR", ""))
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--yes", action="store_true")
    ap.add_argument("--keep", action="store_true", help="不删除旧示例，只追加新示例")
    ap.add_argument("--out-dir", default=os.path.join(os.path.dirname(
        os.path.dirname(os.path.abspath(__file__))), ".cache"))
    args = ap.parse_args()

    if not args.skill_dir or not os.path.isdir(args.skill_dir):
        raise SystemExit("未找到资料库 skill 目录，请用 --skill-dir 指定（或设置 CODEBUDDY_SKILL_DIR）")
    if not args.dry_run and not args.yes:
        print("这是破坏性操作（会删除示例行）。确认要执行请加 --yes，或先跑 --dry-run 看影响面。")
        return

    goal_recs, log_recs, note_recs = gen_seed.build_payloads()
    tables = [("学习目标", args.goals_table, goal_recs, is_seed_goal),
              ("每日打卡记录", args.logs_table, log_recs, is_seed_log)]
    if args.notes_table:
        tables.append(("每周复盘", args.notes_table, note_recs, is_seed_note))

    print("今天：%s" % gen_seed.T.isoformat())
    plan = []
    for title, db, new_recs, pred in tables:
        rows = query_all(args.skill_dir, db)
        seed_ids = [r["record_id"] for r in rows if pred(r)]
        keep = len(rows) - len(seed_ids)
        plan.append((title, db, new_recs, seed_ids, keep, len(rows)))
        print("  %-8s 现有 %d 条 → 删示例 %d 条、保留你自己的 %d 条、写入新示例 %d 条" % (
            title, len(rows), len(seed_ids), keep, len(new_recs)))

    if args.dry_run:
        print("\n--dry-run：未改动任何线上数据。确认后加 --yes 执行。")
        return

    for title, db, new_recs, seed_ids, keep, total in plan:
        if seed_ids and not args.keep:
            n = delete(args.skill_dir, db, seed_ids)
            print("  已删除 %s 旧示例 %d 条" % (title, n))
        elif seed_ids:
            print("  %s：--keep 生效，跳过删除（表里会同时存在新旧示例）" % title)
        n = add(args.skill_dir, db, new_recs)
        print("  已写入 %s 新示例 %d 条" % (title, n))

    print("\n复核：")
    for title, db, new_recs, _, _, _ in plan:
        print("  %-8s 现在 %d 条" % (title, len(query_all(args.skill_dir, db))))
    gen_seed.self_check()


if __name__ == "__main__":
    main()

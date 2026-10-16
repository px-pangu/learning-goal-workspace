#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""在自己的资料库里建好「学习目标管理台」需要的三张表，并把 ID 配进页面。

clone 下来的 index.html 里三张表 ID 是占位符，页面此时**离线可用**（数据存本机 localStorage）。
想让数据落到自己的资料库、跨设备同步，就需要这三张表；本脚本一次建齐，字段与
docs/data-schema.md 完全一致（含「示例」标记列），然后可选直接调 configure.py 配进页面。

用法：
  python3 tools/init_tables.py --skill-dir <资料库skill目录> --dry-run   # 只看将要创建什么
  python3 tools/init_tables.py --skill-dir <资料库skill目录>             # 建表，打印三个 ID
  python3 tools/init_tables.py --skill-dir <目录> --configure            # 建表并写进 index.html
  python3 tools/init_tables.py --skill-dir <目录> --prefix "[测试] "     # 表名加前缀，便于区分

注意：资料库目前没有「删除整张表」的接口，建出来的表需要你在资料库里手动删除，
所以先跑 --dry-run 确认表名与字段，再决定是否真的建。
"""

import argparse
import json
import os
import subprocess
import sys

SCHEMAS = [
    ("goals", "学习目标", [
        {"name": "目标名", "config": {"text": ""}},
        {"name": "单位", "config": {"text": ""}},
        {"name": "总量", "config": {"number": {"decimalPlaces": 0, "useSeparate": False}}},
        {"name": "截止日", "config": {"date": "2026-01-01T00:00:00Z"}},
        {"name": "创建日", "config": {"date": "2026-01-01T00:00:00Z"}},
        {"name": "配色", "config": {"text": ""}},
        {"name": "障碍", "config": {"text": ""}},
        {"name": "对策", "config": {"text": ""}},
        {"name": "示例", "config": {"checkbox": False}},
        {"name": "目标ID", "config": {"text": ""}},
    ]),
    ("logs", "每日打卡记录", [
        {"name": "日期", "config": {"date": "2026-01-01T00:00:00Z"}},
        {"name": "目标名", "config": {"text": ""}},
        {"name": "打卡量", "config": {"number": {"decimalPlaces": 0, "useSeparate": False}}},
        {"name": "单位", "config": {"text": ""}},
        {"name": "分钟", "config": {"number": {"decimalPlaces": 0, "useSeparate": False}}},
        {"name": "补记", "config": {"checkbox": False}},
        {"name": "目标ID", "config": {"text": ""}},
        {"name": "记录ID", "config": {"text": ""}},
    ]),
    ("notes", "每周复盘", [
        {"name": "周起始日", "config": {"date": "2026-01-01T00:00:00Z"}},
        {"name": "保持", "config": {"text": ""}},
        {"name": "问题", "config": {"text": ""}},
        {"name": "尝试", "config": {"text": ""}},
        {"name": "下周预案", "config": {"text": ""}},
        {"name": "示例", "config": {"checkbox": False}},
    ]),
]

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def run(skill_dir, script, body):
    """调资料库 skill 的脚本。

    skill 脚本的 stdout 里除了 JSON 还可能混入给用户的提示行（例如
    `KS_USER_REPLY\t数据表「…」已创建…`），所以这里逐行找第一个能解析的 JSON 对象，
    而不是 json.loads 整段输出。
    """
    path = os.path.join(skill_dir, "database", script)
    out = subprocess.run([sys.executable, path, "--stdin"],
                         input=json.dumps(body, ensure_ascii=False),
                         capture_output=True, timeout=180,
                         encoding="utf-8", errors="replace")
    for line in (out.stdout or "").splitlines():
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            res = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(res, dict):
            if res.get("error"):
                raise SystemExit("%s 返回错误：%s" % (script, res["error"]))
            return res
    raise SystemExit("%s 输出里没找到 JSON：\n%s\n%s" % (script, out.stdout, out.stderr))


def main():
    ap = argparse.ArgumentParser(description="一键建好学习目标管理台的三张数据表")
    ap.add_argument("--skill-dir", default=os.environ.get("CODEBUDDY_SKILL_DIR", ""))
    ap.add_argument("--space-id", default="", help="目标空间 id（留空=个人空间）")
    ap.add_argument("--parent-id", default="", help="挂到哪个节点下（留空=空间根目录）")
    ap.add_argument("--prefix", default="", help="表名前缀，例如「[测试] 」")
    ap.add_argument("--only", default="", help="只建指定表，逗号分隔，例如 logs,notes")
    ap.add_argument("--configure", action="store_true", help="建好后把 ID 写进 index.html")
    ap.add_argument("--html", default=os.path.join(ROOT, "index.html"))
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    created = {}
    wanted = {x.strip() for x in args.only.split(",") if x.strip()}
    for key, title, props in SCHEMAS:
        if wanted and key not in wanted:
            continue
        schema = {"title": args.prefix + title, "properties": props}
        if args.space_id:
            schema["space_id"] = args.space_id
        if args.parent_id:
            schema["parent_id"] = args.parent_id
        print("[%s] %s —— %d 列：%s" % (key, schema["title"], len(props),
                                    " / ".join(p["name"] for p in props)))
        if args.dry_run:
            continue
        if not args.skill_dir or not os.path.isdir(args.skill_dir):
            raise SystemExit("未找到资料库 skill 目录，请用 --skill-dir 指定（或设置 CODEBUDDY_SKILL_DIR）")
        res = run(args.skill_dir, "create_database.py", schema)
        db_id = res.get("database_id") or res.get("id")
        if not db_id:
            raise SystemExit("建表返回里没有 database_id：%s" % json.dumps(res, ensure_ascii=False))
        created[key] = db_id
        print("    → %s  database_id = %s" % (schema["title"], db_id))

    if args.dry_run:
        print("\n--dry-run：未创建任何表。确认表名与字段后去掉 --dry-run 再跑。")
        return

    if all(k in created for k in ("goals", "logs", "notes")):
        print("\n下一步（二选一）：")
        print("  A. 写进页面：python3 tools/configure.py --goals %s --logs %s --notes %s" % (
            created["goals"], created["logs"], created["notes"]))
        print("  B. 在页面里填：我的 → 数据表绑定（只存在本机，不改仓库文件）")
        if args.configure:
            subprocess.run([sys.executable, os.path.join(ROOT, "tools", "configure.py"),
                            "--html", args.html,
                            "--goals", created["goals"], "--logs", created["logs"],
                            "--notes", created["notes"]], check=True)
            print("\n已写入 %s，页面现在读写你自己的三张表。" % args.html)


if __name__ == "__main__":
    main()

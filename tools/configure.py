#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把 index.html 的数据表配置换成你自己的三张表。

用法：
    python3 tools/configure.py --goals <id> --logs <id> --notes <id>
    python3 tools/configure.py --goals <id> --logs <id> --notes <id> --out my.html
    python3 tools/configure.py --check                 # 只看当前配置状态

三个 ID 从资料库里打开对应数据表时的链接/节点信息里取。
不改表结构：表字段定义见 docs/data-schema.md，三张表都要按它建好。
"""
import argparse
import io
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_HTML = os.path.join(ROOT, "index.html")

# 一个逻辑表可能对应页面里多个常量：logs 同时是 DB_LOGS 和主表别名 DATABASE_ID
FIELDS = [
    ("goals", ["DB_GOALS"]),
    ("logs", ["DB_LOGS", "DATABASE_ID"]),
    ("notes", ["DB_NOTES"]),
]
PATTERNS = {
    const: re.compile(r"(var\s+" + const + r"\s*=\s*)'[^']*'")
    for _, consts in FIELDS
    for const in consts
}
PLACEHOLDER = re.compile(r"^YOUR_[A-Z]+_TABLE_ID$")


def read_config(html_path):
    src = io.open(html_path, encoding="utf-8").read()
    out = {}
    for key, consts in FIELDS:
        m = PATTERNS[consts[0]].search(src)
        out[key] = m.group(0).split("'")[1] if m else None
    return src, out


def is_id(v):
    return bool(v) and bool(re.match(r"^[A-Za-z0-9_-]{8,64}$", v.strip()))


def main():
    ap = argparse.ArgumentParser(description="配置学习目标管理台的数据表 ID")
    ap.add_argument("--goals", help="学习目标表 ID")
    ap.add_argument("--logs", help="每日打卡记录表 ID")
    ap.add_argument("--notes", help="每周复盘表 ID")
    ap.add_argument("--html", default=DEFAULT_HTML, help="要改的页面文件（默认 index.html）")
    ap.add_argument("--out", help="输出到新文件，不改动原文件")
    ap.add_argument("--check", action="store_true", help="只打印当前配置状态")
    a = ap.parse_args()

    if not os.path.isfile(a.html):
        sys.exit("找不到页面文件: " + a.html)
    src, cur = read_config(a.html)

    if a.check or not (a.goals or a.logs or a.notes):
        print("当前配置（%s）：" % a.html)
        for key, _ in FIELDS:
            v = cur.get(key)
            state = "未配置（占位符）" if (not v or PLACEHOLDER.match(v)) else v
            print("  %-6s %s" % (key, state))
        if not (a.goals or a.logs or a.notes):
            print("\n要配置请传入 --goals / --logs / --notes，详见 --help")
        return

    given = {"goals": a.goals, "logs": a.logs, "notes": a.notes}
    bad = [k for k, v in given.items() if v and not is_id(v)]
    if bad:
        sys.exit("表 ID 格式不对（应为 8-64 位字母数字/下划线/连字符）：" + ", ".join(bad))

    out_src = src
    changed = []
    for key, consts in FIELDS:
        v = given.get(key)
        if not v:
            continue
        for const in consts:
            new_src, n = PATTERNS[const].subn(lambda m: m.group(1) + "'" + v + "'", out_src)
            if n != 1:
                sys.exit("替换 %s 时匹配到 %d 处（应为 1 处），已中止，文件未改动" % (const, n))
            out_src = new_src
        changed.append("%s=%s" % (key, v))

    if not changed:
        sys.exit("没有传入任何表 ID，文件未改动")

    target = a.out or a.html
    io.open(target, "w", encoding="utf-8", newline="").write(out_src)

    print("已写入 %s" % target)
    print("  " + "\n  ".join(changed))

    _, after = read_config(target)
    missing = [k for k, v in after.items() if not v or PLACEHOLDER.match(v)]
    if missing:
        print("\n注意：这几张表仍是占位符，页面对该表只会用本机存储：%s" % ", ".join(missing))
    else:
        print("\n三张表都已配置。把页面导入你的资料库空间并在导入时绑定这三张表即可。")


if __name__ == "__main__":
    main()

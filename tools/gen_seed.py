#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""生成「学习目标管理台」的示例数据载荷（用于写入 WorkBuddy 资料库数据表）。

日期一律按「运行当天」做相对偏移，所以示例覆盖的演示状态可以稳定复现：

  背英语单词       今日已打卡 · 预计完成日「提前」
  读《人类简史》   红卡（已逾期 + 昨天没学）· 近 7 天无记录 → 暂无推算
  Python 入门课    黄卡（昨天用掉本周休息日、连续天数保住）· 拖后

另外刻意放了 2 条补记记录（makeup=true，按真实日期参与连续天数与推算）
和 2 条未填分钟的记录（14 天堆叠柱状图不硬凑）。

用法：
  python3 gen_seed.py --goals-table <学习目标表 id> --logs-table <每日打卡记录表 id> [--out-dir .cache]

输出 <out-dir>/payload_goals.json、<out-dir>/payload_logs.json，
再喂给资料库 skill 的 database/batch_add_database_records.py 写入：

  python3 <skill>/database/batch_add_database_records.py --stdin < .cache/payload_goals.json
  python3 <skill>/database/batch_add_database_records.py --stdin < .cache/payload_logs.json

脚本同时内置了一份与页面 app.js 等价的计算（连续天数 / 休息日 / 预计完成日），
生成后立刻自检并打印每个目标会呈现的卡片状态。
"""

import argparse
import datetime
import json
import math
import os

T = datetime.date.today()


def d(off):
    return (T + datetime.timedelta(days=off)).isoformat()


def P(*pairs):
    """把 (字段名, 值) 转成数据表写入所需的 {类型: 值} 结构。"""
    out = {}
    for name, val in pairs:
        if isinstance(val, bool):
            out[name] = {"checkbox": val}
        elif isinstance(val, (int, float)):
            out[name] = {"number": val}
        elif isinstance(val, tuple) and val[0] == "date":
            out[name] = {"date": val[1]}
        elif isinstance(val, str):
            out[name] = {"text": val}
        else:
            raise ValueError(name)
    return out


# ---------------- 目标 ----------------
GOALS = [
    dict(id="seed-g1", name="背英语单词", unit="个", total=2000,
         deadline=d(+80), created=d(-21), color="#6366f1",
         obstacle="拿起手机", plan="先把单词 App 打开，做完 20 个再决定要不要继续"),
    dict(id="seed-g2", name="读《人类简史》", unit="页", total=440,
         deadline=d(-3), created=d(-21), color="#0ea5e9",
         obstacle="躺到床上", plan="先把书翻开读 5 页，读不下去就合上"),
    dict(id="seed-g3", name="Python 入门课", unit="节", total=60,
         deadline=d(+13), created=d(-14), color="#8b5cf6",
         obstacle="下班回家觉得太累", plan="先只打开编辑器写一行代码"),
]

# ---------------- 打卡记录：(目标, 相对天数, 打卡量, 分钟|None, 是否补记) ----------------
A_PLAN = [(-14, 50, 20, False), (-11, 55, 22, False), (-10, 55, None, False),
          (-9, 60, 25, False), (-8, 55, 25, True), (-7, 60, 20, False),
          (-6, 55, 22, False), (-5, 60, 25, False), (-4, 55, 20, False),
          (-3, 60, 25, False), (-2, 55, 20, False), (-1, 60, 22, False),
          (0, 55, 20, False)]
B_PLAN = [(-16, 25, 30, False), (-15, 30, 35, False), (-13, 28, 30, False),
          (-12, 32, 35, False), (-11, 30, 30, False), (-10, 35, 40, False),
          (-9, 30, 35, False), (-8, 40, 45, False), (-7, 35, 40, False)]
C_PLAN = [(-14, 1, 45, False), (-13, 2, 50, False), (-12, 2, 45, False),
          (-11, 2, 45, False), (-10, 2, 50, False), (-9, 2, 40, True),
          (-8, 2, 45, False), (-7, 2, 45, False), (-6, 2, 50, False),
          (-5, 2, None, False), (-4, 2, 45, False), (-3, 2, 50, False),
          (-2, 2, 45, False)]

LOGS = []
for gi, (gid, plan) in enumerate([("seed-g1", A_PLAN), ("seed-g2", B_PLAN), ("seed-g3", C_PLAN)]):
    for n, (off, amt, mins, mk) in enumerate(plan):
        LOGS.append(dict(goalId=gid, id="lg-%s%02d" % ("abc"[gi], n + 1),
                         off=off, amount=amt, minutes=mins, makeup=mk))

GOAL_BY_ID = {g["id"]: g for g in GOALS}


def build_payloads():
    goal_records = []
    for g in GOALS:
        goal_records.append(P(
            ("目标名", g["name"]), ("单位", g["unit"]), ("总量", g["total"]),
            ("截止日", ("date", g["deadline"])), ("创建日", ("date", g["created"])),
            ("配色", g["color"]), ("障碍", g["obstacle"]), ("对策", g["plan"]),
            ("示例", True), ("目标ID", g["id"]),
        ))

    log_records = []
    for l in LOGS:
        g = GOAL_BY_ID[l["goalId"]]
        props = P(
            ("日期", ("date", d(l["off"]))), ("目标名", g["name"]),
            ("打卡量", l["amount"]), ("单位", g["unit"]),
            ("补记", bool(l["makeup"])), ("目标ID", l["goalId"]), ("记录ID", l["id"]),
        )
        if l["minutes"] is not None:
            props["分钟"] = {"number": l["minutes"]}
        log_records.append(props)
    return goal_records, log_records


# ---------------- 与页面 app.js 等价的计算，用于生成后自检 ----------------
def dt(s):
    return datetime.date.fromisoformat(s)


def monday(s):
    x = dt(s)
    return (x - datetime.timedelta(days=x.weekday())).isoformat()


TODAY = T.isoformat()


def date_set(gid):
    return {d(l["off"]) for l in LOGS if l["goalId"] == gid}


def is_rest_day(gid, day, dates):
    """当天无记录，且所在周周一（不早于创建日）到前一天都没有漏打 → 本周首个漏打日 = 休息日。"""
    g = GOAL_BY_ID[gid]
    start = max(monday(day), g["created"])
    cur = start
    while cur < day:
        if cur not in dates:
            return False
        cur = (dt(cur) + datetime.timedelta(days=1)).isoformat()
    return True


def streak(gid):
    g = GOAL_BY_ID[gid]
    dates = date_set(gid)
    cur = TODAY if TODAY in dates else d(-1)
    s = 0
    while cur >= g["created"]:
        if cur in dates:
            s += 1
            cur = (dt(cur) - datetime.timedelta(days=1)).isoformat()
        elif is_rest_day(gid, cur, dates):
            cur = (dt(cur) - datetime.timedelta(days=1)).isoformat()
        else:
            break
    return s


def done_of(gid):
    return sum(l["amount"] for l in LOGS if l["goalId"] == gid)


def eta_of(gid):
    g = GOAL_BY_ID[gid]
    done = done_of(gid)
    if done >= g["total"]:
        return "已完成", None
    speed = sum(l["amount"] for l in LOGS if l["goalId"] == gid and -6 <= l["off"] <= 0) / 7.0
    if speed <= 0:
        return "暂无推算（近 7 天无记录）", None
    days = math.ceil((g["total"] - done) / speed)
    eta_date = d(days)
    diff = (dt(g["deadline"]) - dt(eta_date)).days
    return "%s" % eta_date, diff


def self_check():
    print("今天:", TODAY, "| 目标", len(GOALS), "个 | 记录", len(LOGS), "条")
    for gid in ["seed-g1", "seed-g2", "seed-g3"]:
        g, gd = GOAL_BY_ID[gid], date_set(gid)
        done, y = done_of(gid), d(-1)
        missed = (done < g["total"]) and (TODAY not in gd) and (g["created"] <= y) and (y not in gd)
        rest = missed and is_rest_day(gid, y, gd)
        eta_date, diff = eta_of(gid)
        eta = eta_date if diff is None else "%s（%s %d 天）" % (
            eta_date, "提前" if diff > 0 else "拖后", abs(diff))
        overdue = (done < g["total"]) and dt(TODAY) > dt(g["deadline"])
        print("  %-14s %s/%s (%d%%)  连续 %d 天  补记 %d 条  未填分钟 %d 条  预计完成日 %s" % (
            g["name"], done, g["total"], round(done / g["total"] * 100), streak(gid),
            sum(1 for l in LOGS if l["goalId"] == gid and l["makeup"]),
            sum(1 for l in LOGS if l["goalId"] == gid and l["minutes"] is None), eta))
        if missed:
            print("      → 今日卡片：%s" % (
                "黄卡（用掉本周休息日，连续天数保住）" if rest else
                "红卡（%s）" % ("已逾期 %d 天，且昨天没学" % (dt(TODAY) - dt(g["deadline"])).days
                                if overdue else "昨天没学 · 已滚入今日")))
        else:
            print("      → 今日卡片：%s" % ("今日已打卡" if TODAY in gd else "待打卡"))


def main():
    ap = argparse.ArgumentParser(description="生成学习目标管理台的示例数据载荷")
    ap.add_argument("--goals-table", required=True, help="「学习目标」数据表 id")
    ap.add_argument("--logs-table", required=True, help="「每日打卡记录」数据表 id")
    ap.add_argument("--out-dir", default=".cache", help="输出目录（默认 .cache）")
    args = ap.parse_args()

    goal_records, log_records = build_payloads()
    os.makedirs(args.out_dir, exist_ok=True)
    for name, db, recs in (("payload_goals.json", args.goals_table, goal_records),
                           ("payload_logs.json", args.logs_table, log_records)):
        path = os.path.join(args.out_dir, name)
        with open(path, "w", encoding="utf-8") as f:
            json.dump({"database_id": db, "records": recs}, f, ensure_ascii=False, indent=1)
        print("已写出", path, "(%d 条记录)" % len(recs))

    print()
    self_check()


if __name__ == "__main__":
    main()

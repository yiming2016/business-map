# -*- coding: utf-8 -*-
"""v2.6.82：给 10 号线「双拥街→平湖→禾花→华南城→木古→上李朗」5 段写描线。

用户原话：「线路描线错乱，在上李朗➡️木古➡️禾花➡️平湖➡️双拥街」。
病根：这 5 段在 lines_doc["traced"] 里**一条都没有**（266 个 key 全无此段）
⇒ 渲染走兜底肘部/直线，把官方走廊的弯切掉（叠加目检：平湖→禾花切角、
华南城→木古切内弯、木古→上李朗平行偏移）。

修法：沿官方点云 A*（trace_assist）走出每段中心线，RDP 用 **4**（定案 2~5，
14/18 会压直缓弧），写进 lines_doc["traced"]（键方向 = 线序方向）。
幂等：重跑覆盖同 key，无害。

★ 跑之前必须：关 exe（退出会写 软件/data）→ 软件/data 同步到 源码/data。
★ dm.save() 写的是 源码/data —— 跑完把 lines.json 拷回 软件/data。
"""
import os
import sys

os.environ["METROEDITOR_TRACE_RDP"] = "4.0"     # ★ 定案 eps=2~5，先于 import
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

SEQ = ["双拥街", "平湖", "禾花", "华南城", "木古", "上李朗"]
LID = "10"


def main() -> None:
    from core.data_manager import get_data_manager
    from ui import trace_assist as TA

    dm = get_data_manager()
    st = dm.all_stations()
    traced = dm.lines_doc.get("traced")
    if not isinstance(traced, dict):
        traced = {}
        dm.lines_doc["traced"] = traced

    for a, b in zip(SEQ, SEQ[1:]):
        key = "%s|%s|%s" % (LID, a, b)
        ra, rb = st.get(a), st.get(b)
        if not ra or not rb:
            print(f"[SKIP] {key}：站点缺失")
            continue
        ax, ay = float(ra["x"]), float(ra["y"])
        bx, by = float(rb["x"]), float(rb["y"])
        # ★ 这几站都贴着走廊（dev≤20px），TRIM_END=45 会把弯全掐掉（每段只剩
        #   2 个点=直线，等于没修）。站贴走廊时"起手回勾"风险很小，掐 12px 够。
        g = TA._graph(LID)
        na = g.nearest(ax, ay, TA.SNAP_MAX)
        nb = g.nearest(bx, by, TA.SNAP_MAX)
        raw = None
        if na is not None and nb is not None:
            ids = g.astar(na[0], nb[0])
            if ids:
                raw = [g.pts[i] for i in ids]
                trim = 12.0
                while len(raw) > 1 and __import__("math").hypot(
                        raw[0][0] - ax, raw[0][1] - ay) < trim:
                    raw.pop(0)
                while len(raw) > 1 and __import__("math").hypot(
                        raw[-1][0] - bx, raw[-1][1] - by) < trim:
                    raw.pop()
        if not raw:
            print(f"[SKIP] {key}：A* 走不通")
            continue
        pts = TA._post(raw, 4.0)
        # 质检：每个点离本线点云的距离（走廊内应 ~0~11px）
        # ★★ deviation() 返回 0.0 是**真值**（就在走廊上）——不能用 `or 999`
        devs = []
        for p in pts:
            _d = TA.deviation(LID, p[0], p[1])
            devs.append(999.0 if _d is None else _d)
        dmax = max(devs)
        davg = sum(devs) / len(devs)
        span = ((bx - ax) ** 2 + (by - ay) ** 2) ** 0.5
        ok = dmax <= 30.0
        traced[key] = [[round(float(p[0]), 1), round(float(p[1]), 1)] for p in pts]
        print(f"[{'OK  ' if ok else 'WARN'}] {key} 点数={len(pts)} 段长={span:.0f}px "
              f"离走廊 avg={davg:.1f} max={dmax:.1f}")

    dm.save()
    print("[DONE] lines_doc['traced'] 已写盘（源码/data）")


if __name__ == "__main__":
    main()

"""
core/schema.py
========================
数据 schema 的内存常量定义（编辑器内使用）。

说明：这份文件的字段顺序会被 UI 用来生成可编辑表单。
如需新增/删除字段：编辑 EDITABLE_FIELDS 即可，主程序无需改动。
"""

from __future__ import annotations
from typing import List, Dict


# ★★ v2.7.0：**界面上不再显示**的字段（用户要求：「右侧弹窗和双击弹窗，删除
#   出入口信息和它的输入框」）。
#   · 只在 UI 层跳过（InfoPanel / EditDialog 的表单构建都不生成控件）；
#   · **数据完整保留**：`_collect()` 因为拿不到控件而不收集这些键 ⇒
#     `upsert_station`（合并写入）不会覆盖它们 ⇒ 旧值原样留在 stations.json；
#   · 将来想恢复显示：把这个集合里对应的 key 删掉即可，其它代码零改动。
#   ★ v2.7.4：`exits` 从这个集合里**移出去了** —— 用户看到"出入口信息看不见了"
#     之后的要求是：「只恢复**能看**」（不给可编辑输入框）。所以它现在走
#     `READONLY_UI_FIELDS`：控件照建、内容照显示，但**不参与回写**。
#     `facilities`（设施）用户没要求回来，继续留在这里隐藏。
HIDDEN_UI_FIELDS = ("facilities",)

# ★★ v2.7.4：**只读展示**的字段 —— 在右侧面板 / 双击弹窗里**照常出现并显示
#   内容**，但底下的输入控件是只读的（能选、能复制，改不了）。
#   · 用户原话：「你搞丢了不同出入口外的信息」⇒「只恢复『能看』」；
#   · ★ 双重保险：除了控件只读，`_collect()` 也**跳过**这些键 ⇒
#     保存时 payload 里根本没有它 ⇒ `upsert_station` 合并写入原值不动。
#     就算是只读控件在拼回时格式有细微差异，也不可能写进数据。
# ★★ v2.7.5：**清空** —— `exits` 改回可编辑（用户：「A、B、C 作为按钮，
#   点击后可以输入进行编辑，详细信息也应该为输入框」）。
#   常量保留成空元组，是为了不动 `_collect()` / `ExitsEditor` 的调用点。
READONLY_UI_FIELDS = ()


# 编辑器内可编辑的字段（顺序就是 UI 上从上到下的顺序）
# 2026-09-18 调整：`description`（简介）挪到 `station_name` 正下方，
# 这样弹窗里"站点名称 → 简介"紧挨着，一眼就能顺手写一句。
#
# 可选键：
#   `same_row: True`  —— 声明"输入框只有**一行**高"（用 QLineEdit 而不是 QPlainTextEdit）。
#    2026-09-24（v2.6.4）给 `facilities` 用：设施内容就是顿号隔开的一串名词
#    （实测 379 站**全部是单行、最长 18 字**），给一个多行大框纯属浪费地方。
#    形态： `设施    卫生间、电梯、母婴室`
#   `head_with: "<另一个字段的 key>"` —— v2.6.8：**本字段不自己占一行**，
#    而是把输入框挂到目标字段那一行的**标题右侧**（并且不再显示自己的标签文字）。
#    用户要求：「『设施』的内容放到文字『出入口信息』的右侧，删除文字『设施』」。
#    实现见 `ui/form_rows.py::inject_head`。
#
# ★ v2.6.8 用户指定了可见字段的上下顺序：
#     出入口信息 → 周边地标 → 备注 → 首末班车 → 公交换乘
#   （`facilities` 因为挂进了「出入口信息」那一行，自己不再占一行）
EDITABLE_FIELDS: List[Dict] = [
    {
        "key": "station_name",
        "label": "站点名称",
        "type": "text",
        "required": True,
        "placeholder": "例如：购物公园",
    },
    {
        "key": "description",
        "label": "简介",
        "type": "multiline",
        "required": False,
        "placeholder": "地理位置、命名由来等…",
    },
    {
        "key": "lines",
        "label": "所属线路",
        "type": "lines",  # 多选线路（UI 上是可折叠下拉）
        "required": True,
        "placeholder": "",
    },
    # ★ v2.6.6：`is_transfer`（是否换乘站）与 `open_date`（开通日期）**已从表单移除**。
    #   用户原话：「删除文字'是否换乘站''开通日期'和对应的勾选框
    #             （因为上方的下拉菜单可以选择是否为换乘站）」。
    #   · `is_transfer` 改为**由所属线路推导**（`derive_is_transfer()`）——
    #     验过：379 站里 `is_transfer` 与 `len(lines) > 1` **100% 一致**，
    #     所以推导不会改变任何一条数据。
    #   · `open_date` 实测 379 站**全是空串**，从来没人填过 → 去掉输入框零损失。
    #   ★ 两个 key 仍保留在数据里（`upsert_station` 是**合并**写入，
    #     payload 里不带 = 保持原值，不会被清空）。
    {
        # v2.6.69：图标标签（多组）。每组 = 图标 + 手动文字 + 图标相对文字的
        #   位置（left/top/right/bottom，弹窗里 ⚙️ 菜单设置）。
        #   存 `tags` 列表：[{"icon": "hsr|airport|mall_*", "text": str, "pos": str}]。
        #   地图渲染在站名前面（见 metro_render.HaloLabel.set_tags）。
        #   InfoPanel 不认 "tags" 类型会自动跳过（编辑只在弹窗里做）。
        "key": "tags",
        "label": "图标标签",
        "type": "tags",
        "required": False,
    },
    {
        # v2.6.67：所属行政区（下拉 9 区 + 不设置）。
        "key": "district",
        "label": "所属区",
        "type": "choice",
        "required": False,
        "options": [
            ("", "不设置"),
            ("福田区", "福田区"),
            ("罗湖区", "罗湖区"),
            ("南山区", "南山区"),
            ("盐田区", "盐田区"),
            ("宝安区", "宝安区"),
            ("龙岗区", "龙岗区"),
            ("龙华区", "龙华区"),
            ("坪山区", "坪山区"),
            ("光明区", "光明区"),
        ],
    },
    {
        "key": "exits",
        "label": "出入口信息",
        "type": "multiline",
        "required": False,
        "placeholder": "A 出口：…；B 出口：…",
        # ★ v2.7.5：**不再显示「出入口信息」这五个字**（用户原话「删除文字
        #   '出入口信息'」）。下面直接就是 A/B/C… 按钮 + 详细信息输入框，
        #   没有标题也一眼看得懂。`no_label` 由 UI 层读（form_rows.make_stacked）。
        #   ★ label 本身保留 —— 日志/提示里还可能引用它，只是不画出来。
        "no_label": True,
    },
    {
        # v2.6.8：`facilities` 不再自己占一行 —— 输入框挂到**「出入口信息」
        # 那一行的标题右侧**，`设施` 两个字删掉（用户要求）。
        # ★ 它必须**紧跟在 `exits` 后面**：一是读起来顺，二是 `head_with`
        #   的目标字段在它之前出现，读代码时不用回头找。
        "key": "facilities",
        "label": "设施",
        "type": "multiline",
        "required": False,
        "placeholder": "卫生间、电梯、母婴室…",
        # v2.6.4：内容就是顿号隔开的一串名词（379 站**全是单行、最长 18 字**），
        #   给多行大框纯属浪费地方 ⇒ 仍然是单行 QLineEdit。
        "same_row": True,
        # v2.6.8：挂到 `exits` 那行的标题右侧（见 `ui/form_rows.py::inject_head`）。
        "head_with": "exits",
    },
    {
        "key": "landmarks",
        "label": "周边地标",
        "type": "multiline",
        "required": False,
        "placeholder": "",
    },
    {
        "key": "notes",
        "label": "备注",
        "type": "multiline",
        "required": False,
        "placeholder": "其他任意备注…",
    },
    {
        # v2.6.2 新增：首末班车（数据源＝深圳地铁官网 szmc.net/zdxx）
        # v2.6.8：按用户指定的顺序排在「备注」之后。
        "key": "timetable",
        "label": "首末班车",
        "type": "multiline",
        "required": False,
        "placeholder": "例：工作日 · 1号线：往机场东 首06:41 末23:21；往罗湖 首06:02 末23:47",
    },
    {
        # v2.6.2 新增：公交换乘（同一数据源）
        # v2.6.8：排到最后一位。
        "key": "bus_transfer",
        "label": "公交换乘",
        "type": "multiline",
        "required": False,
        "placeholder": "例：B出入口 · 火车站：1、12、17、82、306",
    },
]


def derive_is_transfer(payload: Dict) -> Dict:
    """由「所属线路」推导 `is_transfer`（v2.6.6）。

    背景：表单里的「是否换乘站」勾选框已删（用户要求 —— 上方的线路下拉
    本身就能表达"这站属于几条线"）。但 `is_transfer` 这个**数据字段还在用**：
    `metro_render` 靠它决定站点圆点画多大、站名要不要加粗。

    ★ 必须在 `_collect()` 之后补上这个键：`EDITABLE_FIELDS` 里已经没有它，
      不补的话 payload 不带 `is_transfer`，保存后它的值会一直是打开弹窗那一刻的
      旧值 —— 用户把线路从 1 条改成 2 条，圆点却还是普通大小。
    ★ 判据「线路数 > 1」是拿全量数据验过的：379 站的 `is_transfer`
      与 `len(lines) > 1` **完全一致**（不一致数 = 0），所以推导不改动任何现存数据。

    就地修改并返回 `payload`（方便链式调用）。
    """
    lines = payload.get("lines")
    if isinstance(lines, (list, tuple)):
        payload["is_transfer"] = len(lines) > 1
    return payload


# 默认新站点的初始字段
def new_station_template() -> Dict:
    return {
        "station_name": "新站点",
        "lines": [],
        "is_transfer": False,
        "tags": [],            # v2.6.69：图标标签 [{"icon","text","pos"}]
        "open_date": "",
        "description": "",
        "exits": "",
        "timetable": "",       # v2.6.2：首末班车
        "bus_transfer": "",    # v2.6.2：公交换乘
        "facilities": "",
        "landmarks": "",
        "notes": "",
        "x": 0,
        "y": 0,
        "custom": {},
    }

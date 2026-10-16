"""
ui/form_rows.py
==============================
表单"行"的两种通用形态（v2.6.8 从 edit_dialog / info_panel 里抽出来共用）。

① `make_stacked()`   —— 标签在上、输入框在下、整行宽
② `make_inline_row()`—— 文字在左、输入框占满右边（单行）

★ 为什么抽出来：这两个函数原先在 `edit_dialog.py` 和 `info_panel.py` 里**各写一份**。
  项目铁律（MEMORY §4.16）—— **同一处改动只留一份代码**：
  两份 = 同一个 bug 修两遍，而且极容易只修一处（另一处继续错）。

★ v2.6.8 新增 `head_widget`：把另一个字段的输入框塞进**这一行的标题右侧**。
  用户要求「设施的内容放到文字『出入口信息』的右侧、删掉『设施』两个字」——
  于是 `make_stacked("出入口信息", exits_editor, head_widget=facilities_edit)`。
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QSizePolicy,
)


def make_stacked(label_text, editor: QWidget = None,
                 head_widget: QWidget = None, gap: int = 10) -> QWidget:
    """「标签在上、输入框在下」的整行块。

    :param label_text: 字符串，或者**直接给一个控件**（v2.6.7 起：首末班车曾把
                       日期类型下拉放在这个位置）。
    :param editor:     下面的输入框（None ⇒ 只有标题行）。
    :param head_widget:★ v2.6.8：塞在**标题右侧**的挂件（设施的输入框）。
                       没有的话用 stretch 顶住，标题仍然靠左。
    """
    box = QWidget()
    v = QVBoxLayout(box)
    v.setContentsMargins(0, 0, 0, 0)
    v.setSpacing(3)

    # ★ v2.7.5：**既没有标题文字也没有 head_widget 时，整个标题行都不建**。
    #   「出入口信息」的标题被用户要求删掉，若还留一个空 HBoxLayout，
    #   竖直布局会多出一段 spacing（3px + 空行的边距），看着像凭空空了一截。
    #   ★ 有 head_widget 就必须建（它是 inject_head 的插入锚）。
    if label_text is None and head_widget is None:
        if editor is not None:
            v.addWidget(editor)
        return box

    top = QHBoxLayout()
    top.setContentsMargins(0, 0, 0, 0)
    top.setSpacing(gap)
    if label_text is None:
        pass
    elif isinstance(label_text, QWidget):
        top.addWidget(label_text, 0, Qt.AlignVCenter)
    else:
        top.addWidget(QLabel(label_text), 0, Qt.AlignVCenter)

    if head_widget is not None:
        top.addWidget(head_widget, 1, Qt.AlignVCenter)
    else:
        # ★ 这个 stretch 必须留：它是"标题只占自己宽度"的保证，
        #   也是后面 `inject_head()` 找插入点用的锚。
        top.addStretch(1)

    v.addLayout(top)
    if editor is not None:
        v.addWidget(editor)
    return box


def inject_head(box: QWidget, widget: QWidget) -> bool:
    """把一个控件塞进 `make_stacked()` 造出来的**标题行右侧**（在 stretch 之前）。

    返回 False = 没塞进去（调用方要退回"让它自己占一行"，绝不能让字段凭空消失）。
    """
    if box is None or widget is None:
        return False
    lay = box.layout()
    if lay is None or lay.count() == 0:
        return False
    it = lay.itemAt(0)
    h = it.layout() if it is not None else None
    if h is None:
        return False
    idx = h.count()
    for i in range(h.count()):
        sub = h.itemAt(i)
        if sub is not None and sub.spacerItem():
            idx = i
            break
    h.insertWidget(idx, widget, 1, Qt.AlignVCenter)
    return True


def make_inline_row(label_text: str, editor: QWidget, label_w: int = 56) -> QWidget:
    """「文字在左、输入框占满右边」的**单行**行。

        ★ 标签必须给**固定宽度**，不然各字段标签宽度不一样，
          所有输入框的左边缘就参差不齐（一列内容看着是歪的）。
    """
    box = QWidget()
    h = QHBoxLayout(box)
    h.setContentsMargins(0, 0, 0, 0)
    h.setSpacing(10)
    lbl = QLabel(label_text)
    lbl.setMinimumWidth(label_w)
    lbl.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Preferred)
    h.addWidget(lbl, 0, Qt.AlignVCenter)
    h.addWidget(editor, 1, Qt.AlignVCenter)
    return box

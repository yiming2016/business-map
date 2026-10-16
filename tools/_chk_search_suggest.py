# -*- coding: utf-8 -*-
"""
回归检查：搜索框「边打字边出候选、点击直接选站」（v2.5.0 做，v2.5.1 修的抢按键 bug）

这个功能有四件事必须验，缺一件就等于没做：
  A 结构    —— 面板是不是 Qt.Popup、初始是不是藏着的
  B 边打边筛 —— 每敲一个字，下面候选跟着变，位置贴在搜索框正下方
  C 点选/键盘 —— 点一行能真的选站；↑↓EnterEsc 能不能用
  D 边界    —— 无匹配 / 结果过多 / 清空 / 不出屏 / 窗口动过之后不残留
  G 窗口级按键 —— ★ 弹层的按键必须真的能落回搜索框（v2.5.0 就是这里漏的）
  F 性能    —— 逐键筛选耗时（本项目出过"打字未响应"，逐键动作必须有数据）

★★ 这个文件自己犯过的两个错，引以为戒：
  1) v2.5.0 当时用 `QTest.keyClick(搜索框, ...)` 验键盘 —— 那是把事件**直接塞给控件**，
     绕过了 Qt 的按键分发。而 Qt.Popup 一弹出，Qt 会把按键**重定向给弹层**，
     搜索框一个字都收不到（用户原话："每次输入完成后怎么就取消输入了"）。
     要测这个，必须 `QTest.keyClick(窗口, ...)` 走窗口级分发。 → 见 G 段
  2) A 段原来有一条"面板不抢键盘焦点"直接写 `True` 蒙过去的假断言，
     正是因为它是假的，上面那个 bug 才混过了 v2.5.0。假断言比没有断言更坏。

★ 计时方法上的坑（本文件第一版就踩了，记下来免得再犯）：
  一开始把"敲一个字 + pump(6)"整段计时，测出 96~100ms，看着像功能很卡。
  但实际上：前面测试做的 resize / 定位在事件队列里留了地图补渲染，
  全被算进了计时。单独量才发现：筛选 0.08ms、填面板 0.4ms、弹出 0.3ms；
  而且**把面板关着敲字同样是 6~7ms** —— 那 6~7ms 是输入框自己的，与本功能无关。
  所以这里改成：先排空积压事件，再分开量「功能自身的处理耗时」与「整条链路」，
  并给出「面板关着敲字」作对照。

运行：
    C:\\Users\\29773\\.workbuddy\\binaries\\python\\envs\\default\\Scripts\\python.exe tools/_chk_search_suggest.py
"""
from __future__ import annotations

import ctypes
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from PySide6.QtCore import Qt, QPoint
from PySide6.QtGui import QInputMethodEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QWidget

from ui.main_window import MainWindow
from ui.widgets import SUGGEST_MAX_ROWS

# 系统输入法认的是 Win32 的"键盘焦点窗口"，跟 Qt 的焦点是两套东西，要单独看
_user32 = ctypes.windll.user32

PASS = 0
FAIL = 0
FAILED = []


def check(name: str, cond: bool, extra: str = "") -> None:
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  [OK]   {name}" + (f"   （{extra}）" if extra else ""))
    else:
        FAIL += 1
        FAILED.append(name)
        print(f"  [FAIL] {name}" + (f"   （{extra}）" if extra else ""))


def pump(n: int = 6) -> None:
    for _ in range(n):
        QApplication.processEvents()


def drain() -> None:
    """排空事件队列：把前面测试留下的补渲染/动画先跑完，别算进计时。"""
    for _ in range(80):
        QApplication.processEvents()
    time.sleep(0.25)
    for _ in range(20):
        QApplication.processEvents()


def ms(fn, n: int = 1) -> float:
    t0 = time.perf_counter()
    for _ in range(n):
        fn()
    return (time.perf_counter() - t0) * 1000.0 / n


def type_text(widget, text: str) -> None:
    """模拟输入法**提交**一个字符串。

    ★ 坑（v2.4.19 踩过）：QInputMethodEvent("汉字", []) 只是"预编辑"，不算输入；
      真正落字必须 setCommitString()。
    ★ 另一个坑：QTest.keyClicks(w, "中文") 会让 PySide6 6.11 直接崩进程。
    """
    ev = QInputMethodEvent()
    ev.setCommitString(text)
    QApplication.sendEvent(widget, ev)
    pump()


def main() -> int:
    app = QApplication(sys.argv)
    win = MainWindow()
    # ★ v2.7.1：搜索框搬进了左侧图例（splitter 里）——不给尺寸的话窗口默认很小，
    #   三栏被压，搜索框的全局坐标会算出负数（实测 -720），"贴在正下方"判据假失败。
    win.resize(1480, 900)
    win.show()
    win.activateWindow()
    pump(10)
    win.search_box.setFocus()
    pump()

    pop = win.search_popup
    box = win.search_box
    hint = win.lbl_hint

    def feed(text: str) -> None:
        """清空后用输入法提交一条查询（模拟"从头打一句话"）。"""
        box.clear()
        pump(2)
        type_text(box, text)

    print("\n===== A 结构 =====")
    check("候选面板是 Qt.Popup 顶层窗口",
          bool(pop.windowFlags() & Qt.Popup), f"flags={int(pop.windowFlags())}")
    check("启动时面板是藏着的", not pop.isVisible())
    check("面板对象名/宽度按设计",
          pop.objectName() == "SearchSuggest", f"w={pop.width()}")
    check("MapView.focus_station_by_name 仍在（旧接口没被删）",
          hasattr(win.map_view, "focus_station_by_name"))
    # ★★ 这里以前写的是"面板不抢键盘焦点"，还直接 `True` 蒙过去 —— v2.5.0 就是
    #   被这条假断言骗过去的。真相：Qt.Popup 弹出后，Qt 会把**按键**重定向给它
    #   （QApplication::notify 的弹层规则），搜索框一个字都收不到。
    #   所以"能不能接着打字"必须靠"面板把按键转发回去"，真正的判据在 G 段。
    check("★ 面板必须把按键转发回搜索框（结构）",
          pop.key_target() is box,
          "转发目标=" + (type(pop.key_target()).__name__ if pop.key_target() else "None"))

    print("\n===== B 边打字边筛 =====")
    feed("机场")
    check("输入「机场」后面板自动出现", pop.isVisible())
    rows = pop.visible_rows()
    check("候选行数 > 0", len(rows) > 0, f"{len(rows)} 行")
    check("第一行以「机场」开头", rows[0].text().startswith("机场"),
          f"第一行={rows[0].text()!r}")

    box_bottom = box.mapToGlobal(QPoint(0, box.height())).y()
    box_left = box.mapToGlobal(QPoint(0, 0)).x()
    check("面板贴在搜索框正下方（±8px）",
          abs(pop.y() - (box_bottom + 3)) <= 8,
          f"面板top={pop.y()} 搜索框bottom={box_bottom}")
    check("面板与搜索框水平方向有重叠（居中在搜索框下方）",
          pop.x() < box_left + box.width() and pop.x() + pop.width() > box_left,
          f"面板x={pop.x()} 搜索框x={box_left}")

    n1 = len(rows)
    check("候选行数 == 数据侧筛选结果数（不多不少）",
          n1 == min(len(win._search_candidates("机场")), SUGGEST_MAX_ROWS),
          f"面板{n1} 行")

    type_text(box, "东")
    check("再敲一个字（不重新清空）→ 候选实时收窄",
          len(pop.visible_rows()) <= n1,
          f"{n1} 行 → {len(pop.visible_rows())} 行")
    check("此时搜索框内容是「机场东」", box.text() == "机场东", box.text())
    check("「机场东」是候选第一行",
          pop.visible_rows()[0].text() == "机场东",
          pop.visible_rows()[0].text())
    check("候选行右侧显示了所属线路（灰色小字）",
          pop.visible_rows()[0].info_text() != "",
          pop.visible_rows()[0].info_text())

    print("\n===== C 点选 =====")
    target = pop.visible_rows()[0].text()
    r0 = pop.visible_rows()[0]
    QTest.mouseClick(r0, Qt.LeftButton, pos=r0.rect().center())
    pump(6)
    check("点候选行后面板自动收起", not pop.isVisible())
    check("搜索框回填了站名", box.text() == target, box.text())
    check("地图焦点站 == 点的那个站",
          win.map_view._focus_station_id == target,
          f"focus={win.map_view._focus_station_id!r}")
    check("右侧信息面板切到了该站",
          win.info_panel._current_station_id == target,
          f"panel={win.info_panel._current_station_id!r}")
    check("底部提示显示已定位", "已定位" in hint.text(), hint.text())
    check("选完不会又弹一次面板", not pop.isVisible())

    print("\n===== D 键盘 =====")
    feed("")
    check("清空文本 → 面板收起", not pop.isVisible())
    feed("园")
    check("重新输入 → 面板又出来", pop.isVisible())
    check("刚出来时没有高亮项", pop.active_index() == -1, f"active={pop.active_index()}")

    QTest.keyClick(box, Qt.Key_Down)
    pump()
    check("↓ → 高亮第 1 行", pop.active_index() == 0, f"active={pop.active_index()}")
    check("被高亮的那一行确实进入了高亮态", pop.visible_rows()[0].is_active())
    QTest.keyClick(box, Qt.Key_Down)
    pump()
    check("↓↓ → 高亮第 2 行", pop.active_index() == 1, f"active={pop.active_index()}")
    QTest.keyClick(box, Qt.Key_Up)
    QTest.keyClick(box, Qt.Key_Up)
    pump()
    check("↑↑ 回到第 1 行且不越界（不会变成 -1）",
          pop.active_index() == 0, f"active={pop.active_index()}")
    QTest.keyClick(box, Qt.Key_Up)
    pump()
    check("第 1 行再 ↑ 仍停在第 1 行", pop.active_index() == 0,
          f"active={pop.active_index()}")

    by_down = pop.visible_rows()[pop.active_index()].text()
    QTest.keyClick(box, Qt.Key_Return)
    pump(6)
    check("Enter → 选中高亮项并收起面板", not pop.isVisible())
    check("  Enter 选中的正是高亮那一行",
          win.map_view._focus_station_id == by_down,
          f"期望={by_down!r} 实际={win.map_view._focus_station_id!r}")

    feed("园")
    check("再次输入面板又出来", pop.isVisible())
    QTest.keyClick(box, Qt.Key_Escape)
    pump(6)
    check("Esc → 只关面板", not pop.isVisible())
    check("  Esc 不会顺手退出全屏", not win.isFullScreen())

    feed("园")
    QTest.keyClick(box, Qt.Key_Return)
    pump(6)
    first = win._search_candidates("园")[0]
    check("无高亮时 Enter → 定位第一个匹配项（旧行为没丢）",
          win.map_view._focus_station_id == first,
          f"focus={win.map_view._focus_station_id!r}")

    print("\n===== E 边界 =====")
    feed("zzz")
    check("查无此站 → 面板给出提示而不是空白",
          pop.isVisible() and pop.note_visible() and pop.note_text() == "无匹配站点",
          f"note={pop.note_text()!r}")
    check("  无匹配时没有候选行", len(pop.visible_rows()) == 0)

    feed("")
    check("清空后彻底收起（不留提示行）", not pop.isVisible())

    # 卡片高度必须按内容塌下来
    # ★ 这条是补的：一开始用 adjustSize() 定尺寸，实测 2 行时算出 78 却停在 100、
    #   0 行时算出 37 也停在 100 —— 大白卡片里只有一行字，很难看。
    pop.set_items([(f"站{i}", f"站{i}", "1") for i in range(2)], 2)
    pump()
    check("2 行候选时卡片高度 = 内容高度（76px）", pop.height() == 76,
          f"h={pop.height()}")
    pop.set_items([], 0)
    pump()
    check("0 行（无匹配）时卡片只有提示行那么高（<45px）", pop.height() < 45,
          f"h={pop.height()}")
    check("  0 行时滚动区被藏起来（不占高度）", not pop.area_visible())
    pop.set_items([(f"站{i}", f"站{i}", "1") for i in range(24)], 24)
    pump()
    check("24 行时候只长到 8 行高（不出屏）", pop.height() == 6 + 8 * 31 + 2 + 6,
          f"h={pop.height()}")
    check("  又能看到滚动区了", pop.area_visible())
    pop.hide()

    pop.set_items([(f"站{i}", f"站{i}", "1") for i in range(SUGGEST_MAX_ROWS)],
                  SUGGEST_MAX_ROWS + 80)
    pump()
    check("结果超上限时只建到上限行数",
          len(pop.rows()) == SUGGEST_MAX_ROWS,
          f"{len(pop.rows())} / 上限 {SUGGEST_MAX_ROWS}")
    check("  截断时给出「共 N 条」提示",
          pop.note_visible() and "共" in pop.note_text(), pop.note_text())
    pop.hide()

    feed("园")
    rows = pop.visible_rows()
    check("单字「园」列出全部 24 条（没有被上限砍掉）",
          len(rows) == len(win._search_candidates("园")), f"{len(rows)} 行")
    check("  超出可见行数时出现滚动条（能滚）",
          pop.area().verticalScrollBar().maximum() > 0,
          f"max={pop.area().verticalScrollBar().maximum()}")
    check("  面板高度没有随结果数无限变高",
          pop.height() < 8 * 32 + 90, f"h={pop.height()}")

    # 不出屏：把窗口挪到屏幕右下角，用"24 条"这种高面板来试
    screen = QApplication.primaryScreen().availableGeometry()
    win.move(screen.right() - win.width() - 10, screen.bottom() - win.height() - 10)
    pump(8)
    feed("园")
    if pop.isVisible():
        inside = (screen.left() <= pop.x() and pop.x() + pop.width() <= screen.right() + 1
                  and screen.top() <= pop.y() and pop.y() + pop.height() <= screen.bottom() + 1)
        check("窗口贴屏幕右下角时，面板仍完整在屏幕内", inside,
              f"面板=({pop.x()},{pop.y()},{pop.width()}x{pop.height()}) 行数={len(pop.visible_rows())}")
    else:
        check("窗口贴屏幕右下角时，面板仍完整在屏幕内", False, "面板没显示出来")

    # 下面放不下时必须翻到上方（工具栏在顶部平时碰不到，这里拿一个贴底的控件试）
    probe_bottom = QWidget()
    probe_bottom.setGeometry(screen.left() + 300, screen.bottom() - 30, 160, 24)
    probe_bottom.show()
    pump(4)
    feed("园")
    pop.show_at(probe_bottom)
    pump(4)
    check("下方放不下时面板翻到上方（不会掉到屏幕外）",
          pop.y() + pop.height() <= screen.bottom() + 1 and pop.y() >= screen.top(),
          f"面板y={pop.y()} h={pop.height()} 屏幕bottom={screen.bottom()}")
    probe_bottom.close()

    feed("园")
    win.resize(win.width() - 40, win.height())
    pump(8)
    check("主窗口改变尺寸后面板自动收起", not pop.isVisible())
    win.resize(1480, 900)
    pump(6)

    print("\n===== G 窗口级按键（走真实分发路径；v2.5.1 修的 bug 就在这里）=====")
    # ★★ 方法学（血泪）：这一段必须用 QTest.keyClick(**窗口**, ...) 而不是 QTest.keyClick(控件, ...)。
    #    · 发到"控件" = 把事件直接塞给那个控件，**绕过 Qt 的按键分发**
    #      → 弹层把按键吃掉这种问题**测不出来**（v2.5.0 就是这样漏掉的）
    #    · 发到"窗口" = 走 QWindowSystemInterface → QWidgetWindow → 再分发
    #      → 和真实按键进来后的路径一致，才测得出
    win_h = win.windowHandle()

    def wkey(key_enum):
        """发一个窗口级按键（等同真实按键的分发路径）。"""
        QTest.keyClick(win_h, key_enum)
        pump(6)

    def brief(w):
        return "None" if w is None else type(w).__name__

    def win32_focus():
        """Win32 的键盘焦点窗口句柄（系统输入法认的是这个）。"""
        return int(_user32.GetFocus())

    def focus_box():
        """★ 把焦点还给搜索框，而且要**先收面板 + 让主窗口重新成为活动窗口**。

        三个坑（都踩过）：
          1) 窗口级按键只会送到"当前焦点控件"，而前面几段跑完时焦点已经在地图上
             （_locate_station 会把焦点交给地图）。不还焦点，按键会被地图吃掉。
          2) 面板开着的时候对别的控件 setFocus，Qt 会按"弹层不许焦点外流"的规则
             把焦点改收进弹层内部 —— 而面板里所有子控件都是 NoFocus，
             结果 `focusWidget()` 变成 None，后面全误判。
             真实用法不会这样：用户点搜索框时，弹层会先被点外面关掉。
             所以这里先 hide() 再 setFocus，最后靠 feed() 重新弹出面板。
          3) ★ 本段前面（E 段）为了让面板翻到上方，临时 `show()` 过一个顶层小窗口
             `probe_bottom` 又把它 close 了 —— 主窗口从此**不再是活动窗口**。
             活动窗口丢了之后，Qt 里"没有活动窗口就没有键盘焦点"，
             `focusObject()` 会变成 None。这不是 App 的问题，是测试自己把状态弄脏了：
             ★ 修法就是在还焦点前先 `activateWindow()`。
             实测（`_probe_real_focus.py`，真实 MainWindow 的完整流程）里
             App 自己**从来不会**丢焦点：面板弹出后 focusWidget 一直是搜索框，
             Win32 键盘焦点也一直压在主窗口上。
        """
        pop.hide()
        win.activateWindow()
        box.setFocus(Qt.OtherFocusReason)
        pump(6)

    # ---- G1 输入法焦点：面板弹出来之后，中文还组不组得进字 ----
    #   （焦点要是没了：搜索框光标会消失、系统的输入法也找不到落字的地方）
    focus_box()
    feed("")
    check("弹层弹出前：输入法焦点对象就是搜索框",
          app.focusObject() is box, brief(app.focusObject()))
    feed("园")
    check("（前置）弹层已弹出（且焦点还在搜索框）",
          pop.isVisible() and app.focusWidget() is box,
          f"面板={pop.isVisible()} 焦点={brief(app.focusWidget())}")
    check("★ 弹层弹出后：输入法焦点对象仍是搜索框（中文组字不受影响）",
          app.focusObject() is box, brief(app.focusObject()))
    check("  弹层弹出后：搜索框光标还在（hasFocus）", box.hasFocus())
    check("  弹层弹出后：Win32 键盘焦点仍在主窗口（系统输入法认得这个窗口）",
          win32_focus() == int(win.winId()),
          f"GetFocus={win32_focus()} 主窗口={int(win.winId())}")

    check("面板的按键转发目标就是搜索框（结构）", pop.key_target() is box)

    focus_box()
    feed("")
    wkey(Qt.Key_B)
    check("弹层关着时，窗口级按键能进搜索框（基线）", box.text() == "b", repr(box.text()))

    focus_box()
    feed("园")
    check("（前置）弹层已弹出", pop.isVisible())
    wkey(Qt.Key_B)
    check("★ 弹层开着时，按键仍能进搜索框（v2.5.1 修复）",
          box.text() == "园b", repr(box.text()))

    # 连打多个字 —— 用户原话就是"接着打字进不去"
    focus_box()
    feed("园")
    before_len = len(box.text())
    for k in (Qt.Key_B, Qt.Key_C, Qt.Key_A):
        wkey(k)
    check("★ 弹层开着时，连打 3 个字一个都不丢",
          len(box.text()) == before_len + 3, repr(box.text()))

    # 退格
    focus_box()
    feed("园山")
    check("（前置）弹层开着且有候选", pop.isVisible() and len(pop.visible_rows()) > 0)
    wkey(Qt.Key_Backspace)
    check("★ 弹层开着时，退格能删掉字（用户报的第二条）",
          box.text() == "园", repr(box.text()))
    check("  删完面板还开着（内容还有匹配）", pop.isVisible())

    # 上下选 + 回车选中
    focus_box()
    feed("园")
    _ap = app.activePopupWidget()
    check("（前置）↓ 之前：面板可见 + 焦点在搜索框",
          pop.isVisible() and app.focusWidget() is box,
          f"面板={pop.isVisible()} 焦点={brief(app.focusWidget())} "
          f"activePopup={type(_ap).__name__ if _ap else None} "
          f"行数={len(pop.visible_rows())} 面板位置=({pop.x()},{pop.y()}) "
          f"窗口位置=({win.x()},{win.y()})")
    wkey(Qt.Key_Down)
    check("弹层开着时，↓ 能高亮第 1 行", pop.active_index() == 0,
          f"active={pop.active_index()}")
    wkey(Qt.Key_Down)
    check("  再 ↓ 到第 2 行", pop.active_index() == 1, f"active={pop.active_index()}")
    wkey(Qt.Key_Up)
    check("  ↑ 回第 1 行", pop.active_index() == 0, f"active={pop.active_index()}")
    if pop.active_index() >= 0:
        want = pop.visible_rows()[pop.active_index()].text()
    else:
        want = ""
    wkey(Qt.Key_Return)
    check("弹层开着时，回车选中高亮项", win.map_view._focus_station_id == want,
          f"期望={want!r} 实际={win.map_view._focus_station_id!r}")
    check("  选完面板收起", not pop.isVisible())

    focus_box()
    feed("园")
    wkey(Qt.Key_Escape)
    check("弹层开着时，Esc 关掉面板", not pop.isVisible())

    print("\n===== F 性能（逐键动作）=====")
    drain()
    # 1) 功能自身的处理耗时：直接量处理器（筛选 + 填面板 + 定位，本功能每键做的全部事）
    handler = []
    for q in ("园", "深", "机场", "宝安", "车"):
        t0 = time.perf_counter()
        win._on_search_text_changed(q)
        handler.append((q, (time.perf_counter() - t0) * 1000.0))
    worst_h = max(t for _, t in handler)
    print("  处理器耗时：" + "  ".join(f"{q}={t:.2f}ms" for q, t in handler))
    check("每键的筛选+刷新 < 10ms", worst_h < 10.0, f"最慢 {worst_h:.2f}ms")

    # 2) 弹层"从隐藏到显示"一次的耗时。
    #    ★ 这一项单独量：面板已显示时再 show() 是空操作（实测 0.00ms），
    #      拿它当"弹出耗时"会得出假的好数字。真正花钱的是 hide→show 这一次。
    #    ★ 还必须在"主窗口是活动窗口"的状态下量才准（见 focus_box 的第 3 条坑）：
    #      主窗口没被激活时 Qt 会跳过一部分真实绘制，量出来只有 13ms，
    #      激活之后是 27ms —— 用户的真实环境是后者。
    feed("园")
    pop.hide()
    pump(2)

    def show_cycle():
        pop.hide()
        pump(1)
        pop.show()
        pump(2)

    t_show = max(ms(show_cycle, 1) for _ in range(5))
    print(f"  弹层 隐藏→显示（24 行）: {t_show:.2f} ms")
    check("弹层重新弹出一次 < 60ms（一次搜索只弹一次，这个量级可以接受）",
          t_show < 60.0, f"{t_show:.2f}ms")

    # 3) 真实打字：**接着敲** 3 个字。
    #    ★★ 量法上的坑（这次踩的，记下来）：
    #       原来每轮都先 `box.clear()`。清空会让弹层先收起来，于是每敲一个字都
    #       白搭一次"弹层重新弹出"（27ms），3 个字量出 46ms，看着像打字很卡 ——
    #       其实是量法把"弹出成本"摊到了每一键上。
    #       真实打字是**接着敲**的，弹层只弹一次。
    #       现在改成：先用一个字把弹层弹出来（弹出成本由上面第 2 项单独负责），
    #       再开始计时连敲 3 个字。这同时也正是用户报 bug 的那个动作
    #       （"接着打字进不去"）。
    #    ★ 另外，前面 A~G 段攒下的地图补渲染会渗进这里的计时（实测能把每键
    #      从 2~4ms 抬到 10~14ms），所以计时前再排空一次队列。
    drain()
    def type_three(qs="深圳北站"):
        box.clear()
        pump(2)
        first, rest = qs[0], qs[1:]
        ev = QInputMethodEvent()
        ev.setCommitString(first)
        QApplication.sendEvent(box, ev)      # 先弹出弹层（不计时）
        pump(4)
        t0 = time.perf_counter()
        for ch in rest:
            ev = QInputMethodEvent()
            ev.setCommitString(ch)
            QApplication.sendEvent(box, ev)
            pump(2)
        return (time.perf_counter() - t0) * 1000.0

    trials = sorted(type_three() for _ in range(7))
    lo, med, hi = trials[0], trials[len(trials) // 2], trials[-1]
    # ★ 判据用**最快一次**，不用中位数：本机噪声是"突发型"的
    #   （同一段代码实测 8.4ms ~ 101.8ms 都出现过，差 12 倍），
    #   而噪声只会让耗时**变大**、绝不会变小 —— 所以最小值最接近真实成本，
    #   中位数在突发噪声下会忽绿忽红，不能当判据。中位/最慢照报，用来看抖动。
    print(f"  接着敲 3 个字（弹层已开着）：最快 {lo:.1f}ms  中位 {med:.1f}ms  "
          f"最慢 {hi:.1f}ms  （按最快算单键约 {lo / 3:.1f}ms）")
    check("接着敲 3 个字最快 < 45ms（每键 < 15ms，打字跟手）",
          lo < 45.0, f"最快 {lo:.1f}ms")
    print(f"  〔参照〕本机干净环境实测：单键 2~4ms、卡片改高度 0.66ms、"
          f"只重绘 0.70ms（tools/_probe_type_cost.py）")
    print("  〔说明〕上面这 3 个数字里，真正能当「回归报警」的是 F#1 的处理器耗时"
          "（筛选+刷新 < 10ms）；这一项只是「端到端手感」的粗判，本机噪声大。")

    # 4) 对照：面板关着敲字（不含本功能）—— 只报告，不设阈值
    box.textChanged.disconnect(win._on_search_text_changed)
    ctrl = sorted(type_three() for _ in range(3))
    box.textChanged.connect(win._on_search_text_changed)
    print(f"  对照（面板关着接着敲 3 个字）：最快 {ctrl[0]:.1f}ms  中位 {ctrl[1]:.1f}ms")
    print(f"  → 本功能每键净增约 {(lo - ctrl[0]) / 3:.1f}ms")

    pop.hide()
    win.close()
    pump(4)

    print(f"\n===== 结果：{PASS} 通过 / {FAIL} 失败 =====")
    if FAILED:
        print("失败项：")
        for n in FAILED:
            print("  -", n)
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())

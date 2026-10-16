"""
ui/autofit.py
==============================
多行输入框（QPlainTextEdit）的「高度自动拉伸」（v2.6.8）。

用户原话：「编辑页面的输入框全部都改为自动拉伸高度
          （文字多少均拉伸到刚好全部显示完）」

★ 为什么必须问 QTextDocument 自己、不能按字数估算行数：
  中英文混排、标点避头尾、QPlainTextEdit 自带的 documentMargin —— 任何一项
  都能让估算差掉一整行。差一行就是两种后果：要么冒出内部滚动条（等于没拉伸），
  要么底部空一大截（等于没压缩）。

★ 为什么不能只在构造时算一次：
  ① 构造时布局还没定型，`viewport().width()` 还是默认值 100 → 换行行数完全不同；
  ② 窗口被拉宽/拉窄 → 换行位置变了 → 高度必须跟着变；
  ③ 用户一边打字一边长高 → 还要接 `textChanged`。

★ 为什么一律关掉内部滚动条：高度既然跟着内容走了，再出现滚动条就是"没算准"，
  关掉才能让"算不准"在截图/断言里暴露出来（留着滚动条反而会被误当成正常）。
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QFontMetrics
from PySide6.QtWidgets import QPlainTextEdit, QSizePolicy

# 视口之外还要留的高度：上下各 1 条边框 + 一点呼吸。
# 给太小会出现"最后一行被挤进滚动"，给太大底部会空一截 —— 4px 是实测的甜点。
FRAME_PAD = 4


def doc_height(ed: QPlainTextEdit) -> float:
    """多行输入框里文字的**真实高度**（含 documentMargin）。

    ★★★ 千万不能用 `ed.document().size().height()` —— QPlainTextEdit 用的是
      `QPlainTextDocumentLayout`，它的 `documentSize()` 是**惰性的**：
      **实测 1 行文本返回 1.0、400 个字返回 8.0**，跟内容几乎无关
      （照它算高度 ⇒ 所有框一律压到最小，等于自动拉伸完全没做）。
      只有逐个 block 累加 `blockBoundingRect()` 才拿得到真值
      （同样的数据实测 20.0 / 132.0）。
      —— 这是本轮最坑的一个点：代码看着完全合理，跑起来永远返回最小高度，
         而且是**静默**的，不打日志、不报错。
    """
    doc = ed.document()
    if doc is None:
        return 0.0
    layout = doc.documentLayout()
    total = 0.0
    blk = doc.begin()
    while blk.isValid():
        total += layout.blockBoundingRect(blk).height()
        blk = blk.next()
    return total + 2.0 * float(doc.documentMargin())


def fit_height(ed: QPlainTextEdit, min_h: int = 40, max_h: int = 4000) -> int:
    """把 `ed` 的高度调成"刚好装下当前文字"（返回最终高度）。

    ★ 前提是已经拿到**真实可用宽度**；未布局时 `viewport().width()` 是默认值，
      这种情况直接放弃（等下一次 sync），不然会算出个错高度再被后面纠正，
      表现为"打开弹窗时框先矮一下再跳高"。
    """
    if ed is None:
        return 0
    try:
        vw = ed.viewport().width()
        doc = ed.document()
    except Exception:
        return 0
    if doc is None or vw < 20:
        return ed.height() if ed is not None else 0

    doc.setTextWidth(float(vw))
    need = int(doc_height(ed)) + ed.frameWidth() * 2 + FRAME_PAD
    target = max(int(min_h), min(int(max_h), need))
    if abs(target - ed.height()) >= 1:
        ed.setFixedHeight(target)

    # 校准：设完再确认视口真的装得下（差 1~2px 就会冒出内部滚动条）。
    # ★ 为什么用"补差"循环而不是再算一遍公式：边框 / margin / 行距的取整误差
    #   加起来刚好能差出一行，补差是最稳的收敛方式（实测最多 2 轮就够）。
    for _ in range(3):
        try:
            need_h = int(doc_height(ed))
            got_h = ed.viewport().height()
        except Exception:
            break
        if got_h >= need_h:
            break
        ed.setFixedHeight(ed.height() + (need_h - got_h) + 1)
    return ed.height()


def min_height_for_lines(ed: QPlainTextEdit, lines: int = 2) -> int:
    """「至少显示 N 行」对应的最小像素高度（v2.7.7）。

    ★ 不能直接写死像素：字号是被整体缩放带着变的（SCENE_FONT_PX 那套），
      写死 52px 在字号调小后会留出一大片空白，调大后又只剩一行半。
    ★ 行高必须问 `QFontMetrics.lineSpacing()`（含行距），用 `height()` 会偏小。
    ★ 边框/内边距用**控件自己**的 frameWidth 和本模块的 FRAME_PAD，
      跟 `fit_height` 里的算式保持一致 —— 否则"最小 2 行"会比"实际 2 行"
      差几像素，表现为最后一行被挤进滚动条。
    """
    if ed is None:
        return 0
    try:
        ls = QFontMetrics(ed.font()).lineSpacing()
        fw = ed.frameWidth()
        # ★ documentMargin 不能漏：它是**整段文字外面**的一圈，只算一次，
        #   但每一行的行高里并不含它 —— 漏掉它算出的"2 行"会矮掉 8px，
        #   表现为框里看着只有一行半（实测：漏掉 = 38px，补上 = 58px）。
        dm = float(ed.document().documentMargin())
    except Exception:
        return 0
    return int(ls) * int(max(1, lines)) + int(2 * dm) + int(fw) * 2 + FRAME_PAD


def no_inner_scroll(ed: QPlainTextEdit) -> bool:
    """判据用：文字是否真的装进了视口（没有内部滚动）。"""
    try:
        return int(doc_height(ed)) <= ed.viewport().height() + 1
    except Exception:
        return False


class AutoFitGroup:
    """一批"会自己长高"的多行输入框。

    用法::

        g = AutoFitGroup()
        g.add(ed, min_h=40)
        g.sync()          # 布局定型后 / 窗口 resize 后调一次

    ★ `textChanged` 里直接同步（不用 QTimer）：`setFixedHeight` 不会反过来
      触发 textChanged，没有递归风险；而用 QTimer 反而会让你在断言里量到
      "上一帧的高度"（见 MEMORY §5.15 同源的"未布局几何"坑）。
    """

    def __init__(self, min_h: int = 40, max_h: int = 4000):
        self._items: list = []
        self.min_h = int(min_h)
        self.max_h = int(max_h)

    def add(self, ed, min_h: int = None) -> None:
        if ed is None:
            return
        mh = self.min_h if min_h is None else int(min_h)
        ed.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        ed.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        ed.setLineWrapMode(QPlainTextEdit.WidgetWidth)
        ed.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        ed.setMinimumHeight(mh)
        ed.setMaximumHeight(self.max_h)
        self._items.append((ed, mh))
        # ★ 默认参数 `_ed=ed` 不能省：在循环里连 lambda 会全部捕获到最后一个
        ed.textChanged.connect(lambda _ed=ed, _mh=mh: fit_height(_ed, _mh, self.max_h))

    def sync(self) -> None:
        for ed, mh in self._items:
            fit_height(ed, mh, self.max_h)

    def __len__(self) -> int:
        return len(self._items)

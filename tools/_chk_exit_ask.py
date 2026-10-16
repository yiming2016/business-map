"""_chk_exit_ask.py — v2.7.32 回归：退出时"要不要把整张图保存为图片？"的触发条件

背景（用户反馈）：开一下软件、**什么元素都没改**，关掉时也弹这个询问。
期望：只有"数据改过、图上已过期"时才问；数据没动就别打扰。

做法：不起 GUI（不需要 QApplication）——用 `MainWindow.__new__` 造一个壳，
只调 `_img_is_fresh()` 这一个纯逻辑方法，数据目录用临时副本，绝不碰真实数据。

跑法（项目自带的构建解释器）：
    "C:/Users/29773/.workbuddy/binaries/python/envs/default/Scripts/python.exe" tools/_chk_exit_ask.py
"""
import os
import sys
import json
import shutil
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from ui import image_mode as IM                     # noqa: E402
from ui.main_window import MainWindow               # noqa: E402

PASS = FAIL = 0


def check(name, ok, extra=""):
    global PASS, FAIL
    if ok:
        PASS += 1
        print(f"  OK   {name}")
    else:
        FAIL += 1
        print(f"  FAIL {name}" + (f"  => {extra!r}" if extra else ""))


def make_shell(data_dir, sig):
    """造一个只有必要属性的 MainWindow 壳（不跑 __init__、不建窗口）。"""
    o = MainWindow.__new__(MainWindow)
    o.dm = type("D", (), {"DATA_DIR": str(data_dir)})()
    o._img_sig_done = sig
    o._view_img = object()                          # 假装本次会话烘过图
    return o


def main():
    work = Path(tempfile.mkdtemp(prefix="chk_exit_ask_"))
    try:
        # 用真实数据文件的副本当"数据目录"，避免污染项目数据
        src_data = ROOT / "data"
        for name in ("stations.json", "lines.json"):
            s = src_data / name
            if s.exists():
                shutil.copy(s, work / name)
            else:
                (work / name).write_text("{}", encoding="utf-8")

        sec = IM.load_settings(str(work))
        print("--- 设置默认值 ---")
        check("ask_on_exit 默认 True（保持原行为：该问的时候还是要问）",
              sec.get("ask_on_exit") is True, sec.get("ask_on_exit"))

        png = Path(IM.png_path(str(work), sec))
        png.parent.mkdir(parents=True, exist_ok=True)

        print("--- 场景1：什么都没改，png 还在 → 不该问 ---")
        sig = IM.signature(str(work))
        sh = make_shell(work, sig)
        check("指纹非空（数据文件读到了）", bool(sig), sig)
        check("png 不存在时 → 仍然要问", sh._img_is_fresh() is False)
        png.write_bytes(b"fake-png")
        check("png 在 + 数据没变 → 跳过询问", sh._img_is_fresh() is True)

        print("--- 场景2：改了元素 → 要问 ---")
        st = json.loads((work / "stations.json").read_text(encoding="utf-8"))
        if isinstance(st, dict):
            st["__chk_new_station__"] = {"name": "测试站", "x": 1, "y": 2}
        else:
            st = list(st) + [{"id": "__chk_new_station__", "name": "测试站"}]
        (work / "stations.json").write_text(
            json.dumps(st, ensure_ascii=False, indent=2), encoding="utf-8")
        check("数据变了 → 图过期，要问", sh._img_is_fresh() is False)
        check("指纹确实变了", IM.signature(str(work)) != sig)

        print("--- 场景3：改完又烘了新图 → 不问 ---")
        sh._img_sig_done = IM.signature(str(work))
        check("重新烘图后（指纹已同步）→ 跳过询问", sh._img_is_fresh() is True)

        print("--- 场景4：其它边界 ---")
        sh2 = make_shell(work, None)
        check("本次没烘过图（sig 为 None）→ 老实问", sh2._img_is_fresh() is False)

        sh3 = make_shell(work, "")
        check("sig 为空串 → 老实问", sh3._img_is_fresh() is False)

        png.unlink()
        check("png 被用户删了 → 要问", sh._img_is_fresh() is False)

        print("--- 场景5：lines.json 改了也算改（指纹覆盖两个文件）---")
        png.write_bytes(b"fake-png")
        ln = work / "lines.json"
        old = ln.read_text(encoding="utf-8")
        ln.write_text(old + "\n", encoding="utf-8")
        check("lines.json 变 1 个字节 → 图过期，要问", sh._img_is_fresh() is False)
    finally:
        shutil.rmtree(work, ignore_errors=True)

    print(f"\n== _chk_exit_ask 结果：{PASS} 通过 / {FAIL} 失败 ==")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())

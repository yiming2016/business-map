"""
build_exe.py
========================
一键打包脚本：使用 PyInstaller 把整个项目打成单文件 exe，输出到 ../软件。

目录约定（2026-09-18 重组后）：
  · 源码/  ← 本脚本所在处，所有源代码与开发资料
  · 软件/  ← 打包成品 + 运行数据（SZ_MetroEditor.exe / data/ / logs/）

踩过的坑（别再踩）：
  1. 旧 exe 还开着 → shutil.copy2 撞 WinError 32（文件被占用）。
     → 打包前先 _kill_running_exe()。
  2. 用 shutil.rmtree 删 PyInstaller 的中间目录，会撞上沙箱的"批量删除保护"
     （单目录条目数 > 50 就拦截），把整个打包流程打断。
     → 给 PyInstaller 指定**全新的** --workpath，从根上不做删除动作。
  3. ★★ 输出目录（软件/）里除了 exe，还有用户的 data/（站点数据）和 logs/。
     早期版本会先 `_clear_dir(DIST)` 清空整个输出目录 —— 那等于
     **每打包一次就把用户数据删光**。现在改成只删文件、目录一律不动。
"""

import os
import sys
import time
import shutil
import tempfile
import subprocess
from pathlib import Path

# 源码目录（包含 main.py 的位置）
SRC_ROOT = Path(__file__).resolve().parent
# 打包输出目录：与源码同级的「软件」文件夹
OUT_ROOT = SRC_ROOT.parent / "软件"
DIST = OUT_ROOT
EXE_NAME = "SZ_MetroEditor"


def _kill_running_exe() -> int:
    """打包前干掉正在运行的 exe，否则输出文件被占用会失败。"""
    name = f"{EXE_NAME}.exe"
    try:
        out = subprocess.check_output(
            ["tasklist", "/FI", f"IMAGENAME eq {name}", "/FO", "CSV", "/NH"],
            stderr=subprocess.DEVNULL,
        ).decode("gbk", errors="ignore")
    except Exception:
        return 0
    pids = [
        line.split(",")[1].strip('"')
        for line in out.splitlines()
        if line.startswith(f'"{name}"')
    ]
    for pid in pids:
        subprocess.call(["taskkill", "/PID", pid, "/F"],
                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        print(f"[CLOSE] 已关闭正在运行的 {name} (PID {pid})")
    if pids:
        time.sleep(1.0)
    return len(pids)


def _clear_output() -> None:
    """只清理输出目录里的**旧文件**（旧 exe / PyInstaller 残留），子目录一律不动。

    ★★ 为什么不能清空整个目录：输出目录是「软件/」，里面除了 exe，还有
       用户的 data/（379 个站点数据）和 logs/（运行日志）。
       早期实现 `_clear_dir` 会把目录内所有条目 rmtree 掉 ——
       等于**每打包一次就删光用户数据**。这里改成只 unlink 文件。
    """
    if not DIST.exists():
        return
    print(f"[CLEAN] {DIST}（只删文件，保留 data/ logs/ 等子目录）")
    for item in list(DIST.iterdir()):
        if item.is_dir():
            continue                      # ★ data/ logs/ 绝对不能碰
        try:
            item.unlink()
        except Exception as e:
            print(f"[WARN] 清理失败 {item}: {e}")


def _set_aside_stale_build() -> None:
    """
    老的 src/build 目录直接留着会混淆，但删它（上百个文件）会触发删除保护。
    用"改名"代替"删除" —— 改名不触发保护。
    """
    stale = SRC_ROOT / "build"
    if not stale.exists():
        return
    target = SRC_ROOT / "_backup" / f"build_stale_{time.strftime('%H%M%S')}"
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        stale.rename(target)
        print(f"[MOVE] 旧中间目录已挪走 → {target}")
    except Exception as e:
        print(f"[WARN] 挪走旧中间目录失败（不影响打包）: {e}")


def _bundle_skip(name: str) -> bool:
    """这个 data 文件要不要**跳过**、不塞进 exe（v2.7.33）。

    · `underlay.png` / 官方线路图：版权归深圳地铁（szmc.net）。公开发布 exe
      （GitHub Release）时把它打进去有版权风险，仓库里也没放它。
      ★ 去掉它**不影响任何逻辑** —— 首启动只初始化 `INITIAL_FILES`
      （stations/lines/schema 三个 json，见 core/data_manager.py），
      本来就不会复制 underlay；本机 data/ 里也仍然有它，功能照常。
    · `*.bak*` / `*.bad_snap*` / `_view_image*` / `_removed_orphans_*`：
      开发时的自动备份与离屏缓存，光这几个就 20MB，塞进 exe 纯属浪费。
    ★ 要恢复"全都打包"的旧行为：把下面两个表清空即可。
    """
    if name in ("underlay.png", "_view_image.png", "_view_image_meta.json"):
        return True
    return name.startswith(("stations.json.bak", "lines.json.bak",
                            "stations.json.bad_snap", "_removed_orphans_"))


def _stage_data_for_bundle() -> Path:
    """给 PyInstaller 准备一份 data 快照，**排除子目录（covers/ 等）与不该入包的文件**
    （后者见 `_bundle_skip()`：官方底图 + 调试备份）。

    ★ 为什么不能直接 `--add-data data;data`：
      data/covers/ 是用户给站点加的封面图，属于用户数据。
      直接整目录打包会把它们塞进 exe（既增大体积，又没意义 ——
      data_manager._bootstrap_data_files() 首启动只会复制 INITIAL_FILES
      里那几个 json，covers/ 根本不会被用上）。
      这里只把 data/ 下的**普通文件**拷进一个临时目录再打包。
    """
    staged = Path(tempfile.gettempdir()) / f"szmetro_data_{int(time.time())}"
    staged.mkdir(parents=True, exist_ok=True)
    src_data = SRC_ROOT / "data"
    if not src_data.exists():
        print(f"[WARN] 找不到 {src_data}，跳过数据打包")
        return src_data
    kept = skipped = 0
    for item in sorted(src_data.iterdir()):
        if item.is_dir():
            print(f"[SKIP] 不打包子目录（用户数据）: data/{item.name}/")
            skipped += 1
            continue
        if _bundle_skip(item.name):
            print(f"[SKIP] 不入包（版权/调试残留）: data/{item.name}")
            skipped += 1
            continue
        shutil.copy2(item, staged / item.name)
        kept += 1
    print(f"[DATA] 打包数据快照：{kept} 个文件入库，{skipped} 项跳过 → {staged}")
    return staged


def main():
    # 0) 关掉正在运行的旧 exe
    _kill_running_exe()

    # 1) 清理输出目录里的旧文件（★ 绝不动 data/ logs/ 子目录）
    DIST.mkdir(parents=True, exist_ok=True)
    _clear_output()

    # 2) 把旧的中间目录挪走（改名，不删除）
    _set_aside_stale_build()

    # 3) 全新 workpath —— 每次都是空目录，PyInstaller 不需要删任何东西
    work = Path(tempfile.gettempdir()) / f"szmetro_build_{int(time.time())}"

    # 3.5) data 快照（排除 covers/ 等子目录，见函数注释）
    data_stage = _stage_data_for_bundle()

    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--noconfirm",
        "--onefile",                       # 单文件 exe
        "--windowed",                      # 不弹黑色控制台
        "--name", EXE_NAME,
        "--workpath", str(work),           # 中间产物 → 全新临时目录
        "--distpath", str(DIST),           # 成品直接进 ../软件
        "--specpath", str(SRC_ROOT),       # .spec 放在源码目录
        # ★ v2.7.0：软件图标（exe 图标 / 任务栏）
        "--icon", str(SRC_ROOT / "assets" / "logo.ico"),
        # 只打包数据文件（地图是程序画的，不需要底图）
        "--add-data", f"{data_stage}{os.pathsep}data",
        # ★ v2.7.0：窗口图标 PNG（运行时经 _frozen_assets_dir 读）
        "--add-data", f"{SRC_ROOT / 'assets' / 'logo.png'}{os.pathsep}assets",
        # v2.6.67：商场图标 PNG（assets/icons/mall_*.png，运行时经 _frozen_assets_dir 读）
        "--add-data", f"{SRC_ROOT / 'assets' / 'icons'}{os.pathsep}assets/icons",
        # 隐藏导入（PySide6 有时候静态分析漏掉）
        "--hidden-import", "PySide6.QtWidgets",
        "--hidden-import", "PySide6.QtCore",
        "--hidden-import", "PySide6.QtGui",
        "--hidden-import", "PySide6.QtOpenGL",
        "--hidden-import", "PySide6.QtOpenGLWidgets",
        "main.py",
    ]
    print("[RUN]", " ".join(cmd))
    rc = subprocess.call(cmd, cwd=str(SRC_ROOT))
    if rc != 0:
        print(f"[FAIL] PyInstaller 返回 {rc}")
        sys.exit(rc)

    exe_path = DIST / f"{EXE_NAME}.exe"
    if exe_path.exists():
        print(f"\n[OK] 打包完成 → {exe_path}")
        print(f"     大小: {exe_path.stat().st_size / 1024 / 1024:.1f} MB")
        print(f"     中间目录（可随时删除）: {work}")
    else:
        print(f"[WARN] 没找到 {EXE_NAME}.exe，请检查上方日志")


if __name__ == "__main__":
    main()

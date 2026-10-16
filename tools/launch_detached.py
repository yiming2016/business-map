# -*- coding: utf-8 -*-
"""
以"完全脱离当前进程树"的方式启动 exe。

背景：直接用 Popen(DETACHED_PROCESS) 启动的 GUI 进程，在被自动化宿主回收进程树时
会被一起杀掉。改用 explorer.exe 作为父进程启动，进程会挂到 explorer 下，
从而脱离宿主的进程树，可以跨命令/跨调用稳定驻留。

用法:
    python tools/launch_detached.py
"""
import os
import subprocess
import sys
import time

# 目录重组后不要再写死绝对路径：从本脚本位置往上推
_SUBWAY = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
EXE = os.path.join(_SUBWAY, "软件", "SZ_MetroEditor.exe")
EXPLORER = r"C:\Windows\explorer.exe"


def running() -> list:
    """返回当前在跑的 SZ_MetroEditor 进程 PID 列表。"""
    try:
        out = subprocess.check_output(
            ["tasklist", "/FI", "IMAGENAME eq SZ_MetroEditor.exe", "/FO", "CSV", "/NH"],
            stderr=subprocess.DEVNULL,
        ).decode("gbk", errors="ignore")
    except Exception:
        return []
    return [
        line.split(",")[1].strip('"')
        for line in out.splitlines()
        if line.startswith('"SZ_MetroEditor.exe"')
    ]


def kill_all() -> int:
    n = 0
    for pid in running():
        subprocess.call(["taskkill", "/PID", pid, "/F"],
                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        n += 1
    return n


def main() -> int:
    if not os.path.isfile(EXE):
        print("[ERROR] 找不到 exe:", EXE)
        return 1

    # 先关旧，再开新
    n = kill_all()
    if n:
        print(f"[CLEAN] 已关闭 {n} 个旧进程")
        time.sleep(0.6)

    # ★ v2.6.50：自动打开的这一份**不抢焦点**。
    #   ★★ explorer.exe 只接受**路径**参数：`explorer <exe> --noactivate` 会让 exe
    #      直接起不来（v2.6.49 实测：日志里连启动行都没有）；env 又传不进去（v2.6.45）。
    #      ⇒ 用**标记文件**：本脚本在 exe 同目录放 `.noactivate`，exe 启动时读到即删。
    flag = os.path.join(os.path.dirname(EXE), ".noactivate")
    try:
        with open(flag, "w", encoding="ascii") as f:
            f.write("1")
        print("[OK] 已写不抢焦点标记:", flag)
    except Exception as e:
        print("[WARN] 标记文件写失败（将照常打开，可能抢焦点）:", repr(e))
    subprocess.Popen([EXPLORER, EXE])
    print("[OK] 已通过 explorer 拉起:", EXE)

    time.sleep(8)
    if os.path.isfile(flag):        # exe 没读到就别留着，免得污染用户手动双击
        try:
            os.remove(flag)
            print("[WARN] 标记文件未被消费（exe 可能没读到它）")
        except Exception:
            pass
    pids = running()
    if pids:
        print("[OK] 进程驻留中，PID =", ", ".join(pids))
        return 0
    print("[ERROR] 进程未存活，请检查 exe 是否可正常启动")
    return 2


if __name__ == "__main__":
    sys.exit(main())

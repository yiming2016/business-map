"""
core/data_manager.py
========================
数据持久化层：负责把 data/stations.json 和 data/lines.json 加载进来，
对外提供新增/修改/删除接口。每次写盘前会生成 .bak 备份，方便回滚。

本模块是整个软件的"数据库"，**主程序不应直接读写 JSON 文件**，
统一通过 DataManager 走，保证原子写、备份、出错回滚。

路径解析策略：
  - 开发模式（直接 python main.py）：data/ 在源码旁（<project>/data/）
  - 打包模式（PyInstaller --onefile）：data/ 在 exe 所在目录下，便于持久化
  - 首启动打包模式时：从 exe 内嵌的初始数据里复制一份到 exe 旁边的 data/
"""

from __future__ import annotations

import json
import os
import shutil
import sys
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional


# ------------------------------------------------------------
# 路径解析（兼容开发/打包两种模式）
# ------------------------------------------------------------

def _is_frozen() -> bool:
    return getattr(sys, "frozen", False)


def _frozen_or_dev_root() -> Path:
    """
    解释：
      - _is_frozen() = True  →  PyInstaller 打包后的 exe
                              项目根 = exe 所在目录 (用户数据要持久化到这里)
      - _is_frozen() = False →  本地源码开发
                              项目根 = __file__.parent.parent
    返回的是"用户数据写入的目标目录"。
    """
    if _is_frozen():
        return Path(sys.executable).resolve().parent
    else:
        return Path(__file__).resolve().parent.parent


def _frozen_assets_dir() -> Path:
    """assets 目录：开发时 = 项目根/assets；打包时 = sys._MEIPASS/assets（只读）。"""
    if _is_frozen():
        return Path(getattr(sys, "_MEIPASS", sys.executable)) / "assets"
    else:
        return Path(__file__).resolve().parent.parent / "assets"


def _frozen_data_dir() -> Path:
    """数据目录：用户数据写在这里。"""
    return _frozen_or_dev_root() / "data"


# 重新计算路径
PROJECT_ROOT = _frozen_or_dev_root()       # 兼容旧代码引用
DATA_DIR = _frozen_data_dir()
STATIONS_FILE = DATA_DIR / "stations.json"
LINES_FILE = DATA_DIR / "lines.json"

# 站点封面图：放在 data/covers/ 下，跟着 data 一起走
# （这样 README 里"把 软件\data\ 拷到 源码\data\"的同步方式对封面同样成立）
COVERS_DIRNAME = "covers"
COVER_EXTS = {".png", ".jpg", ".jpeg", ".bmp", ".gif", ".webp"}


def station_keyed_json_candidates(filename: str) -> List[Path]:
    """"以站名为键"的独立 json（elbow_sides / terminal_badges）的查找顺序：
    **用户数据目录 → 打包内(_MEIPASS) → 源码 data**。

    ★★ 顺序照 `trace_assist._load()`（v2.6.55 踩过：`trace_cloud.json` 不在
       `INITIAL_FILES` 里，新装机器上只有 _MEIPASS 有 ⇒ 只读 DATA_DIR 会全空）。
    ★ `ui/map_view.py` 也用这一份 —— 读写两侧必须同序，否则"写进去了却读不到"。
    """
    out: List[Path] = [Path(DATA_DIR) / filename]
    _mei = getattr(sys, "_MEIPASS", None)
    if _mei:
        out.append(Path(_mei) / "data" / filename)
    out.append(Path(__file__).resolve().parent.parent / "data" / filename)
    return out


def safe_filename(name: str) -> str:
    """把站点名/站 id 变成能当文件名用的字符串（去掉 Windows 非法字符）。"""
    bad = '\\/:*?"<>|\r\n\t'
    out = "".join(("_" if c in bad else c) for c in str(name)).strip().strip(".")
    return out or "station"


# ------------------------------------------------------------
# 首启动：把打包内的初始数据落到用户数据目录
# ------------------------------------------------------------

INITIAL_FILES = ["stations.json", "lines.json", "schema.json"]


def _bootstrap_data_files() -> None:
    """
    在以下场景被调用：
      1) 打包 exe 首次运行：exe 内 _MEIPASS/ 里有初始 JSON，但用户数据目录为空
         → 把这些初始 JSON 复制到 exe 旁边的 data/ 下
      2) 开发模式：data/ 已存在 → 啥也不做
    """
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    if not _is_frozen():
        # 开发模式：data/ 就是源码目录下的，假定已经由开发者维护好
        return

    # 打包模式：从 _MEIPASS 把初始文件复制过去（仅当目标文件不存在）
    src_dir = Path(sys._MEIPASS) / "data"
    if not src_dir.exists():
        return
    for name in INITIAL_FILES:
        dst = DATA_DIR / name
        src = src_dir / name
        if not dst.exists() and src.exists():
            try:
                shutil.copy2(src, dst)
            except Exception as e:
                print(f"[WARN] 复制初始数据 {name} 失败：{e}")


_bootstrap_data_files()


# ------------------------------------------------------------
# 工具函数
# ------------------------------------------------------------

def _read_json(path: Path, default: Any) -> Any:
    """读取 JSON，失败则返回默认值（启动容错用）。"""
    if not path.exists():
        return default
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        print(f"[WARN] 读取 {path.name} 失败，使用空数据继续运行：{e}")
        return default


def _atomic_write_json(path: Path, data: Any) -> None:
    """
    安全写入 JSON：
    0. ★ v2.7.17：内容**一模一样**就什么都不做（不备份、不写、不改 mtime）
    1. 先把现有文件备份成 .bak（如果有）
    2. 写到一个临时文件
    3. 原子替换原文件
    中途崩溃不会损坏数据。

    ★★ 第 0 步为什么必须有：软件每次退出都 `dm.save()` 无条件重写
      stations.json / lines.json。用户一个字没改，mtime 也会变 ——
      而看图模式的缓存指纹曾经就挂在 mtime 上 ⇒ 缓存永远失效 ⇒
      "每次进来都要重新生成图片"（用户原话）。
      指纹已改成内容 md5，但"没改也重写盘"本身仍是白干活
      （还白白刷掉 .bak 备份），所以这里一并堵掉。
    """
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    blob = json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8")
    try:
        if path.exists() and path.read_bytes() == blob:
            return                      # 一字未变 ⇒ 连 mtime 都不动
    except Exception:
        pass

    if path.exists():
        bak = path.with_suffix(path.suffix + ".bak")
        try:
            shutil.copy2(path, bak)
        except Exception as e:
            print(f"[WARN] 备份 {path.name} 失败：{e}")

    tmp = path.with_suffix(path.suffix + ".tmp")
    try:
        # ★ 写的是上面那份 blob（跟"比没变"用的是同一串字节，避免
        #   比较与落盘不一致导致"每次都以为变了"）。
        with open(tmp, "wb") as f:
            f.write(blob)
        if path.exists():
            path.unlink()
        tmp.rename(path)
    except Exception as e:
        print(f"[ERROR] 写入 {path.name} 失败：{e}")
        raise


# ------------------------------------------------------------
# DataManager
# ------------------------------------------------------------

class DataManager:
    """单例使用：dm = DataManager()"""

    def __init__(self) -> None:
        self.stations_doc: Dict[str, Any] = _read_json(STATIONS_FILE, {"version": "1.0", "stations": {}})
        self.lines_doc: Dict[str, Any] = _read_json(LINES_FILE, {"version": "1.0", "lines": []})
        self.stations_doc.setdefault("stations", {})
        self.lines_doc.setdefault("lines", [])

    # ---------- 查询 ----------
    def all_stations(self) -> Dict[str, Dict[str, Any]]:
        return self.stations_doc["stations"]

    def get_station(self, station_id: str) -> Optional[Dict[str, Any]]:
        return self.stations_doc["stations"].get(station_id)

    def all_lines(self) -> List[Dict[str, Any]]:
        return sorted(self.lines_doc["lines"], key=lambda x: x.get("order", 999))

    def get_line(self, line_id: str) -> Optional[Dict[str, Any]]:
        for line in self.lines_doc["lines"]:
            if line.get("id") == line_id:
                return line
        return None

    def line_color(self, line_id: str, default: str = "#888888") -> str:
        line = self.get_line(line_id)
        if line:
            return line.get("color", default)
        return default

    # ---------- 站点 增删改 ----------
    def upsert_station(self, station_id: str, data: Dict[str, Any]) -> None:
        stations = self.stations_doc["stations"]
        existing = stations.get(station_id, {})
        merged = dict(existing)
        for k, v in data.items():
            merged[k] = v
        merged["station_id"] = station_id
        merged["_updated_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
        stations[station_id] = merged

    # ------------------------------------------------------------------
    # 整站改名（v2.6.57）
    # ------------------------------------------------------------------
    @staticmethod
    def _rename_in_seg_key(key: str, old: str, new: str) -> str:
        """把 `"<线号>|<上站>|<下站>"` / `"<线号>|<站名>"` 这类键里的站名换掉。"""
        return "|".join(new if p == old else p for p in str(key).split("|"))

    def rename_station(self, old_id: str, new_name: str) -> bool:
        """把站点连同**所有引用**一起改名。

        ★★ 为什么必须重键：本工程 `station_id == station_name`，
           20 条线的站序数组、折点方向表、末端号码方块表……**全都拿站名当键**。
           以前只改 `station_name` 字段不动键 ⇒ 名字显示是新的、内部编号还是旧的
           ⇒ 半保存状态（按新名查不到、站序里仍是旧名）。

        ★ 同步清单（漏一处就会"改了却没完全改"，比不改还糟）：
           ① stations 的键 + station_id
           ② through_links / transfer_links 的 a、b
           ③ lines[].stations[] 数组元素
           ④ lines_doc 的 segment_shapes / traced（键 "<线号>|<上站>|<下站>"）
           ⑤ data/elbow_sides.json（同上）
           ⑥ data/terminal_badges.json + badge_offsets.json（键 "<线号>|<站名>"）
           ⑦ covers/ 下以旧名命名的封面图文件

        返回 False = 拒绝改名（新名为空 / 和旧名一样 / 新名已被别的站占用）。
        """
        new_name = (new_name or "").strip()
        stations = self.stations_doc["stations"]
        if old_id not in stations:
            return False
        if not new_name or new_name == old_id:
            return False
        if new_name in stations:
            # ★ 别把两个站并成一个：那会静默吞掉一个站的数据，宁可拒绝
            return False

        rec = stations.pop(old_id)
        rec["station_id"] = new_name
        rec["station_name"] = new_name
        stations[new_name] = rec

        # ② 贯通段 / 换乘连接
        for key in ("through_links", "transfer_links"):
            for item in (self.stations_doc.get(key) or []):
                if not isinstance(item, dict):
                    continue
                if item.get("a") == old_id:
                    item["a"] = new_name
                if item.get("b") == old_id:
                    item["b"] = new_name

        # ③ 线路站序
        for ln in (self.lines_doc.get("lines") or []):
            seq = ln.get("stations") or []
            ln["stations"] = [new_name if s == old_id else s for s in seq]

        # ④ lines_doc 里以站名为键的两张表（弧形状 / 自动描线）
        for key in ("segment_shapes", "traced"):
            tbl = self.lines_doc.get(key)
            if not isinstance(tbl, dict):
                continue
            self.lines_doc[key] = {
                self._rename_in_seg_key(k, old_id, new_name): v
                for k, v in tbl.items()
            }

        # ⑤⑥ 独立 json
        self._rename_in_station_keyed_json("elbow_sides.json", old_id, new_name)
        self._rename_in_station_keyed_json("terminal_badges.json", old_id, new_name)
        self._rename_in_station_keyed_json("badge_offsets.json", old_id, new_name)

        # ⑦ 封面图（文件名就是 safe_filename(station_id)）
        self._rename_cover_file(new_name, rec)
        return True

    def _rename_in_station_keyed_json(self, filename: str, old: str, new: str) -> None:
        """改独立 json 里以站名为键的记录。

        ★★ 必须写 **DATA_DIR（用户数据目录）**，不能写模块目录：打包后模块目录
          是临时解包目录（_MEIPASS），写进去重启就没了。
        ★★ 读的那侧（`load_elbow_sides` / `load_terminal_badges`）也**必须同序**
          优先读 DATA_DIR，否则改完写进去了、下次启动还是读老版本。
        ★★★ **源文件要按候选顺序找**：`elbow_sides.json` 不在 `INITIAL_FILES` 里，
          用户数据目录里**压根没有**（实测确认）。只看 DATA_DIR 就会"读不到 ⇒
          跳过 ⇒ 改名不同步"。所以先从 DATA_DIR / _MEIPASS / 源码里找到那一份，
          改完再写进 DATA_DIR（等于顺手在用户目录建了一份）。
        """
        d = None
        for p in station_keyed_json_candidates(filename):
            try:
                with open(p, "r", encoding="utf-8") as fh:
                    d = json.load(fh)
            except (OSError, ValueError, TypeError):
                continue
            break
        if not isinstance(d, dict):
            return
        out = {self._rename_in_seg_key(k, old, new): v for k, v in d.items()}
        if out == d:
            return
        try:
            _atomic_write_json(Path(DATA_DIR) / filename, out)
        except Exception as e:
            print(f"[WARN] 改写 {filename} 失败：{e}")
        # 进程内缓存要跟着失效，否则这一刻的画面还是老键
        try:
            from ui import map_view as _MV
            if filename == "elbow_sides.json":
                _MV._ELBOW_SIDES = None
            elif filename == "terminal_badges.json":
                _MV._TERMINAL_BADGES = None
        except Exception:
            pass

    def _rename_cover_file(self, new_name: str, rec: Dict[str, Any]) -> None:
        """站点图片的文件名 = `safe_filename(station_id)` ⇒ 改名后要跟着重命名。

        ★ v2.6.79：图片升级为**多张**（`images` 列表）。旧的 `cover`（单张）
          自动当作第一张：重命名时把两处一起换，`cover` 始终等于第一张
          （旧字段保留，兼容还没升级的读档路径）。
        """
        d = self.covers_dir()
        names: list = list(rec.get("images") or [])
        cov = (rec.get("cover") or "").strip()
        if cov and cov not in names:
            names.insert(0, cov)
        if not names:
            return
        base = safe_filename(new_name)
        new_list: list = []
        used: set = set()
        for fn in names:
            src = d / fn
            if not src.exists():
                new_list.append(fn)          # 文件本来就不在，名字原样保留
                continue
            suffix = src.suffix
            dst = d / (base + suffix)
            i = 2
            while dst.name in used or (dst.exists() and dst.name != src.name):
                dst = d / f"{base}_{i}{suffix}"
                i += 1
            try:
                if dst.exists():
                    dst.unlink()
                src.rename(dst)
                new_list.append(dst.name)
            except OSError as e:
                print(f"[WARN] 站点图片改名失败：{e}")
                new_list.append(fn)          # 改名失败别把引用弄丢
            used.add(dst.name)
        rec["images"] = new_list
        # cover 保留 = 第一张（旧逻辑/旧探针还在读这个字段）
        rec["cover"] = new_list[0] if new_list else ""

    def delete_station(self, station_id: str) -> bool:
        return self.stations_doc["stations"].pop(station_id, None) is not None

    def generate_station_id(self, station_name: str = "") -> str:
        base = "ST_" + uuid.uuid4().hex[:8]
        existing = self.stations_doc["stations"]
        while base in existing:
            base = "ST_" + uuid.uuid4().hex[:8]
        return base

    # ---------- 站点封面图 ----------
    def covers_dir(self) -> Path:
        d = DATA_DIR / COVERS_DIRNAME
        d.mkdir(parents=True, exist_ok=True)
        return d

    def cover_path(self, filename: str) -> Optional[Path]:
        """由站点数据里的 cover 字段（只存文件名）拿到绝对路径。"""
        name = (filename or "").strip()
        if not name:
            return None
        p = DATA_DIR / COVERS_DIRNAME / name
        return p if p.exists() else None

    def resolve_cover(self, data: Optional[Dict[str, Any]]) -> Optional[Path]:
        """给 tooltip 用：从整条站点数据直接取到封面图绝对路径（第一张）。"""
        paths = self.resolve_images(data)
        return paths[0] if paths else None

    def resolve_images(self, data: Optional[Dict[str, Any]]) -> list:
        """★ v2.6.79：站点的**全部**图片绝对路径（按顺序）。

        · `images` 列表为主；列表缺失/为空时回退到旧的单张 `cover`
          （旧数据不用迁移也能看）。
        · 顺手过滤掉文件已不存在的条目，别把坏引用喂给 UI。
        """
        if not data:
            return []
        names = data.get("images")
        if isinstance(names, str):
            names = [names]
        paths: list = []
        for n in (names or []):
            p = self.cover_path(str(n))
            if p:
                paths.append(p)
        if not paths:
            p = self.cover_path(str(data.get("cover") or ""))
            if p:
                paths.append(p)
        return paths

    def import_cover(self, station_id: str, src_path: str) -> str:
        """把外部图片拷进 covers/，返回**落盘文件名**。

        只负责拷文件 + 返回名字，**不改站点数据** —— 调用方把返回值放进
        payload["cover"]，再走统一的 upsert_station 落盘。
        （新建站点时 station_id 是保存那一刻才生成的，所以必须拆成两步。）
        """
        src = Path(src_path)
        if not src.exists():
            raise FileNotFoundError(f"找不到图片：{src}")
        ext = src.suffix.lower()
        if ext not in COVER_EXTS:
            raise ValueError(f"不支持的图片格式：{ext or '（无扩展名）'}")

        dst_dir = self.covers_dir()
        base = safe_filename(station_id or src.stem)
        # 同一个站点换封面：先把旧的（可能是别的扩展名）删掉，避免留孤儿文件
        for old in dst_dir.glob(base + ".*"):
            try:
                old.unlink()
            except Exception as e:
                print(f"[WARN] 删除旧封面 {old.name} 失败：{e}")
        dst = dst_dir / f"{base}{ext}"
        shutil.copy2(src, dst)
        return dst.name

    def import_image(self, station_id: str, src_path: str) -> str:
        """★ v2.6.79：多图模式 —— 把外部图片拷进 covers/，返回落盘文件名。

        与 `import_cover` 的区别：**不删同名旧文件**（多张图共存），
        命名冲突就往后排 `_2 / _3 …`，绝不覆盖已有图片。
        """
        src = Path(src_path)
        if not src.exists():
            raise FileNotFoundError(f"找不到图片：{src}")
        ext = src.suffix.lower()
        if ext not in COVER_EXTS:
            raise ValueError(f"不支持的图片格式：{ext or '（无扩展名）'}")
        dst_dir = self.covers_dir()
        base = safe_filename(station_id or src.stem)
        dst = dst_dir / f"{base}{ext}"
        i = 2
        while dst.exists():
            dst = dst_dir / f"{base}_{i}{ext}"
            i += 1
        shutil.copy2(src, dst)
        return dst.name

    def remove_cover(self, filename: str) -> bool:
        p = self.cover_path(filename)
        if not p:
            return False
        try:
            p.unlink()
            return True
        except Exception as e:
            print(f"[WARN] 删除封面 {filename} 失败：{e}")
            return False

    # ---------- 线路 增删改 ----------
    def upsert_line(self, line_id: str, data: Dict[str, Any]) -> None:
        for i, ln in enumerate(self.lines_doc["lines"]):
            if ln.get("id") == line_id:
                self.lines_doc["lines"][i] = {**ln, **data, "id": line_id}
                return
        new_line = {"id": line_id, "order": 999, **data}
        self.lines_doc["lines"].append(new_line)

    def delete_line(self, line_id: str) -> bool:
        for i, ln in enumerate(self.lines_doc["lines"]):
            if ln.get("id") == line_id:
                self.lines_doc["lines"].pop(i)
                return True
        return False

    # ---------- 落盘 ----------
    def save(self) -> None:
        try:
            _atomic_write_json(STATIONS_FILE, self.stations_doc)
            _atomic_write_json(LINES_FILE, self.lines_doc)
        except Exception as e:
            print(f"[ERROR] DataManager.save 失败：{e}")
            raise

    # ---------- 导入 ----------
    def bulk_import(self, items: List[Dict[str, Any]]) -> Dict[str, int]:
        added = updated = failed = 0
        existing_ids = set(self.stations_doc["stations"].keys())

        normalized: List[Dict[str, Any]] = []
        if isinstance(items, dict):
            for sid, body in items.items():
                row = dict(body)
                row.setdefault("station_id", sid)
                normalized.append(row)
        elif isinstance(items, list):
            normalized = items
        else:
            return {"added": 0, "updated": 0, "failed": 0}

        for row in normalized:
            try:
                sid = row.get("station_id") or self.generate_station_id(row.get("station_name", ""))
                was_new = sid not in existing_ids
                self.upsert_station(sid, row)
                if was_new:
                    added += 1
                else:
                    updated += 1
            except Exception as e:
                print(f"[WARN] 导入站点 {row.get('station_name', '?')} 失败：{e}")
                failed += 1

        self.save()
        return {"added": added, "updated": updated, "failed": failed}


# 单例
_data_manager: Optional[DataManager] = None


def get_data_manager() -> DataManager:
    global _data_manager
    if _data_manager is None:
        _data_manager = DataManager()
    return _data_manager

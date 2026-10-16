# -*- coding: utf-8 -*-
"""建 GitHub Release 并上传 exe 附件（一次性脚本，不属于项目源码）。

用法：
    python _rel_upload.py <token> <tag> <title> <notes.md> <asset>

为什么用 urllib 手写而不用 gh：这台机器没装 gh；而且手写能精确控制
"已存在同名 release 就更新、不重复建"。
"""
import json
import sys
import urllib.request
import urllib.error
from pathlib import Path

OWNER_REPO = "yiming2016/business-map"
API = "https://api.github.com"
UPLOADS = "https://uploads.github.com"


def req(method, url, token, data=None, ctype="application/json", raw=False):
    r = urllib.request.Request(url, data=data, method=method)
    r.add_header("Authorization", f"token {token}")
    r.add_header("Accept", "application/vnd.github+json")
    r.add_header("User-Agent", "metro-editor-release")
    if data is not None:
        r.add_header("Content-Type", ctype)
    try:
        with urllib.request.urlopen(r, timeout=600) as resp:
            body = resp.read()
            return resp.status, (body if raw else json.loads(body or b"{}"))
    except urllib.error.HTTPError as e:
        return e.code, e.read()[:800]


def main() -> int:
    token, tag, title, notes_path, asset = sys.argv[1:6]
    notes = Path(notes_path).read_text(encoding="utf-8")
    asset_p = Path(asset)
    print(f"[INFO] 附件 {asset_p.name}  {asset_p.stat().st_size/1048576:.1f} MB")

    # 1) 已有同名 tag 的 release？有就改，没有就建
    st, cur = req("GET", f"{API}/repos/{OWNER_REPO}/releases/tags/{tag}", token)
    payload = {
        "tag_name": tag,
        "target_commitish": "main",
        "name": title,
        "body": notes,
        "draft": False,
        "prerelease": False,
    }
    if st == 200 and isinstance(cur, dict):
        print(f"[INFO] 已存在 release id={cur['id']}，改为更新")
        st, rel = req("PATCH", f"{API}/repos/{OWNER_REPO}/releases/{cur['id']}",
                      token, json.dumps(payload).encode("utf-8"))
    else:
        st, rel = req("POST", f"{API}/repos/{OWNER_REPO}/releases", token,
                      json.dumps(payload).encode("utf-8"))
    if st not in (200, 201):
        print(f"[FAIL] 建 release 失败 HTTP {st}: {rel}")
        return 1
    rid = rel["id"]
    print(f"[OK] release id={rid}  {rel['html_url']}")

    # 2) 上传附件（同名附件先删掉，避免重名冲突）
    st, assets = req("GET", f"{API}/repos/{OWNER_REPO}/releases/{rid}/assets", token)
    if st == 200:
        for a in assets:
            if a["name"] == asset_p.name:
                print(f"[INFO] 先删旧附件 {a['name']} id={a['id']}")
                req("DELETE", f"{API}/repos/{OWNER_REPO}/releases/assets/{a['id']}", token)

    url = (f"{UPLOADS}/repos/{OWNER_REPO}/releases/{rid}/assets"
           f"?name={asset_p.name}&label=Windows%20x64")
    st, out = req("POST", url, token, asset_p.read_bytes(),
                  ctype="application/octet-stream")
    if st not in (200, 201):
        print(f"[FAIL] 上传附件失败 HTTP {st}: {out}")
        return 1
    print(f"[OK] 附件已上传 {out['name']}  {out['size']/1048576:.1f} MB")
    print(f"     下载直链 {out['browser_download_url']}")
    print(f"     Release 页面 {rel['html_url']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

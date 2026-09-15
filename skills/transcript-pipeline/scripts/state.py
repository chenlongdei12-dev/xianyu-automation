#!/usr/bin/env python3
"""逐字稿流水线状态管理（断点续跑）。

状态文件: <root>/_pipeline_state.json

  {
    "root": "/path/to/root",
    "bloggers": {
      "清华白也": {
        "export":      {"done": true,  "at": "...", "note": "160 篇"},
        "clean":       {"done": true,  "at": "...", "note": "148/158 改动"},
        "shot":        {"done": true,  "at": "...", "note": "红字封面.png"},
        "upload_ima":  {"done": true,  "at": "...", "note": "...", "link": null},
        "upload_baidu": {"done": true, "at": "...", "note": "...", "link": "https://pan.baidu.com/s/xxx"},
        "upload_quark": {"done": true, "at": "...", "note": "...", "link": "https://pan.quark.cn/s/xxx"}
      }
    }
  }

2026-09-16 v2: upload 拆分为三通道 upload_ima / upload_baidu / upload_quark，
每通道独立 done/link；旧状态文件（upload 单阶段）读取时自动迁移。
"""
import argparse
import json
import os
import sys
from datetime import datetime

STAGES = ["export", "clean", "shot", "upload_ima", "upload_baidu", "upload_quark"]
CN = {"export": "导（导出逐字稿）", "clean": "清（校对格式分段）",
      "shot": "截（访达截图加红字）",
      "upload_ima": "传-ima（知识库）", "upload_baidu": "传-百度（永久分享）",
      "upload_quark": "传-夸克（永久分享）"}

LEGACY_STAGES = ["upload"]  # 旧版单阶段上传，读取时迁移为三通道


def state_path(root):
    return os.path.join(os.path.abspath(root), "_pipeline_state.json")


def load(root):
    p = state_path(root)
    if os.path.exists(p):
        st = json.load(open(p, encoding="utf-8"))
    else:
        return {"root": os.path.abspath(root), "bloggers": {}}
    # 旧格式迁移：upload → 三通道。旧 upload 实际只上传过百度，故 done 只折算给 upload_baidu
    changed = False
    for b, stages in st.get("bloggers", {}).items():
        if "upload" in stages:
            old = stages.pop("upload")
            blank = {"done": False, "at": None, "note": "", "link": None}
            stages["upload_ima"] = blank
            stages["upload_baidu"] = dict(old) if old.get("done") else dict(blank)
            stages["upload_quark"] = dict(blank)
            changed = True
    if changed:
        save(root, st)
    return st


def save(root, st):
    p = state_path(root)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    json.dump(st, open(p, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    return p


def now():
    return datetime.now().strftime("%Y-%m-%d %H:%M")


def blank_stages():
    return {s: {"done": False, "at": None, "note": "", "link": None} for s in STAGES}


def cmd_init(a):
    st = load(a.root)
    if a.blogger:
        b = st["bloggers"].setdefault(a.blogger, blank_stages())
        # 补齐缺失阶段（老记录升级）
        for s in STAGES:
            b.setdefault(s, {"done": False, "at": None, "note": "", "link": None})
    p = save(a.root, st)
    print("状态文件: %s" % p)
    print("已登记博主: %s" % ", ".join(st["bloggers"].keys()))
    return 0


def cmd_status(a):
    st = load(a.root)
    if not st["bloggers"]:
        print("尚无记录。先跑 init --blogger <博主名>")
        return 0
    for b, stages in st["bloggers"].items():
        done = [s for s in STAGES if stages.get(s, {}).get("done")]
        cur = next((s for s in STAGES if not stages.get(s, {}).get("done")), None)
        print("● %s  [%d/%d]  %s" % (b, len(done), len(STAGES),
                                      "完成" if not cur else "下一步: " + CN[cur]))
        for s in STAGES:
            d = stages.get(s, {})
            flag = "✔" if d.get("done") else "·"
            link = ("  " + d["link"]) if d.get("link") else ""
            print("    %s %-13s %-14s %s%s"
                  % (flag, s, d.get("at") or "", d.get("note") or "", link))
    return 0


def cmd_next(a):
    st = load(a.root)
    stages = st["bloggers"].get(a.blogger)
    if stages is None:
        print("未登记博主 %s，先 init" % a.blogger)
        return 1
    cur = next((s for s in STAGES if not stages.get(s, {}).get("done")), None)
    if not cur:
        print("%s 六个阶段全部完成 ✔" % a.blogger)
        return 0
    b = a.blogger
    print("下一个阶段: %s —— %s\n" % (cur, CN[cur]))
    # 跨机器适配：优先 WorkBuddy 托管 python，回退当前解释器
    import glob as _glob
    _cand = _glob.glob(os.path.expanduser(
        "~/.workbuddy/binaries/python/envs/default/bin/python"))
    PY = _cand[0] if _cand else sys.executable or "python3"
    S = os.path.dirname(os.path.abspath(__file__))
    hints = {
        "export": "调用 biji-export skill 导出该博主逐字稿到 <root>/%s/" % b,
        "clean": ("%s\nT=~/.workbuddy/skills/transcript-cleanup/scripts/toolkit.py\n"
                  "$PY $T backup \"<root>/%s\" && $PY $T scan \"<root>/%s\"\n"
                  "…按 transcript-cleanup SKILL.md 六步执行，qa 必须 0 问题" % (PY, b, b)),
        "shot": ("%s ~/.workbuddy/skills/finder-shot-redhead/scripts/make_cover.py \\\n"
                 "  --folder \"<root>/%s\" \\\n"
                 "  --line1 \"%s抖音全部公开内容逐字稿\" --line2 \"网盘秒发\" \\\n"
                 "  --out \"<root>/%s_红字封面.png\"" % (PY, b, b, b)),
        "upload_ima": ("node %s/ima_batch_upload.cjs --folder \"<root>/%s\" \\\n"
                       "  --kb-name \"%s逐字稿\" --description \"%s抖音全部公开内容逐字稿\"\n"
                       "（自动：找库/新建共享库KBT_SHARED_KB → 批量重名预检 → 逐篇五步上传 → 断点续传）\n"
                       "完成后 mark --stage upload_ima --done --note '已入库「%s逐字稿」N 篇（共享库）'" % (S, b, b, b, b)),
        "upload_baidu": ("cd \"<root>/%s\" && /usr/bin/zip -q -r -e -P dora2026 \\\n"
                         "  \"/tmp/%s_抖音全部公开内容逐字稿_<N>篇.zip\" *.md\n"
                         "export PATH=\"$HOME/.local/bin:$PATH\"   # bdpan 不在默认 PATH\n"
                         "bdpan upload \"/tmp/<zip>\" \"博主逐字稿/%s/<zip>\" --agentname <agent名> \\\n"
                         "  --session-input '<用户原话>' --session-id '<ts-rand>'\n"
                         "bdpan share \"博主逐字稿/%s/<zip>\" --period 0 …（永久；只传加密zip，禁封面/json）\n"
                         "验证：提取码流程后 grep risk-label 必须为 0\n"
                         "mark --stage upload_baidu --done --note '提取码xx 解压密码dora2026' --link '<链接>'" % (b, b, b, b)),
        "upload_quark": ("cd ~/.workbuddy/skills/quarkclouddrive\n"
                         "node scripts/quark-drive.cjs upload \"/tmp/<加密zip>\" \\\n"
                         "  --session-input '<用户原话>' --session-id '<ts-rand>'\n"
                         "node scripts/quark-drive.cjs share <zip_fid> --url-type 1 --expired-type 1\n"
                         "验证：share-detail 查 partial_violation=false 且 file_num=1\n"
                         "mark --stage upload_quark --done --link '<share_url>'（解压密码 dora2026）"),
    }
    print(hints[cur])
    return 0


def cmd_mark(a):
    st = load(a.root)
    stages = st["bloggers"].setdefault(a.blogger, blank_stages())
    for s in STAGES:
        stages.setdefault(s, {"done": False, "at": None, "note": "", "link": None})
    rec = stages.setdefault(a.stage, {"done": False, "at": None, "note": "", "link": None})
    rec["done"] = a.done
    rec["at"] = now() if a.done else None
    if a.note:
        rec["note"] = a.note
    if a.link is not None:
        rec["link"] = a.link
    p = save(a.root, st)
    print("%s / %s → %s%s" % (a.blogger, a.stage,
                              "完成" if a.done else "未完成",
                              ("（%s）" % a.note) if a.note else ""))
    if a.link is not None:
        print("链接: %s" % a.link)
    print("已写入 %s" % p)
    return 0


def cmd_links(a):
    st = load(a.root)
    for b, stages in st.get("bloggers", {}).items():
        print("● %s" % b)
        for s in ("upload_ima", "upload_baidu", "upload_quark"):
            d = stages.get(s, {})
            if d.get("done"):
                print("  %-13s %s" % (s, d.get("link") or "（无链接，见 note: %s）" % (d.get("note") or "-")))
            else:
                print("  %-13s 未完成" % s)
    return 0


def main():
    ap = argparse.ArgumentParser(description="逐字稿流水线状态管理 v2（三通道上传）")
    sub = ap.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("init"); s.add_argument("--root", required=True)
    s.add_argument("--blogger"); s.set_defaults(func=cmd_init)

    s = sub.add_parser("status"); s.add_argument("--root", required=True)
    s.set_defaults(func=cmd_status)

    s = sub.add_parser("next"); s.add_argument("--root", required=True)
    s.add_argument("--blogger", required=True); s.set_defaults(func=cmd_next)

    s = sub.add_parser("mark"); s.add_argument("--root", required=True)
    s.add_argument("--blogger", required=True)
    s.add_argument("--stage", required=True, choices=STAGES)
    s.add_argument("--done", action="store_true")
    s.add_argument("--undo", dest="done", action="store_false")
    s.add_argument("--note", default="")
    s.add_argument("--link", default=None, help="分享链接（百度/夸克）；ima 无链接可省略")
    s.set_defaults(func=cmd_mark, done=True)

    s = sub.add_parser("links"); s.add_argument("--root", required=True)
    s.set_defaults(func=cmd_links)

    a = ap.parse_args()
    return a.func(a)


if __name__ == "__main__":
    sys.exit(main())

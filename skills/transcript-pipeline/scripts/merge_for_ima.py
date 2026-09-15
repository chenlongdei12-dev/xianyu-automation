#!/usr/bin/env python3
"""把单个博主的清洗后逐字稿合并为单个 Markdown，供 ima 知识库单文件上传。

用法:
  python3 merge_for_ima.py --folder "<博主目录>" --out "<输出.md>" [--blogger 名]

- 按文件名序号排序，每篇之间以分隔线衔接
- 输出 UTF-8；文件头部带目录索引（篇数、博主名、合并时间）
- 幂等：重复运行直接覆盖输出文件
"""
import argparse
import os
import re
import sys
from datetime import datetime


def natural_key(name):
    # "001_标题 #标签.md" → 1
    m = re.match(r"^(\d+)", name)
    return int(m.group(1)) if m else 10**9


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--folder", required=True, help="博主清洗后目录")
    ap.add_argument("--out", required=True, help="输出合并 md 路径")
    ap.add_argument("--blogger", default="", help="博主名（默认取目录名）")
    a = ap.parse_args()

    folder = os.path.abspath(a.folder)
    if not os.path.isdir(folder):
        print("目录不存在: %s" % folder, file=sys.stderr)
        return 1
    blogger = a.blogger or os.path.basename(folder.rstrip("/"))

    mds = sorted([f for f in os.listdir(folder) if f.endswith(".md")],
                 key=natural_key)
    if not mds:
        print("目录里没有 .md 文件: %s" % folder, file=sys.stderr)
        return 1

    out_dir = os.path.dirname(os.path.abspath(a.out))
    os.makedirs(out_dir, exist_ok=True)

    parts = []
    parts.append("# %s 抖音全部公开内容逐字稿（合集）\n" % blogger)
    parts.append("> 合并时间：%s ｜ 篇数：%d ｜ 来源：Get笔记导出后清洗版\n"
                 % (datetime.now().strftime("%Y-%m-%d %H:%M"), len(mds)))
    parts.append("\n## 目录\n")
    for i, f in enumerate(mds, 1):
        title = f[:-3]
        parts.append("%d. %s" % (i, title))
    parts.append("\n---\n")

    for f in mds:
        path = os.path.join(folder, f)
        with open(path, encoding="utf-8") as fh:
            body = fh.read().strip()
        parts.append("\n<!-- SOURCE: %s -->\n" % f)
        parts.append(body)
        parts.append("\n---\n")

    content = "\n".join(parts)
    with open(a.out, "w", encoding="utf-8") as fh:
        fh.write(content)

    size_kb = os.path.getsize(a.out) / 1024
    print("已合并 %d 篇 → %s（%.0f KB）" % (len(mds), a.out, size_kb))
    return 0


if __name__ == "__main__":
    sys.exit(main())

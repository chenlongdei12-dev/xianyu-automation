#!/usr/bin/env python3
"""逐字稿清洗工具箱（transcript-cleanup）。

子命令:
  scan    <dir>                  扫描分类：正常稿 / 歌词误转写 / 极短稿 / 无标题
  backup  <dir>                  备份到同级 备份_原始逐字稿_YYYYMMDD/
  apply   <dir> --rules R.json   应用替换规则（literal 或 regex），输出改动日志
  repara  <dir>                  碎片段合并 + 巨段重分段（目标 180~380 字/段）
  qa      <dir>                  质检：H1、结尾换行、词中句号、巨段、弱开头、残留变体
  report  <dir> --backup B       与备份对比，输出改动文件统计

设计原则：只修错、不润色。所有替换规则必须来自看了上下文后的确认，
不确定的写进 rules JSON 的 "review" 字段，只报告不替换。
"""
import argparse
import difflib
import json
import os
import re
import shutil
import statistics
import sys
from datetime import date
from collections import Counter

MD = ".md"
# 不属于正文的段落（歌词文件等）
LYRIC_MARK = "背景音乐歌词"


# ---------- 通用 ----------
def list_md(d):
    return sorted(f for f in os.listdir(d) if f.endswith(MD) and f[0].isdigit())


def read(p):
    return open(p, encoding="utf-8").read()


def write(p, t):
    open(p, "w", encoding="utf-8").write(t)


def split_title_body(text):
    lines = text.split("\n")
    for i, l in enumerate(lines):
        if l.startswith("# "):
            return l, "\n".join(lines[i + 1:])
    return None, text


def paragraphs(body):
    return [p.strip() for p in body.split("\n\n") if p.strip()]


def is_lyric(text):
    return LYRIC_MARK in text or "语音识别结果" in text


# ---------- 重分段 ----------
def split_sentences(text):
    return [p.strip() for p in re.split(r"(?<=[。？！…])", text) if p.strip()]


def reparagraph(body, min_len=180, max_len=380):
    flat = re.sub(r"\s+", "", "".join(paragraphs(body)))
    sents = split_sentences(flat)
    paras, cur = [], ""
    for s in sents:
        cur += s
        if len(cur) >= min_len:
            paras.append(cur)
            cur = ""
    if cur:
        if paras and len(cur) < 80:
            paras[-1] += cur
        else:
            paras.append(cur)
    final = []
    for p in paras:
        while len(p) > max_len * 1.6:
            mid = len(p) // 2
            idx = p.rfind("，", 0, mid + 100)
            if idx < len(p) // 4:
                idx = p.find("，", mid - 100)
            if idx <= 0:
                break
            final.append(p[: idx + 1])
            p = p[idx + 1:]
        final.append(p)
    return "\n\n".join(final)


# ---------- 基础体检 ----------
ORDINAL_OK = {
    # 序数 / 逻辑连接词
    "第一", "第二", "第三", "第四", "第五", "第2", "第3", "第4",
    "首先", "然后", "同时", "另外", "其次", "最后", "比如", "不是",
    "对了", "所以", "但是", "当然", "这样", "坦白", "简单", "说白了",
    "有问题", "错了", "时候", "因", "的", "和", "像", "如果", "他呢",
    "之后呢", "好", "其实", "因为", "反正", "总之", "现在", "以前",
    "后来", "就是", "这个", "那个", "真的", "不过", "而且", "还有",
    # 口语应答/语气词（对话实录里合法存在，不是词中句号）
    "嗯", "哎", "哦", "啊", "哇", "哈", "哈喽", "你看", "你听", "你懂",
    "对", "对啊", "对的", "是的", "没错", "好嘞", "行", "来", "我",
    "你", "他", "她", "它", "我们", "你们", "他们",
    # 句末标点后的口语起头（博主口播常见：上一句结束 → 语气词另起）
    "好了", "好吧", "同理", "兄弟", "对吧", "呃", "算了", "钱", "抖音",
    "我日", "脑", "牛病", "就凭你",
    # 合法句首的转折/提示语（。然而，/。注意，/。那好，/。啊对，均属正常断句）
    "然而", "注意", "那好", "啊对",
}


def find_word_split_periods(body):
    """找出把词切断的误插句号：。X[。，、] 且 X 不是正常句首词。"""
    flat = re.sub(r"\s+", "", body)
    out = []
    for m in re.finditer(r"。([\u4e00-\u9fff]{1,2})[。，、]", flat):
        g = m.group(1)
        if g in ORDINAL_OK:
            continue
        i = m.start()
        out.append((g, flat[max(0, i - 14): i + 16]))
    return out


def find_mega_paragraphs(body, limit=1200):
    return [(len(p), p[:60]) for p in paragraphs(body) if len(p) > limit]


def find_fragment_paragraphs(body):
    """ASR 一句一段的碎片文件特征：段数远多于字数/200。"""
    ps = paragraphs(body)
    chars = sum(len(p) for p in ps)
    return len(ps) > 8 and (chars / max(len(ps), 1)) < 60


# 助词/连词：永不作正常句首，出现即视为段落被切断
HARD_WEAK = "的地得之和与或"
# 副词/连词：可合法作句首（如对话引用『就凭你。』），仅当上一段未正常收尾时才可疑
SOFT_WEAK = "就也都还但是"
TERMINAL = "。？！…\"」”"


def find_weak_starts(body):
    """段落以连词/助词硬开头，说明上一段在句中就被切断了。"""
    ps = paragraphs(body)
    out = []
    for i in range(1, len(ps)):
        if len(ps[i]) >= 30:
            continue
        head = ps[i][0]
        if head in HARD_WEAK:
            out.append((i, ps[i][:24]))
        elif head in SOFT_WEAK and not (ps[i - 1] and ps[i - 1][-1] in TERMINAL):
            out.append((i, ps[i][:24]))
    return out


# ---------- 子命令 ----------
def cmd_scan(a):
    d = a.dir
    files = list_md(d)
    rows, lyric, tiny, notitle, normal = [], [], [], [], []
    for f in files:
        t = read(os.path.join(d, f))
        _, body = split_title_body(t)
        ps = paragraphs(body)
        cn = len(re.findall(r"[\u4e00-\u9fff]", body))
        chars = len(body.strip())
        rec = {"file": f, "chars": chars, "paras": len(ps),
               "cn_ratio": round(cn / max(chars, 1), 2),
               "has_title": t.lstrip().startswith("# "),
               "max_para": max((len(p) for p in ps), default=0)}
        rows.append(rec)
        if is_lyric(t) or rec["cn_ratio"] < 0.35:
            lyric.append(rec)
        elif chars < 100:
            tiny.append(rec)
        elif not rec["has_title"]:
            notitle.append(rec)
        else:
            normal.append(rec)

    print("目录: %s" % d)
    print("文件总数: %d | 正常稿 %d | 歌词/非中文 %d | 极短稿 %d | 无标题 %d"
          % (len(files), len(normal), len(lyric), len(tiny), len(notitle)))
    tot = sum(r["chars"] for r in normal)
    print("正常稿正文合计: %s 字" % format(tot, ","))
    if lyric:
        print("\n[歌词/非中文，正文处理需人工判断]")
        for r in lyric:
            print("  %s  chars=%s cn=%s" % (r["file"][:44], r["chars"], r["cn_ratio"]))
    if tiny:
        print("\n[极短稿]")
        for r in tiny:
            print("  %s  chars=%s" % (r["file"][:44], r["chars"]))
    if notitle:
        print("\n[无 H1 标题]")
        for r in notitle:
            print("  %s" % r["file"][:52])
    mega = [r for r in normal if r["max_para"] > 1200]
    frag = []
    for r in normal:
        t = read(os.path.join(d, r["file"]))
        _, body = split_title_body(t)
        if find_fragment_paragraphs(body):
            frag.append(r["file"])
    if mega:
        print("\n[整篇一大段，需重分段] %d 个" % len(mega))
        for r in mega:
            print("  %s  最长段 %s 字" % (r["file"][:40], r["max_para"]))
    if frag:
        print("\n[一句一段的碎片稿，需合并] %d 个" % len(frag))
        for f in frag[:20]:
            print("  %s" % f[:52])
    if a.json:
        json.dump(rows, open(a.json, "w"), ensure_ascii=False, indent=1)
        print("\n明细已写入 %s" % a.json)
    return 0


def cmd_backup(a):
    d = os.path.abspath(a.dir)
    name = os.path.basename(d)
    stamp = date.today().strftime("%Y%m%d")
    dst = os.path.join(os.path.dirname(d), "备份_原始逐字稿_%s" % stamp, name)
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    if os.path.exists(dst):
        print("备份已存在，跳过（避免覆盖）: %s" % dst)
        return 0
    shutil.copytree(d, dst)
    n = len([f for f in os.listdir(dst) if f.endswith(MD)])
    print("已备份 %d 个 md 文件 → %s" % (n, dst))
    return 0


def cmd_apply(a):
    rules = json.load(open(a.rules, encoding="utf-8"))
    literal = rules.get("literal", [])          # [[old, new], ...]
    regex = rules.get("regex", [])              # [[pattern, repl], ...]
    review = rules.get("review", [])            # 只报告不替换
    d = a.dir
    log = {}
    for f in list_md(d):
        p = os.path.join(d, f)
        t = o = read(p)
        hits = []
        for old, new in literal:
            if old in t:
                n = t.count(old)
                t = t.replace(old, new)
                hits.append("%s→%s ×%d" % (old, new, n))
        for pat, rep in regex:
            t2, n = re.subn(pat, rep, t)
            if n:
                t = t2
                hits.append("%s → %s ×%d" % (pat[:24], rep[:24], n))
        if t != o:
            write(p, t)
            log[f] = hits
    print("应用规则：literal %d 条 / regex %d 条" % (len(literal), len(regex)))
    print("改动文件 %d 个" % len(log))
    for f, hits in sorted(log.items()):
        print("  %-30s %s" % (f[:30], "; ".join(hits)[:110]))
    if review:
        print("\n[待人工确认，未替换]")
        for item in review:
            print("  %s" % item)
    return 0


def cmd_repara(a):
    d = a.dir
    changed = []
    for f in list_md(d):
        p = os.path.join(d, f)
        t = read(p)
        if is_lyric(t):
            continue
        title, body = split_title_body(t)
        ps = paragraphs(body)
        if not ps:
            continue
        need = max(len(x) for x in ps) > a.mega or find_fragment_paragraphs(body)
        if not need:
            continue
        new_body = reparagraph(body, a.min, a.max)
        out = (title + "\n\n" if title else "") + new_body + "\n"
        if out != t:
            write(p, out)
            changed.append((f, len(ps), len(paragraphs(new_body))))
    print("重分段: %d 个文件" % len(changed))
    for f, a0, b0 in changed:
        print("  %-40s %d 段 → %d 段" % (f[:40], a0, b0))
    return 0


def cmd_qa(a):
    d = a.dir
    files = list_md(d)
    lens, issues, residue = [], [], Counter()
    for f in files:
        p = os.path.join(d, f)
        t = read(p)
        if is_lyric(t):
            continue
        lines = t.split("\n")
        if not (lines and lines[0].startswith("# ")):
            issues.append((f, "无 H1 标题"))
        if not t.endswith("\n"):
            issues.append((f, "结尾无换行"))
        if re.search(r"^\*\*标题：\*\*", t, re.M):
            issues.append((f, "残留重复标题行"))
        _, body = split_title_body(t)
        for g, ctx in find_word_split_periods(body):
            issues.append((f, "词中句号「%s」…%s…" % (g, ctx)))
        for n, head in find_mega_paragraphs(body, a.limit):
            issues.append((f, "超长段 %d 字: %s" % (n, head)))
        for i, head in find_weak_starts(body):
            issues.append((f, "第 %d 段弱开头: %s" % (i + 1, head)))
        ps = paragraphs(body)
        lens += [len(x) for x in ps]
        if a.terms:
            for term, expect in a.terms.items():
                c = t.count(term)
                if c and not expect:
                    residue[term] += c
    print("文件 %d 个" % len(files))
    if lens:
        print("段落 %d 个 | 平均 %.0f 字 | 中位数 %.0f | 最长 %d"
              % (len(lens), statistics.mean(lens), statistics.median(lens), max(lens)))
    print("问题 %d 处" % len(issues))
    for f, w in issues[:60]:
        print("  %-32s %s" % (f[:32], w))
    if residue:
        print("\n[残留疑似误转词]")
        for k, v in residue.most_common():
            print("  %s ×%d" % (k, v))
    return 0 if not issues else 0


def cmd_report(a):
    d = os.path.abspath(a.dir)
    b = os.path.abspath(a.backup)
    if not os.path.isdir(b):
        print("备份目录不存在: %s" % b)
        return 1
    new, old = set(list_md(d)), set(list_md(b))
    changed, same = [], 0
    for f in sorted(old & new):
        x, y = read(os.path.join(b, f)), read(os.path.join(d, f))
        if x != y:
            changed.append((f, len(x), len(y)))
        else:
            same += 1
    print("备份: %s" % b)
    print("可对比文件 %d | 有改动 %d | 无改动 %d" % (len(old & new), len(changed), same))
    if old - new:
        print("仅存在于备份（被改名/删除）: %s" % ", ".join(sorted(old - new)))
    if new - old:
        print("新增文件: %s" % ", ".join(sorted(new - old)))
    print("\n改动明细（前 30）:")
    for f, x, y in changed[:30]:
        print("  %-40s %d → %d 字" % (f[:40], x, y))
    return 0


def main():
    ap = argparse.ArgumentParser(description="逐字稿清洗工具箱")
    sub = ap.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("scan"); s.add_argument("dir"); s.add_argument("--json")
    s.set_defaults(func=cmd_scan)

    s = sub.add_parser("backup"); s.add_argument("dir"); s.set_defaults(func=cmd_backup)

    s = sub.add_parser("apply"); s.add_argument("dir")
    s.add_argument("--rules", required=True); s.set_defaults(func=cmd_apply)

    s = sub.add_parser("repara"); s.add_argument("dir")
    s.add_argument("--min", type=int, default=180)
    s.add_argument("--max", type=int, default=380)
    s.add_argument("--mega", type=int, default=1200)
    s.set_defaults(func=cmd_repara)

    s = sub.add_parser("qa"); s.add_argument("dir")
    s.add_argument("--limit", type=int, default=1200)
    s.add_argument("--terms", help="JSON 文件：{疑似残留词: 0}")
    s.set_defaults(func=cmd_qa)

    s = sub.add_parser("report"); s.add_argument("dir")
    s.add_argument("--backup", required=True); s.set_defaults(func=cmd_report)

    a = ap.parse_args()
    if getattr(a, "terms", None):
        a.terms = json.load(open(a.terms, encoding="utf-8"))
    return a.func(a)


if __name__ == "__main__":
    sys.exit(main())

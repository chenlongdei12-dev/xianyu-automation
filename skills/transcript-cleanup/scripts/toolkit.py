#!/usr/bin/env python3
"""逐字稿清洗工具箱（transcript-cleanup）。

子命令:
  scan    <dir>                  扫描分类：正常稿 / 歌词误转写 / 极短稿 / 无标题
  backup  <dir>                  备份到同级 备份_原始逐字稿_YYYYMMDD/
  apply   <dir> --rules R.json   应用替换规则（literal 或 regex），输出改动日志
  repara  <dir>                  碎片段合并 + 巨段重分段（目标 180~380 字/段）
  layout  <dir>                  版式统一：头部元信息块 + 标题标签空格 + 全量段落基线 + 粘连列表
  qa      <dir>                  质检：H1、元信息块、词中句号、超长段、弱开头、粘连列表、残留变体
  report  <dir> --backup B       与备份对比，输出改动文件统计

版式基线（layout 的目标形态，qa 按此检查）:
  # <标题>（标签前保证空格）
  （空行）
  > 发布时间：YYYY-MM-DD HH:MM   ← 无法确认时写「未知」并进存疑清单
  （空行）
  正文段落 180~380 字/段，段间空行

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
    """返回 (H1 行, 正文)。H1 之前的前导内容（如 HTML 注释说明块）并入正文头。"""
    lines = text.split("\n")
    for i, l in enumerate(lines):
        if l.startswith("# "):
            pre = "\n".join(x for x in lines[:i] if x.strip())
            rest = "\n".join(lines[i + 1:])
            if pre:
                return l, pre + "\n\n" + rest
            return l, rest
    return None, text


def paragraphs(body):
    return [p.strip() for p in body.split("\n\n") if p.strip()]


def is_lyric(text):
    return LYRIC_MARK in text or "语音识别结果" in text


# ---------- 版式基线 ----------
# 头部元信息块：> 发布时间：YYYY-MM-DD HH:MM
RE_META = re.compile(r"^>\s*发布时间[:：]\s*(.+)$", re.M)
RE_META_TIME = re.compile(r"(\d{4})[-/年.](\d{1,2})[-/月.](\d{1,2})日?\s*(\d{1,2}):(\d{2})")
# 粘连列表项：前字符是 CJK/字母/右括号/句末标点，数字. 后紧跟文字或空格+文字
RE_GLUE_ITEM = re.compile(
    r"(?<=[\u4e00-\u9fffA-Za-z）\]】」””：:。！？…])\s*(\d{1,2})\.\s*(?=[\u4e00-\u9fffA-Za-z])")


def extract_meta(body):
    """从正文中分离出 (剩余正文, 规范化时间串或 None)。

    兼容两种形态：规范的 > 引用块；粘连在正文里的（含日期时分粘死如 2026-08-1217:16）。
    """
    m = RE_META.search(body)
    if m:
        rest = (body[: m.start()] + body[m.end():]).strip()
        ts = m.group(1).strip()
        tm = RE_META_TIME.match(ts)
        if tm:
            y, mo, dd, hh, mi = tm.groups()
            tail = ts[tm.end():].strip()  # 时间后粘在同一行的正文，必须保留
            ts = "%s-%02d-%02d %02d:%02d" % (y, int(mo), int(dd), int(hh), int(mi))
            if tail:
                rest = (tail + "\n\n" + rest).strip()
        return rest, ts
    m = re.search(r"[<>]?\s*发布时间[:：]\s*", body)
    if m:
        tm = RE_META_TIME.match(body[m.end():].lstrip())
        if tm:
            y, mo, dd, hh, mi = tm.groups()
            ts = "%s-%02d-%02d %02d:%02d" % (y, int(mo), int(dd), int(hh), int(mi))
            end = m.end() + tm.end()
            rest = (body[: m.start()] + body[end:]).strip()
            return rest, ts
    return body.strip(), None


def norm_title_tags(title):
    """标题行内「正文#标签」之间保证一个空格：...很少#AICoding → ...很少 #AICoding"""
    return re.sub(r"(?<=[\u4e00-\u9fff\w！？。，、…）\]])#", " #", title)


def norm_glue_lists(body, min_glue=2):
    """粘连有序列表拆行：1.XXX2.XXX3.XXX 挤一行 → 每项独立成段。

    min_glue：全文件至少 N 个粘连点才认定是列表（N 个粘连点 = N+1 条）。
    必须在 repara 之后调用，否则拆出的短行会被重分段重新揉合。
    """
    cands = list(RE_GLUE_ITEM.finditer(body))
    if len(cands) < min_glue:
        return body, 0
    out, last = [], 0
    for m in cands:
        out.append(body[last:m.start()])
        out.append("\n\n%s. " % m.group(1))
        last = m.end()
    out.append(body[last:])
    text = "".join(out)
    # 条目格式统一：N.后补空格（首项常保留 1.XXX 原样）
    text = re.sub(r"^(\d{1,2})\.(?=[^\s\d])", r"\1. ", text, flags=re.M)
    # 简介截断符后粘正文：条目内「...」后若还有长文，从省略号处切开归正文
    def cut_intro(m):
        line, tail = m.group(1), m.group(2)
        return "%s...\n\n%s" % (line, tail.strip())
    text = re.sub(r"^(\d{1,2}\. [^\n]{1,60}?)\.\.\.([^\n]{10,})$", cut_intro, text, flags=re.M)
    return text, len(cands)


def has_meta_block(body):
    """检查正文头部是否有规范的元信息块（> 发布时间：…）。"""
    head = body.split("\n\n", 1)[0]
    return bool(RE_META.search(head))


# ---------- 重分段 ----------
def split_sentences(text):
    return [p.strip() for p in re.split(r"(?<=[。？！…])", text) if p.strip()]


def protect_list_items(body):
    """把已拆行的列表项换成占位符，防止 reparagraph 把它们揉回大段。"""
    holds = []

    def repl(m):
        holds.append(m.group(0))
        return "\x00%d\x00" % (len(holds) - 1)

    out = re.sub(r"^\d{1,2}\. .*$", repl, body, flags=re.M)
    return out, holds


def restore_list_items(body, holds):
    return re.sub(r"\x00(\d+)\x00", lambda m: holds[int(m.group(1))], body)


def reparagraph(body, min_len=180, max_len=380):
    protected, holds = protect_list_items(body)
    flat = re.sub(r"\s+", "", "".join(paragraphs(protected)))
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
    return restore_list_items("\n\n".join(final), holds)


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

    "哈哈",
    "天呐",
    "好的",
    "没事",
    "看吧",
    "最终",
    "是说",
    "显然",
    "不，",
    # 播客双人对谈应答词（2026-09-17 缘缘er 实测：X。嗯嗯，/X。对对，均合法）
    "嗯嗯", "对对", "嗯呃", "嗯啊", "嗯对", "对嗯", "吧对", "对呀",
    "是是", "诶呦", "能吧", "是，", "是",
    "不",
    # 口播强调停顿起头（2026-09-17 无用之用 实测：句号后接转折/总结/呼告是博主断句习惯）
    "相反", "同样", "记住", "反之", "况且", "用户", "需求", "到这",
    "结束", "没用", "二", "三", "四", "五",
    # 口播举例/总结/拟声起头（同上批次补充）
    "果然", "例如", "学习", "总结", "试想", "一听", "很快", "砰", "六", "九", "你坑", "一",
    # 口播逻辑连接词句首（2026-09-17 洪树实测：。第六，/。至此，/。再者，/。那么，/。因此，/。于是，/。去年，/。我呢，均为正常断句）
    "第六", "我呢", "至此", "再者", "那么", "因此", "于是", "去年", "接下来",
    # 口播呼告/感叹起头（2026-09-17 行者实测：。好啦，/。行吧。/。同学，/。朋友，/。孩子，/。哎呀，/。说说均为句号后另起呼语）
    "好啦", "行吧", "同学", "朋友", "孩子", "哎呀", "说说", "保留",
    # 句号后另起：感叹/转折/列举起头（2026-09-17 行者实测：。哎呦，/。不对，/。是啊，/。餐饮、/。芒格、/。八戒、/。有，/。爸服。）
    "哎呦", "不对", "是啊", "餐饮", "芒格", "八戒", "有", "爸服",
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


def find_glue_lists(body):
    """正文里的粘连有序列表：1.XXX2.XXX3.XXX 挤在一行。"""
    return len(re.findall(r"[^\n]{30,}\d{1,2}\.[^\s\n]", body))


def find_meta_issues(body):
    """头部元信息块问题：缺失 / 时间格式不规范。"""
    out = []
    head = body.split("\n\n", 1)[0]
    m = RE_META.search(head)
    if not m:
        out.append("缺元信息块")
    else:
        ts = m.group(1).strip()
        if not RE_META_TIME.fullmatch(ts) and ts != "未知":
            out.append("时间格式异常: %s" % ts)
    return out


def find_h1_overflow(title):
    """H1 疑似混入正文：过长且含句末标点（标题一般短于 60 字且不含整句）。

    只报告不自动切——切点无法可靠判定，进存疑清单人工处理。
    """
    if not title:
        return ""
    t = title[2:].strip()
    if len(t) > 60 and re.search(r"[。！？]", t):
        return "%s…（%d 字）" % (t[:50], len(t))
    return ""


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
        rest, meta = extract_meta(body)
        ps = paragraphs(rest)
        if not ps:
            continue
        need = (max(len(x) for x in ps) > a.max or find_fragment_paragraphs(rest))
        if not need:
            continue
        new_body = reparagraph(rest, a.min, a.max)
        out = (title + "\n\n" if title else "")
        if meta:
            out += "> 发布时间：%s\n\n" % meta
        out += new_body + "\n"
        if out != t:
            write(p, out)
            changed.append((f, len(ps), len(paragraphs(new_body))))
    print("重分段: %d 个文件" % len(changed))
    for f, a0, b0 in changed:
        print("  %-40s %d 段 → %d 段" % (f[:40], a0, b0))
    return 0


def cmd_layout(a):
    d = a.dir
    changed, meta_fixed, tag_fixed, list_fixed = [], [], [], []
    for f in list_md(d):
        p = os.path.join(d, f)
        t = read(p)
        if is_lyric(t):
            continue
        title, body = split_title_body(t)
        orig_title = title
        if title:
            title = title.strip()
            title = norm_title_tags(title)
            if title != orig_title:
                tag_fixed.append(f)
        rest, meta = extract_meta(body)
        # 全量段落基线（不再只盯 >1200 巨段），先做段落，后拆列表
        ps = paragraphs(rest)
        if ps and (max(len(x) for x in ps) > a.max or find_fragment_paragraphs(rest)
                   or (min(len(x) for x in ps) < 80 and len(ps) > 3)):
            rest = reparagraph(rest, a.min, a.max)
        # 粘连列表拆行（在 repara 之后，避免短行被重新揉合）
        rest2, n_glue = norm_glue_lists(rest, a.min_glue)
        if n_glue and rest2 != rest:
            rest = rest2
            list_fixed.append(f)
        meta_missing = meta is None
        if meta_missing:
            meta = "未知"
            meta_fixed.append(f)
        out = (title + "\n\n" if title else "")
        out += "> 发布时间：%s\n\n" % meta
        out += rest.strip() + "\n"
        if out != t:
            write(p, out)
            changed.append(f)
    print("版式统一: 改动 %d 个文件" % len(changed))
    if tag_fixed:
        print("  标题标签补空格: %d" % len(tag_fixed))
    if meta_fixed:
        print("  补「未知」元信息块: %d（需人工补真实时间 → 进存疑清单）" % len(meta_fixed))
    if list_fixed:
        print("  粘连列表拆行: %d" % len(list_fixed))
    for f in changed[:40]:
        print("  %s" % f[:70])
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
        else:
            h1 = find_h1_overflow(lines[0])
            if h1:
                issues.append((f, "H1 疑似混入正文: %s" % h1))
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
        n_glue = find_glue_lists(body)
        if n_glue:
            issues.append((f, "疑似粘连列表 ×%d" % n_glue))
        for w in find_meta_issues(body):
            issues.append((f, "元信息: %s" % w))
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
    s.set_defaults(func=cmd_repara)

    s = sub.add_parser("layout"); s.add_argument("dir")
    s.add_argument("--min", type=int, default=180)
    s.add_argument("--max", type=int, default=380)
    s.add_argument("--min-runs", dest="min_glue", type=int, default=2)
    s.set_defaults(func=cmd_layout)

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

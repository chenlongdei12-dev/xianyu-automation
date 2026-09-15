#!/usr/bin/env python3
"""逐字稿流水线环境自检（空白电脑必跑）。

用法: python3 doctor.py
输出: 每项依赖 OK / MISSING + 修复命令；全部通过返回 0，否则返回 1。

检查项：
  A. Python 版本 (>=3.9)
  B. playwright（biji-export 无头刷新用）
  C. PIL（封面合成用）
  D. pyobjc-Quartz（macOS 窗口定位用，仅截环节需要）
  E. zip 命令（加密打包用）
  F. node（ima 上传用）
  G. bdpan（百度网盘 CLI，可选——按需上传通道）
  H. quark-drive（夸克 CLI，可选）
  I. macOS 系统字体（封面红字用）
  J. 各平台登录态提示（无法代检，提示人工确认）
"""
import os
import shutil
import subprocess
import sys

PY_PKGS = [("playwright", "pip install playwright && playwright install chromium"),
           ("PIL", "pip install pillow"),
           ("Quartz", "pip install pyobjc-framework-Quartz  # 仅 macOS 截图环节需要")]

FONTS = ["/System/Library/Fonts/Hiragino Sans GB.ttc",
         "/System/Library/Fonts/STHeiti Medium.ttc",
         "/System/Library/Fonts/Supplemental/Songti.ttc"]

LOGIN_HINTS = [
    ("Get笔记", "~/.biji_exporter/browser_data_skill（首次需在有 GUI 的机器跑一次 biji_export.py login）"),
    ("ima 知识库", "~/.config/ima/client_id + api_key（https://ima.qq.com/agent-interface 申请）"),
    ("百度网盘", "bdpan 安装后 login（baidu-drive skill scripts/login.sh）"),
    ("夸克网盘", "quark-drive login（quarkclouddrive skill）"),
]

fails = []


def check(name, ok, fix=""):
    mark = "OK " if ok else "MISS"
    print(f"  [{mark}] {name}" + ("" if ok else f"  → 修复: {fix}"))
    if not ok:
        fails.append(name)


print("== A. Python (%s) ==" % sys.version.split()[0])
check("Python >= 3.9", sys.version_info >= (3, 9), "升级 Python")

print("== B-D. Python 包 ==")
for mod, fix in PY_PKGS:
    try:
        __import__(mod)
        check(mod, True)
    except ImportError:
        check(mod, False, fix)

print("== E. zip 命令（加密打包）==")
check("zip -e 加密支持", shutil.which("zip") is not None, "brew install zip / apt install zip")
if shutil.which("zip"):
    r = subprocess.run(["zip", "-h"], capture_output=True, text=True)
    check("zip 支持 -e 加密", "-e" in (r.stdout + r.stderr), "系统 zip 3.0+ 自带；否则装 p7zip")

print("== F. node（ima 上传脚本用）==")
check("node >= 16", shutil.which("node") is not None, "brew install node / nvm install 16")

print("== G-H. 网盘 CLI（按通道选装）==")
bdpan = shutil.which("bdpan") or os.path.exists(os.path.expanduser("~/.local/bin/bdpan"))
check("bdpan（百度通道）", bdpan, "~/.workbuddy/skills/baidu-drive/scripts/install.sh")
qk = os.path.exists(os.path.expanduser("~/.workbuddy/skills/quarkclouddrive/scripts/quark-drive.cjs"))
check("quark-drive（夸克通道）", qk, "quarkclouddrive skill: bash scripts/install.sh")

print("== I. macOS 字体（仅截环节）==")
if sys.platform == "darwin":
    check("中文字体（Hiragino/STHeiti/Songti 任一）",
          any(os.path.exists(f) for f in FONTS), "macOS 自带；Linux 需改 make_cover.py 字体表")
else:
    print("  [SKIP] 非 macOS：finder-shot-redhead 截图环节仅支持 macOS，跳过")

print("== J. 登录态（人工确认，无法自动检）==")
for name, hint in LOGIN_HINTS:
    print(f"  [NOTE] {name}: {hint}")

print()
if fails:
    print(f"✘ {len(fails)} 项缺失：{', '.join(fails)}")
    print("  按上面修复命令补齐后重跑 doctor.py")
    sys.exit(1)
print("✔ 环境就绪，可开始流水线（参考 transcript-pipeline/SKILL.md 五环编排）")

---
name: finder-shot-redhead
description: 截取 macOS 访达（Finder）中某个文件夹的窗口截图，并在顶部叠加两行红色大字（如「XX抖音全部公开内容逐字稿 / 网盘秒发」），用于交付物封面或宣传图。当用户要求「给访达截图」「加上红字」「文件列表截图做成封面」时使用。
agent_created: true
---

# 访达截图 + 红字抬头

## 用途

把某个文件夹的访达窗口截图，做成带两行红色大字的封面图（红字在上方白底抬头区，截图完整保留在下）。

## 用法

```bash
/Users/dei/.workbuddy/binaries/python/envs/default/bin/python \
  ~/.workbuddy/skills/finder-shot-redhead/scripts/make_cover.py \
  --folder "/绝对路径/目标文件夹" \
  --line1 "清华白也抖音全部公开内容逐字稿" \
  --line2 "网盘秒发" \
  --out "/绝对路径/输出.png"
```

未指定 `--out` 时，输出到文件夹同级目录，命名为 `<文件夹名>_红字封面.png`。
默认「红字直接叠加在访达截图上」，画布不变；若已有截图可加 `--skip-capture --shot <截图路径>` 跳过重新截图。

## 关键实现要点（踩过的坑）

1. **不要用 `screencapture -R x,y,w,h` 估算区域截图**。访达窗口位置是用户拖出来的，估算坐标会截到桌面，用户看不到内容。必须：
   - 先用 `open <folder>` 打开文件夹；
   - 再用 Quartz `CGWindowListCopyWindowInfo` 按 `kCGWindowOwnerName == 'Finder'` 找到目标窗口拿 `kCGWindowNumber`；
   - 最后 `screencapture -x -o -l<windowID>` 按窗口 ID 精确截取。
2. **AppleScript 读窗口不可靠**：本机未授予自动化/辅助功能权限，`tell application "Finder" to get bounds of front window` 会失败，也无法改窗口大小。别依赖它。
3. **中文字体**：`PingFang.ttc` 在本机不存在。可用 `/System/Library/Fonts/Hiragino Sans GB.ttc`（index=2 为 W6 粗体）或 `STHeiti Medium.ttc`（index=1 为 Heiti SC Medium）。
4. **默认把红字直接压在截图本身上**（`--mode overlay`，画布尺寸必须与截图完全一致，不做扩展、不加白底抬头带——观自明确要求过）。两行**同字号 46px**（观自要求大小一致），行间距 42px（要留得开，不要太挤），整体垂直居中略下移 24px 避开顶部工具栏。红字用白色描边（stroke_width 4）保证压在文件列表上依然清晰。
   `--mode band` 是备选（上方加白底抬头），仅在用户明确要求时才用。
5. 依赖：`pillow` + `pyobjc-framework-Quartz`，装在
   `/Users/dei/.workbuddy/binaries/python/envs/default`。

## 自检

生成后用 Read 工具看图，确认红字内容、位置正常，且截图确实是目标文件夹（可用 OCR 反查文件名）。

---
name: biji-export
description: Get笔记（biji.com）订阅博主逐字稿批量导出。列出知识库、找博主、增量导出 Markdown 逐字稿、断点续传、指定输出目录。还原自用户自建的 DouClaw 工具。
triggers:
  - Get笔记导出
  - biji逐字稿
  - biji导出
  - 笔记博主导出
  - 订阅博主导出
  - 逐字稿导出
  - DouClaw
---

# biji-export — Get笔记博主逐字稿导出

把 Get笔记（biji.com）订阅的博主文章逐字稿导出为本地 Markdown，增量续传。源自用户自建工具 DouClaw 的 skill 化重构，2026-09-16 实测通过。

## 环境事实（直接用，不要重新探索）

- **脚本**：`~/.workbuddy/skills/biji-export/scripts/biji_export.py`（单文件 CLI，5 个子命令）
- **Python**：`~/.workbuddy/binaries/python/envs/default/bin/python3`（无则用系统 `python3`；需 playwright：`pip install playwright && playwright install chromium`）
- **凭据缓存**：`~/.biji_exporter/skill_credentials.json`（token + csrf）
- **登录态目录**：`~/.biji_exporter/browser_data_skill`（headless 自动刷新用）
- **浏览器**：复用 DouClaw 的 chromium（`~/Library/Application Support/DouClaw/playwright-browsers`），不要重新下载
- **默认输出**：`~/DouClaw/Get笔记博主知识库/{博主名}_{follow_id}/`
- **API 域**：`knowledge-api.trytalks.com`，响应包裹为 `{h:…, c:{…}}`（数据在 c）
- **token 特性**：JWT 有效期仅 **30 分钟**。CLI 已内置自动无头刷新（凭据过期时自动起 headless 浏览器续期，用户无感）；仅当登录态本身失效（如改密码）才需人工 login
- **代理**：报代理错误时提醒用户关 Clash/Surge，或设 `BIJI_USE_SYSTEM_PROXY=1`

## 命令速查（完整命令前缀：cd ~/.workbuddy/skills/biji-export/scripts && 上述 python3 biji_export.py）

```bash
# 列知识库 → 返回 {alias, name}
... biji_export.py topics

# 列博主（含 follow_id、笔记数、可直接导出的 url）→ 用户说"提取胡说老王"时遍历找名字
... biji_export.py follows <topic_alias>

# 查状态：已导出/未导出篇数、续传建议
... biji_export.py status "<url>"

# 导出（增量，自动跳过已导出）
... biji_export.py export "<url>" [--start-date 2026-09-01] [--end-date ...] [--max-items N]

# 指定目录（根目录模式，自动建 博主名_子目录）
... biji_export.py export "<url>" -o ~/目标目录 --output-is-base

# 预览不落盘
... biji_export.py export "<url>" --dry-run
```

所有命令输出单行 JSON（`--pretty` 美化）：`ok / count / items / exported / skipped_existing / unexported_count / output_dir`。

## 典型编排（agent 直接照做）

用户："帮我导出胡说老王最近的逐字稿"

1. `topics` 拿知识库列表
2. 逐个 `follows <alias>` 找到"胡说老王" → 记住它的 url
3. `status "<url>"` 看导出状态
4. `export "<url>"`（或带 `--start-date` 从断点补）
5. 汇报：新增几篇、目录在哪

## 自动化（WorkBuddy 定时任务）

prompt 模板：
> 用 biji-export skill：对 <博主URL> 跑 status，若有未导出篇目则 export 增量补齐，输出本次新增篇数与目录。token 会自动刷新，无需人工干预。

适合每天/每周跑。198 篇全量约 3-5 分钟（每篇一次 detail 请求）。

## 文件格式与增量机制

- 每篇：`{序号:03d}_{post_id}_{标题}.md`，内容含标题 + 发布时间 + 逐字稿正文
- 增量识别：按文件名中段 post_id 精确匹配，重复运行零成本跳过
- `.biji_export_meta.json`：记录 URL 与更新时间

## 边界与故障排查

1. **403/LoginRequired** → CLI 已自动处理（无头刷新）；若刷新也失败 → 需要用户在场跑 `login`
2. **登录窗口/浏览器被杀** → login 需要人在场，自动化里只跑 status/export
3. 接口无时间字段时自动忽略日期筛选（导全部）——这是平台行为，非 bug
4. 只导用户自己订阅的内容
5. 私有 API 无文档：若 topics/follows 突然全挂，是平台改版，需抓包校准（参考脚本内 API 路径）

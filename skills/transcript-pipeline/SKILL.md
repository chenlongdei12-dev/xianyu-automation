---
name: transcript-pipeline
description: 抖音博主逐字稿一条龙流水线总编排：导出（Get笔记）→ 清洗校验（错别字/格式/分段）→ 封面截图（访达截图+红字）→ 三通道上传（ima 知识库 + 百度网盘 + 夸克网盘永久分享）→ 链接汇总反馈。当用户要求「跑一遍逐字稿流程」「一条龙处理某博主」「批量做博主逐字稿交付」时使用。单阶段执行时直接调用对应子 skill，不必走本编排。
agent_created: true
---

# 逐字稿流水线（总编排 v2）

把五个环节串成一条可断点续跑的流水线。**大循环套小循环**：
外层 = 多个博主（一个博主一轮）；内层 = 单个博主的五个环节，每环节幂等、可单独重跑。

## 五环与对应子 skill

| 序 | 环节 | 子 skill / 工具 | 输入 → 输出 |
|---|---|---|---|
| 1 | **导** | `biji-export`（登录态 `~/.biji_exporter/browser_data_skill`，token 自动无头刷新）；用户直接给文件时跳过 | 博主名 → `<工作根目录>/<博主名>/*.md` |
| 2 | **清**（校验） | `transcript-cleanup`（六步 + QA） | 逐字稿目录 → 清洗后同目录 + 备份 + 校验报告 |
| 3 | **截** | `finder-shot-redhead` | 清洗后目录 → `<博主名>_红字封面.png`（访达截图 + 两行红字） |
| 4 | **传**（三通道并行交付） | ① `ima-skill`（knowledge-base 模块）② `baidu-drive`（bdpan CLI）③ `quarkclouddrive`（quark-drive CLI） | 交付目录 → ima 知识库条目 + 两条永久分享链接 |
| 5 | **报** | 本编排自带（`state.py links`） | 状态文件 → 汇总三条链接反馈给用户 |

环节之间只通过**文件系统 + 状态文件**传递，不靠记忆：每环开始前先检查上一环的产物是否存在且通过质检，不通过就退回上一环，不要带着脏数据往下跑。

## 状态文件（断点续跑的关键）

**跨机器适配**：`$PY` 一律用「WorkBuddy 托管 python 优先、`python3` 回退」：
```bash
PY=$(ls ~/.workbuddy/binaries/python/envs/default/bin/python 2>/dev/null || command -v python3)
S=~/.workbuddy/skills/transcript-pipeline/scripts/state.py

$PY $S init   --root "<工作根目录>" --blogger 清华白也
$PY $S status --root "<工作根目录>"           # 总览：每博主进度 + 已有链接
$PY $S next   --root "<工作根目录>" --blogger 清华白也    # 下一环节 + 执行命令提示
$PY $S mark   --root "<工作根目录>" --blogger 清华白也 --stage upload_baidu --done --note "永久" --link "https://pan.baidu.com/s/xxx"
$PY $S links  --root "<工作根目录>"           # 第 5 环「报」：输出三通道链接
```

阶段枚举：`export / clean / shot / upload_ima / upload_baidu / upload_quark`（v2 起上传拆三通道，各自独立 done + link；旧状态文件读取时自动迁移）。
状态落在 `<工作根目录>/_pipeline_state.json`。每环完成**必须** `mark --done`，网盘通道记得 `--link`。

## 每个博主的执行顺序

### 1. 导
调 `biji-export`：`topics` → `follows <alias>` 找博主 → `status "<url>"` → `export "<url>" -o <工作根目录> --output-is-base`。
产物目录命名 `<博主名>`。用户直接给文件夹时跳过本环。

### 2. 清（校验）
走 `transcript-cleanup` 的六步（backup → scan → 修错 → 分段 → 格式 → QA）。
**QA 必须跑到「0 问题或每条都有解释」**，否则不许进入截图/上传（截图和上传会把脏内容固化进交付物）。

### 3. 截
```bash
$PY ~/.workbuddy/skills/finder-shot-redhead/scripts/make_cover.py \
  --folder "<清洗后目录>" \
  --line1 "<博主名>抖音全部公开内容逐字稿" \
  --line2 "网盘秒发" \
  --out "<工作根目录>/<博主名>_红字封面.png"
```
两行红字同字号（46px）、直接压在访达截图本体上、红色 (214,25,25)。生成后必须用 Read 看图自检。

### 4. 传（三通道，顺序执行，任一通道失败不阻断其他通道）

**⚠️ 网盘交付口径（2026-09-16 观自二次确认）：只传一个加密 zip（仅含 md 逐字稿），不上传封面、不上传 json、不上传散文件。**

三个原因：
1. biji-export 会在目录留 `.biji_export_meta.json` 等工具元数据，整目录上传必被带上；
2. 百度对明文 md 做内容扫描——**散文件和明文 zip 都会被判「部分文件违规，已被过滤」（均实测踩坑，明文 zip 会在数小时内被补扫补判）**；
3. 封面/散文件非用户要的交付物。

```bash
# 4.0a 打包加密 zip（在博主目录内执行，天然排除工具文件；密码统一 dora2026）
cd "<工作根目录>/<博主名>" && /usr/bin/zip -q -r -e -P "dora2026" \
  "/tmp/<博主名>_抖音全部公开内容逐字稿_<N>篇.zip" *.md
# 注：系统 zip 3.0 支持 -e 加密；解压密码 dora2026
```
- **必做验证**：百度分享后用「提取码流程 curl + grep risk-label」检查（=0 才算过）；夸克用 `share-detail` 查 `partial_violation=false`。加密 zip 当下干净也可能被补判，有 risk 标记就重打包重传。

ima 侧仍用合并单文件（结构化内容，ima 要解析）：
```bash
$PY ~/.workbuddy/skills/transcript-pipeline/scripts/merge_for_ima.py \
  --folder "<工作根目录>/<博主名>" \
  --out "<工作根目录>/_ima_upload/<博主名>.md"
```

**4.1 ima 知识库**（走 `ima-skill` knowledge-base 模块，media_type=7 Markdown，上限 10MB）：
- ⚠️ **ima OpenAPI 没有创建知识库接口**。目标库二选一：用户点名了库 → `search_knowledge_base` 按名搜 ID；未点名 → 默认「观自的知识库」（个人库）并在汇报时说明库名。
- 上传走标准五步：`preflight-check.cjs` → `check_repeated_names`（重名 → 追加时间戳，IMA 不支持替换）→ `create_media` → `cos-upload.cjs`（大文件加 `--timeout 300000`）→ `add_knowledge`（title 必须等于文件名）。
- 完成后 `mark --stage upload_ima --done --note "已入库「库名」"`（无分享链接，note 记库名）。

**4.2 百度网盘**（`baidu-drive`，路径限 `/apps/bdpan/`）：
```bash
export PATH="$HOME/.local/bin:$PATH"   # bdpan 不在默认 PATH
bdpan upload "/tmp/<博主名>_抖音全部公开内容逐字稿_<N>篇.zip" "博主逐字稿/<博主名>/<同name>.zip" \
  --agentname workbuddy --session-input '<用户原话>' --session-id '<ts-6位随机>'
bdpan share "博主逐字稿/<博主名>/<zip名>.zip" --period 0 …同公共参数   # 对加密 zip 分享，0 = 永久
```
- 交付口径：**仅一个加密 zip**（不含封面/png/json）。⚠️ 明文 zip 会被百度数小时内补扫补判违规——必须 `-e -P` 加密。
- 分享后**必做验证**：curl 走提取码流程后 `grep risk-label`，=0 才向用户交付。
- 链接来自 share 返回（提取码 + 解压密码 dora2026 一并告知）；`mark --stage upload_baidu --done --link '<链接>'`。
- 提醒用户：永久链接无法自动过期，注意文件安全。

**4.3 夸克网盘**（`quarkclouddrive`，先 `bash scripts/install.sh` 环境检查）：
```bash
cd ~/.workbuddy/skills/quarkclouddrive
# 只传加密 zip 一个文件
node scripts/quark-drive.cjs upload "/tmp/<博主名>_抖音全部公开内容逐字稿_<N>篇.zip" \
  --session-input '<用户原话>' --session-id '<ts-6位随机>'
# 从 result 行取 data.fids[0] → 永久公开分享
node scripts/quark-drive.cjs share <zip_fid> --title "<博主名>抖音全部公开内容逐字稿" \
  --url-type 1 --expired-type 1 …同公共参数
# 分享后验证：share-detail 查 partial_violation=false 且 file_num=1
```
- ⚠️ 夸克 CLI **无删除命令**：传错了只能留在盘里，上传前先确认只传 zip 一个文件。
- `mark --stage upload_quark --done --link '<share_url>'`。

### 5. 报（链接汇总反馈）
```bash
$PY $S links --root "<工作根目录>"
```
把输出整理成三行反馈给用户：ima 库名（无链接）+ 百度永久链接 + 夸克永久链接。
**对外动作红线**：链接生成后先把三条链接一并列给用户确认，再宣告完成；任何通道失败要在汇报中明确说清缺哪条、为什么。

## 批量（外层大循环）

多个博主时，逐个博主跑完五环再换下一个——不要先把所有博主都「导」完再统一「清」，
因为清洗阶段的词典是靠单篇上下文定的，混批会互相污染判断。
每个博主跑完在状态文件里留档；中断后 `status` 看进度，`next` 从断点继续。

## 环境事实（直接用，不要重新探索）

### 新机器部署（三步）

```bash
# 1. 装 skill：把 4 个 skill 目录放进 agent 的 skills 目录（如 ~/.workbuddy/skills/）
# 2. 环境自检（缺什么会给出修复命令；可选通道缺失不阻断其他环节）
python3 ~/.workbuddy/skills/transcript-pipeline/scripts/doctor.py
# 3. 登录态（人工，一次性）：
#    Get笔记: biji_export.py login（需 GUI 机器跑一次，之后 token 自动无头刷新）
#    ima:     ~/.config/ima/{client_id,api_key}
#    百度:    bdpan login（baidu-drive skill）
#    夸克:    quark-drive login（quarkclouddrive skill）
```

依赖的**外部 skill**（上传环节，缺了对应通道不可用但流水线其他环照跑）：
- `baidu-drive`（bdpan CLI 安装/登录见其 SKILL.md）
- `quarkclouddrive`（quark-drive CLI，install.sh）
- `ima-skill`（官方 ima OpenAPI 封装）

平台限制：`finder-shot-redhead` 截图环节仅 macOS（Quartz 窗口 API + 系统字体）；Linux 机器跳过截环节或自行改字体表。

- **ima 凭据**：`~/.config/ima/client_id` + `api_key`（已配置）；CLI `~/.workbuddy/skills/ima-skill/ima_api.cjs`
- **⚠️ COS 凭据传参铁律（2026-09-16 姜Dora首跑踩坑）**：`create_media` 返回的 cos_credential 必须落盘（如 `/tmp/cos_cred.json`）再用 python/subprocess 数组传参调 `cos-upload.cjs`。**严禁把 secret_id/token 复制进 shell 命令行**——长 token 会被截断，报 403 InvalidAccessKeyId，且极难排查。
- **bdpan**：v3.8.7 在 `~/.local/bin`（不在默认 PATH）；登录态至 2026-10-15；操作范围限 `/apps/bdpan/`
- **quark-drive**：`~/.workbuddy/skills/quarkclouddrive/scripts/quark-drive.cjs`；已授权（token 在 `workbuddy/config.json`）；每次调用前跑一次 `scripts/install.sh`
- **biji 登录态**：`~/.biji_exporter/browser_data_skill`（headless 刷新用）；凭据 `~/.biji_exporter/skill_credentials.json`（JWT 30 分钟，CLI 自动续）
- **默认工作根目录**（本机）：`~/Desktop/优质博主文案/dontbesilent 相似博主/`；其他机器由用户指定或默认 `~/博主逐字稿/`
- **biji 导出目录名**：`<博主名>_<follow_id>`，导出后重命名为 `<博主名>` 再进流水线

## 红线

- **不跳环**。尤其不许跳过清洗 QA 直接出封面/上传。
- 清洗阶段的所有判断规则以 `transcript-cleanup` 为准，本 skill 不另立标准。
- 三通道上传**互不阻断**：ima 失败不影响网盘，百度失败不影响夸克；失败通道如实汇报，不许假装全成。
- 上传前确认目标目录和文件清单，不要整盘乱传。
- 每个博主的产物带博主名，避免多博主混在同一目录。
- ima 上传必须过四道安全门（类型检查/命名一致/重名检查/COS 退出码），详见 ima-skill knowledge-base SKILL.md。
- 百度/夸克 CLI 的公共参数（`--session-input`/`--session-id`，百度另有 `--agentname`）每条命令都要带。

## 已知可改进点（下次迭代）

- ima 若要「每博主一个知识库」，目前只能在 ima 客户端手动建库后再由 API 上传——OpenAPI 无建库接口。
- 尚未做跨博主的**术语一致性校验**（同一个人在多个博主稿里出现时写法应统一）。
- 百度上传目录名如需与夸克路径一致（`博主逐字稿/<博主名>`），夸克侧目前用 CLI 默认目录，如需统一要显式 `create-folder` 后传 `--parent-fid`。

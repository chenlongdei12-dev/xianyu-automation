# 闲鱼自动化 — 博主逐字稿流水线 Skill 集

> 从 Get笔记导出 → 清洗校验 → 封面截图 → 三通道上传（ima / 百度 / 夸克）→ 链接汇报
> 一条可断点续跑的生产流水线，2026-09-16 完成全流程实测（姜Dora在此 107 篇）。

## 流水线五环

```
导 ──→ 清 ──→ 截 ──→ 传 ──────────→ 报
biji   cleanup  cover   ima/百度/夸克   links
export  六步QA  红字封面  三通道互不阻断  汇总反馈
```

| 环节 | Skill | 说明 |
|---|---|---|
| 导 | `biji-export` | Get笔记（biji.com）订阅博主逐字稿批量导出，增量续传，token 自动无头刷新 |
| 清 | `transcript-cleanup` | 只修错不润色：错别字/术语统一/格式规范/重分段/QA 报告 |
| 截 | `finder-shot-redhead` | 访达截图 + 两行红字封面（46px 同字号直压截图本体） |
| 传 | `transcript-pipeline` | 总编排：状态机断点续跑 + ima 合并上传 + 网盘加密 zip 交付 |
| 报 | `transcript-pipeline` | `state.py links` 一条命令输出三通道链接 |

## 快速开始（空白电脑三步部署）

```bash
# 1. 安装：把 skills/ 下四个目录复制到你的 agent skills 目录
cp -r skills/* ~/.workbuddy/skills/   # 或你的 Claude Code / OpenClaw skills 目录

# 2. 环境自检：缺什么给什么修复命令（python 包 / zip / node / 网盘 CLI / 字体 / 登录态清单）
python3 skills/transcript-pipeline/scripts/doctor.py

# 3. 各平台登录（人工，一次性）：
#    Get笔记  → biji_export.py login（需 GUI 机器跑一次，之后 token 自动无头刷新）
#    ima      → ~/.config/ima/{client_id,api_key}（ima.qq.com/agent-interface 申请）
#    百度网盘 → bdpan login（需 baidu-drive skill）
#    夸克网盘 → quark-drive login（需 quarkclouddrive skill）
```

### 依赖的配套 skill（上传环节）

| 通道 | 配套 skill | 缺失影响 |
|---|---|---|
| ima 知识库 | `ima-skill`（官方 OpenAPI 封装） | ima 通道不可用 |
| 百度网盘 | `baidu-drive`（bdpan CLI） | 百度通道不可用 |
| 夸克网盘 | `quarkclouddrive`（quark-drive CLI） | 夸克通道不可用 |

三通道互不阻断：缺哪个就少传哪个，其余环节照跑。
`finder-shot-redhead` 截图环节仅 macOS（Quartz 窗口 API）；Linux 跳过截环节或改字体表。

### 日常使用

```bash
# 初始化状态（工作根目录放博主逐字稿文件夹）
python3 skills/transcript-pipeline/scripts/state.py init \
  --root "<你的工作根目录>" --blogger "<博主名>"

# 每步完成后标记，支持断点续跑
python3 skills/transcript-pipeline/scripts/state.py mark \
  --root "<根目录>" --blogger "<博主名>" --stage clean --done

# 看下一步做什么 / 汇总链接
python3 skills/transcript-pipeline/scripts/state.py next   --root "<根目录>" --blogger "<博主名>"
python3 skills/transcript-pipeline/scripts/state.py links  --root "<根目录>"
```

## 关键铁律（实测踩坑沉淀）

1. **网盘交付只传一个加密 zip**（`zip -e -P` 加密码，仅含 md 逐字稿）：
   - 百度对散文件 md **和明文 zip** 都会内容扫描判「部分文件违规，已被过滤」——明文 zip 也会在数小时内被补扫补判
   - 不上传封面 png、不上传导出工具的 `.biji_export_meta.json`
2. **分享后必验证**：百度走提取码流程后检查 `risk-label`（必须 0）；夸克 `share-detail` 查 `partial_violation=false`
3. **清洗只修错不润色**：口播重复/语气词是真实口语，保留；判断不了的进存疑清单
4. **ima 上传必须合并单文件**（碎 md 合并成一个合集再传，COS 凭据用文件传参防截断）
5. **三通道互不阻断**：任一失败不影响其他，汇报时如实说明

## 依赖环境

- Python 3.13（playwright）
- Node.js（ima 上传用）
- 各平台登录态：Get笔记 / ima / 百度网盘 / 夸克网盘
- 详见各 skill 的 SKILL.md「环境事实」

## 实测记录

- 2026-09-16 姜Dora在此：107 篇全流程 6/6 通过，97 篇清洗（博主名 6 种误转写统一等 300+ 处修正）
- 状态机六阶段：`export / clean / shot / upload_ima / upload_baidu / upload_quark`

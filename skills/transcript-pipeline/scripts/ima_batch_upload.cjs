#!/usr/bin/env node
'use strict';
/**
 * ima 知识库批量上传（逐篇模式）
 *
 * 用法:
 *   node ima_batch_upload.cjs --folder "<博主逐字稿目录>" \
 *     [--kb-name "<知识库名>" ] [--kb-id "<已有库ID>"] [--description "..."]
 *
 * 行为:
 *   1. 未给 --kb-id 时：先按 --kb-name（默认 "<目录名>逐字稿"）search，
 *      已存在 → 直接用；不存在 → create_knowledge_base(KBT_MINE_KB)
 *   2. 目录内全部 .md 逐篇走五步: preflight → check_repeated_names(批量) →
 *      create_media → cos-upload → add_knowledge
 *   3. 重名（is_repeated=true）自动追加 _YYYYMMDDHHmmss 后缀保留两者
 *   4. 断点续传：--state 记录已上传文件名（默认 <folder>/_ima_batch_state.json），
 *      重跑自动跳过已完成项
 *
 * 凭据: ~/.config/ima/{client_id,api_key}（与 ima-skill 相同）
 */
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { execFileSync } = require('node:child_process');

const SKILL_DIR = path.resolve(__dirname, '..', '..', 'ima-skill');
const IMA_API = path.join(SKILL_DIR, 'ima_api.cjs');
const PREFLIGHT = path.join(SKILL_DIR, 'knowledge-base', 'scripts', 'preflight-check.cjs');
const COS_UPLOAD = path.join(SKILL_DIR, 'knowledge-base', 'scripts', 'cos-upload.cjs');

function parseArgs(argv) {
  const a = {};
  for (let i = 2; i < argv.length; i += 2) {
    const k = argv[i].replace(/^--/, '');
    if (!argv[i + 1]) { console.error(`Missing value for --${k}`); process.exit(1); }
    a[k] = argv[i + 1];
  }
  return a;
}

function imaApi(ep, body) {
  const clientId = fs.readFileSync(path.join(os.homedir(), '.config/ima/client_id'), 'utf8').trim();
  const apiKey = fs.readFileSync(path.join(os.homedir(), '.config/ima/api_key'), 'utf8').trim();
  const opts = JSON.stringify({ clientId, apiKey });
  const out = execFileSync('node', [IMA_API, ep, JSON.stringify(body), opts],
                           { encoding: 'utf8', maxBuffer: 32 * 1024 * 1024 });
  const j = JSON.parse(out);
  if (j.code !== 0) throw new Error(`${ep} 失败: code=${j.code} ${j.msg}`);
  return j.data;
}

function pad2(n) { return String(n).padStart(2, '0'); }
function stamp() {
  const d = new Date();
  return `${d.getFullYear()}${pad2(d.getMonth() + 1)}${pad2(d.getDate())}` +
         `${pad2(d.getHours())}${pad2(d.getMinutes())}${pad2(d.getSeconds())}`;
}

// ---- main ----
const args = parseArgs(process.argv);
const folder = path.resolve(args.folder);
if (!fs.statSync(folder).isDirectory()) { console.error(`目录不存在: ${folder}`); process.exit(1); }
const statePath = args.state || path.join(folder, '_ima_batch_state.json');
const state = fs.existsSync(statePath) ? JSON.parse(fs.readFileSync(statePath, 'utf8')) : { uploaded: [] };
const done = new Set(state.uploaded);

// 1. 定位或创建知识库
let kbId = args['kb-id'] || null;
let kbName = args['kb-name'] || `${path.basename(folder)}逐字稿`;
if (!kbId) {
  const found = imaApi('openapi/wiki/v1/search_knowledge_base', { query: kbName, cursor: '', limit: 20 });
  const hit = (found.info_list || []).find(k => k.kb_name === kbName);
  if (hit) { kbId = hit.kb_id; console.log(`知识库已存在: 「${kbName}」`); }
  else {
    const created = imaApi('openapi/wiki/v1/create_knowledge_base',
      { name: kbName, description: args.description || `${kbName}（transcript-pipeline 自动创建）`, type: 'KBT_SHARED_KB' });
    kbId = created.id;
    console.log(`已新建共享知识库: 「${kbName}」 id=${kbId.slice(0, 12)}…`);
  }
} else {
  console.log(`使用指定知识库 id=${kbId.slice(0, 12)}…`);
}

// 2. 收集待上传 md
const mds = fs.readdirSync(folder).filter(f => f.endsWith('.md')).sort();
const todo = mds.filter(f => !done.has(f));
console.log(`共 ${mds.length} 篇，已传 ${done.size}，本次 ${todo.length}`);

// 3. 批量重名预检（一次 API 查全部）
let repeated = new Set();
if (todo.length) {
  const params = todo.map(f => ({ name: f, media_type: 7 }));
  try {
    const chk = imaApi('openapi/wiki/v1/check_repeated_names', { params, knowledge_base_id: kbId });
    for (const r of (chk.results || [])) if (r.is_repeated) repeated.add(r.name);
    if (repeated.size) console.log(`重名 ${repeated.size} 个 → 将追加时间戳保留两者`);
  } catch (e) { console.warn(`重名预检失败（不阻断）: ${e.message}`); }
}

// 4. 逐篇五步上传
let ok = 0, fail = 0;
for (const f of todo) {
  const p = path.join(folder, f);
  try {
    const pre = JSON.parse(execFileSync('node', [PREFLIGHT, '--file', p], { encoding: 'utf8' }));
    if (!pre.pass) throw new Error(`preflight: ${pre.reason || '未通过'}`);
    let fileName = f;
    if (repeated.has(f)) {
      fileName = f.replace(/\.md$/, `_${stamp()}.md`);
      fs.copyFileSync(p, path.join('/tmp', fileName));
    }
    const filePath = repeated.has(f) ? path.join('/tmp', fileName) : p;
    const size = fs.statSync(filePath).size;
    const cm = imaApi('openapi/wiki/v1/create_media', {
      file_name: fileName, file_size: size,
      content_type: 'text/markdown', knowledge_base_id: kbId, file_ext: 'md',
    });
    execFileSync('node', [COS_UPLOAD,
      '--file', filePath,
      '--secret-id', cm.cos_credential.secret_id,
      '--secret-key', cm.cos_credential.secret_key,
      '--token', cm.cos_credential.token,
      '--bucket', cm.cos_credential.bucket_name,
      '--region', cm.cos_credential.region,
      '--cos-key', cm.cos_credential.cos_key,
      '--content-type', 'text/markdown',
      '--start-time', cm.cos_credential.start_time,
      '--expired-time', cm.cos_credential.expired_time,
      '--timeout', '300000',
    ], { encoding: 'utf8', stdio: ['ignore', 'ignore', 'pipe'] });
    imaApi('openapi/wiki/v1/add_knowledge', {
      media_type: 7, media_id: cm.media_id, title: fileName, knowledge_base_id: kbId,
      file_info: { cos_key: cm.cos_credential.cos_key, file_size: size, file_name: fileName },
    });
    done.add(f); ok++;
    state.uploaded = [...done];
    fs.writeFileSync(statePath, JSON.stringify(state, null, 1));
    if (ok % 10 === 0 || ok === todo.length) console.log(`  进度 ${ok}/${todo.length}`);
  } catch (e) {
    fail++;
    console.error(`  ✘ ${f.slice(0, 40)}: ${e.message.slice(0, 120)}`);
  }
}

console.log(`\n完成: 成功 ${ok} / 失败 ${fail}（重跑自动续传）`);
console.log(`知识库: 「${kbName}」（共享库）`);
console.log(`知识库ID: ${kbId}`);
console.log(`入口: ima 客户端 → 知识库 → 「${kbName}」`);
console.log(`⚠️ 分享链接: ima OpenAPI 无知识库分享端点（实测 create/get/update 均不含 share_url）。`);
console.log(`   要把库分享给别人：ima 客户端打开该库 → 右上角「分享/邀请」生成链接，一次性手动操作。`);
console.log(`状态文件: ${statePath}`);
process.exit(fail ? 1 : 0);

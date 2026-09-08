/** Local recording desk: genuine WebUI + Runtime, four synthetic OneBot members. */
import { readFileSync, writeFileSync, mkdirSync } from 'node:fs'
import { resolve } from 'node:path'
import { spawn, execFileSync } from 'node:child_process'
import { createServer } from 'node:http'
import { WebSocket } from 'ws'

const root = resolve(import.meta.dirname, '../../..')
const state =
  process.env.DUDUDA_RECORDING_STATE ||
  resolve(root, '../dududa-recording-state')
const web = 'http://127.0.0.1:5174',
  desk = 'http://127.0.0.1:8786'
const ip = execFileSync(
  'docker',
  [
    'inspect',
    '-f',
    '{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}',
    'dududa-recording-astrbot',
  ],
  { encoding: 'utf8' },
).trim()
const api =
  'http://127.0.0.1:6186/api/v1/plugins/extensions/astrbot_plugin_dududa_core/runtime'
const key = () =>
  readFileSync(resolve(state, 'secrets/astrbot_plugin_api_key'), 'utf8').trim()
const scope = {
  accountId: 'qq-1000000001',
  conversationId: 'qq-1000000001:group:2000000001',
}
const fixture = JSON.parse(
  readFileSync(
    resolve(root, 'tests/fixtures/recording/math-analysis-discussion.json'),
    'utf8',
  ),
)
const cases = JSON.parse(
  readFileSync(
    resolve(root, 'tests/fixtures/recording/manual-capability-cases.json'),
    'utf8',
  ),
).cases
const env = {
  ...process.env,
  DUDUDA_WEB_INTERNAL_PORT: '5174',
  DUDUDA_WEB_BIND: '127.0.0.1',
  DUDUDA_WEB_PUBLIC_ORIGIN: '',
  DUDUDA_WEB_PUBLIC_DIR: resolve(root, 'apps/web/dist'),
  DUDUDA_ONEBOT_TOKEN_FILE: resolve(state, 'secrets/onebot_access_token'),
  DUDUDA_ASTRBOT_PLUGIN_API_URL: 'http://127.0.0.1:6186/api/v1',
  DUDUDA_ASTRBOT_PLUGIN_API_KEY_FILE: resolve(
    state,
    'secrets/astrbot_plugin_api_key',
  ),
  DUDUDA_AGENT_POLICY_PATH: resolve(state, 'agent/agent-policies.json'),
  DUDUDA_API_KEY_STORE_PATH: resolve(state, 'api-keys/api-keys.json'),
  DUDUDA_MCP_CONSOLE_URL: `http://${ip}:8090`,
}
// Same-origin reset clears only this separate recording WebUI's browser storage.
writeFileSync(
  resolve(root, 'apps/web/dist/recording-reset.html'),
  `<!doctype html><meta charset="utf-8"><p>正在重置录制工作台…</p><script type="module">for(const db of await indexedDB.databases()){await new Promise((yes,no)=>{const r=indexedDB.deleteDatabase(db.name);r.onsuccess=yes;r.onerror=no;r.onblocked=()=>document.querySelector('p').textContent='请关闭其他录制工作台标签页，重置会自动继续。'})}localStorage.clear();sessionStorage.clear();location.replace('/')<\/script>`,
)
const child = spawn(
  process.execPath,
  [resolve(root, 'apps/web/dist-server/index.cjs')],
  { cwd: resolve(root, 'apps/web'), env, stdio: 'inherit' },
)
const sleep = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms))
for (let i = 0; i < 50; i++) {
  try {
    if ((await fetch(web)).ok) break
  } catch {}
  await sleep(200)
}
let sequence = 100,
  messages: any[] = []
let status: any = { busy: false, message: '就绪。先重置场景，再打开 WebUI。' }
const botName = '嘟嘟哒',
  groupName = '数学分析选课 · 四人模拟群'
const socket = new WebSocket('ws://127.0.0.1:5174/onebot/v11/ws', {
  headers: {
    'X-Self-ID': '1000000001',
    Authorization: `Bearer ${readFileSync(resolve(state, 'secrets/onebot_access_token'), 'utf8').trim()}`,
    'X-Client-Role': 'Universal',
  },
})
function event(name: string, text: string, bot = false) {
  const uid = bot
    ? 1000000001
    : 3000000001 + Math.max(0, fixture.members.indexOf(name))
  const id = ++sequence
  return {
    self_id: 1000000001,
    time: Math.floor(Date.now() / 1000),
    message_id: id,
    message_seq: id,
    real_id: id,
    user_id: uid,
    group_id: 2000000001,
    group_name: groupName,
    message_type: 'group',
    post_type: 'message',
    sender: {
      user_id: uid,
      nickname: name,
      card: name,
      role: bot ? 'owner' : 'member',
    },
    message: [{ type: 'text', data: { text } }],
    raw_message: text,
    message_format: 'array',
    font: 0,
  }
}
function publish(name: string, text: string, bot = false) {
  const row = event(name, text, bot)
  messages.push(row)
  socket.send(JSON.stringify(row))
  return row
}
socket.on('message', (raw) => {
  const req = JSON.parse(raw.toString())
  let data: any
  switch (req.action) {
    case 'get_login_info':
      data = { user_id: 1000000001, nickname: botName }
      break
    case 'get_status':
      data = { online: true, good: true, stat: {} }
      break
    case 'get_version_info':
      data = {
        app_name: 'NapCat.Onebot',
        protocol_version: 'v11',
        app_version: '4.18.13',
        recording_simulation: true,
      }
      break
    case 'nc_get_packet_status':
    case 'mark_group_msg_as_read':
      data = null
      break
    case 'get_group_list':
      data = [{ group_id: 2000000001, group_name: groupName, member_count: 5 }]
      break
    case 'get_friend_list':
    case 'get_friends_with_category':
      data = []
      break
    case 'get_recent_contact':
      data = messages.length
        ? [
            {
              lastestMsg: messages.at(-1),
              peerUin: '2000000001',
              remark: '',
              msgTime: String(Math.floor(Date.now() / 1000)),
              chatType: 2,
              msgId: String(messages.at(-1).message_id),
              peerName: groupName,
            },
          ]
        : []
      break
    case 'get_group_msg_history':
      data = { messages: messages.slice(-100) }
      break
    case 'get_group_info':
      data = {
        group_id: 2000000001,
        group_name: groupName,
        member_count: 5,
        max_member_count: 200,
      }
      break
    case 'get_group_member_list':
      data = [botName, ...fixture.members].map((name: string, i: number) => ({
        group_id: 2000000001,
        user_id: i === 0 ? 1000000001 : 3000000000 + i,
        nickname: name,
        card: name,
        role: i === 0 ? 'owner' : 'member',
        join_time: 1788000000,
        last_sent_time: Math.floor(Date.now() / 1000),
      }))
      break
    case 'send_group_msg': {
      const text = (req.params.message || [])
        .filter((x: any) => x.type === 'text')
        .map((x: any) => x.data.text)
        .join('')
      data = { message_id: publish(botName, text, true).message_id }
      break
    }
    case 'get_msg':
      data = messages.find(
        (x) => String(x.message_id) === String(req.params.message_id),
      )
      break
    case '_get_group_notice':
    case 'get_essence_msg_list':
      data = []
      break
    default:
      socket.send(
        JSON.stringify({
          status: 'failed',
          retcode: 1404,
          data: null,
          message: '录制通道未提供此群管理操作',
          echo: req.echo,
        }),
      )
      return
  }
  socket.send(
    JSON.stringify({
      status: 'ok',
      retcode: 0,
      data,
      message: '',
      echo: req.echo,
    }),
  )
})
await new Promise<void>((yes, no) => {
  socket.once('open', yes)
  socket.once('error', no)
})
publish('小林', '嘟嘟哒，今天一起看看数学分析怎么选。')
async function runtime(path: string, payload?: unknown) {
  const response = await fetch(api + path, {
    method: payload ? 'POST' : 'GET',
    headers: { 'X-API-Key': key(), 'Content-Type': 'application/json' },
    body: payload ? JSON.stringify(payload) : undefined,
    signal: AbortSignal.timeout(240000),
  })
  const data: any = await response.json()
  if (!response.ok)
    throw new Error(data.message || data.error || `HTTP ${response.status}`)
  return data
}
function reset() {
  execFileSync(
    'uv',
    [
      'run',
      '--locked',
      'python',
      '-c',
      `import sys;sys.path.insert(0,'ops/cli');from pathlib import Path;from run_recording_rehearsal import reset_policy;reset_policy(Path(sys.argv[1]))`,
      state,
    ],
    { cwd: root },
  )
  messages = []
  status = {
    busy: false,
    message: '已重置：评课关闭，自适应许可开启，等待20条讨论。',
  }
}
async function play() {
  fixture.messages = JSON.parse(
    readFileSync(
      resolve(root, 'tests/fixtures/recording/math-analysis-discussion.json'),
      'utf8',
    ),
  ).messages
  status = { busy: true, message: '正在播放四人讨论…' }
  for (const row of fixture.messages) {
    publish(row.sender, row.text)
    status.message = `四人讨论 ${messages.length}/20`
    await sleep(1400)
  }
  status.message = '20 条讨论已送入真实 Runtime，正在查询评课社区…'
  const history = messages
    .slice(-20)
    .map((row) => ({
      id: String(row.message_id),
      senderId: String(row.user_id),
      senderName: row.sender.nickname,
      content: row.raw_message,
      timestamp: new Date(row.time * 1000).toISOString(),
    }))
  const result = await runtime('/rehearsal', {
    ...scope,
    prompt: history.at(-1)?.content,
    history: {
      ...scope,
      source: 'synthetic',
      truncated: false,
      messages: history,
    },
  })
  const replies = result.data?.responses || []
  for (const row of replies)
    if (row.candidate) publish(botName, row.candidate, true)
  mkdirSync(resolve(state, 'reports'), { recursive: true })
  writeFileSync(
    resolve(state, 'reports/desk-adaptive.json'),
    JSON.stringify(result, null, 2),
  )
  status = {
    busy: false,
    message: replies.some((r: any) => r.outcome === 'response')
      ? '排练完成。回到群配置可查看嘟嘟哒已启用评课。'
      : '本次未完成，请查看下方诊断。',
    result,
  }
}
const html = `<!doctype html><meta charset="utf-8"><title>嘟嘟哒 · 录制控制台</title><style>body{font:17px system-ui;max-width:1100px;margin:48px auto;background:#fff8fb;color:#523842}a{color:#a73c6a}button{background:#cf6194;color:white;border:0;border-radius:9px;padding:13px 20px;font:inherit;margin-right:12px;cursor:pointer}button:disabled{opacity:.4}pre{background:white;padding:20px;white-space:pre-wrap;max-height:400px;overflow:auto}td{padding:10px;border-bottom:1px solid #efdde6}code{font-size:13px}</style><h1>嘟嘟哒 · 录制控制台</h1><p>四名模拟群友；模型和 MCP 实际执行。请录制 <a href="${web}" target="recording-web">WebUI 工作台</a>，此页用于幕后控制。</p><button id="reset">重置场景</button><button id="play">播放20条讨论</button><p id="status"></p><details><summary>本次排练结果</summary><pre id="result"></pre></details><p><a href="/poster" target="_blank">开场海报</a> · <a href="/plugins" target="_blank">插件实测素材</a> · <a href="/design" target="_blank">架构展示</a></p><h2>手动能力清单</h2><p>在 WebUI 当前群配置中打开对应插件，再粘贴问题；原子查询可在 MCP 工作台输入下列参数。</p><table id="cases"></table><script>const rows=${JSON.stringify(cases)};const table=document.querySelector('#cases');for(const row of rows){const tr=document.createElement('tr');for(const value of [row.capabilityId,row.question,JSON.stringify(row.arguments)]){const td=document.createElement('td');td.textContent=value;tr.append(td)}table.append(tr)}async function action(name){document.querySelectorAll('button').forEach(x=>x.disabled=true);const r=await fetch('/'+name,{method:'POST'});if(!r.ok)alert(await r.text())}reset.onclick=async()=>{await action('reset');window.open('${web}/recording-reset.html','recording-web')};play.onclick=()=>action('play');setInterval(async()=>{const s=await(await fetch('/status')).json();document.querySelector('#status').textContent=s.message;document.querySelector('#result').textContent=JSON.stringify(s.result||{},null,2);document.querySelectorAll('button').forEach(x=>x.disabled=s.busy)},1000)</script>`
const server = createServer(async (req, res) => {
  try {
    if (req.method === 'GET' && req.url === '/poster') {
      res.setHeader('Content-Type', 'image/png')
      res.end(readFileSync(resolve(root, 'docs/assets/dududa-poster.png')))
      return
    }
    if (req.method === 'GET' && req.url?.startsWith('/assets/')) {
      const files: Record<string, string> = {
        'emoji.png': 'emoji.png',
        'arc-cover.jpg': 'arc-cover.jpg',
        'chart.jpg': 'charts/sayonarahatsukoi_2.jpg',
      }
      const file = files[req.url.slice(8)]
      if (!file) {
        res.writeHead(404)
        res.end()
        return
      }
      res.setHeader(
        'Content-Type',
        file.endsWith('.png') ? 'image/png' : 'image/jpeg',
      )
      res.end(readFileSync(resolve(state, 'data/recording-artifacts', file)))
      return
    }
    if (req.method === 'GET' && req.url === '/plugins') {
      const samples = JSON.parse(
        readFileSync(resolve(state, 'reports/plugin-samples.json'), 'utf8'),
      )
      const escape = (value: string) =>
        value.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
      res.setHeader('Content-Type', 'text/html; charset=utf-8')
      res.end(
        '<meta charset="utf-8"><title>嘟嘟哒 · 插件实测</title><style>body{font:20px system-ui;max-width:1080px;margin:40px auto;background:#fff8fb;color:#523842}section{background:white;border-radius:20px;padding:30px;margin:28px 0}img{max-width:100%;max-height:760px}pre{white-space:pre-wrap;font:inherit}</style><h1>嘟嘟哒 · 插件实测</h1><p>图片由真实服务生成；复读使用模拟群消息，统计使用明确标注的样例数据。</p><section><h2>/emoji 😀 😭</h2><img src="/assets/emoji.png"></section><section><h2>/arc info Testify</h2><img width="280" src="/assets/arc-cover.jpg"><pre>' +
          escape(
            readFileSync(
              resolve(state, 'data/recording-artifacts/arc-info.txt'),
              'utf8',
            ),
          ) +
          '</pre></section><section><h2>/arc chart Sayonara Hatsukoi ftr</h2><img src="/assets/chart.jpg"></section><section><h2>三位群友 → 一次复读</h2><p>小林：一起聊天，一起变好！</p><p>小周：一起聊天，一起变好！</p><p>小陈：一起聊天，一起变好！</p><pre>嘟嘟哒：' +
          escape(samples.reread.reply) +
          '</pre></section><section><h2>/sub2api status · 统计样例</h2><pre>' +
          escape(samples.sub2api.reply) +
          '</pre></section>',
      )
      return
    }
    if (req.method === 'GET' && req.url === '/design') {
      res.setHeader('Content-Type', 'text/html; charset=utf-8')
      res.end(
        '<meta charset="utf-8"><title>嘟嘟哒 · 设计</title><style>body{font:24px system-ui;background:#fff8fb;color:#523842;text-align:center;padding:70px}h1{font-size:52px}main{display:flex;gap:18px;align-items:center;justify-content:center;margin:75px 0}.card{background:white;border:2px solid #e5bad0;border-radius:20px;padding:28px;width:190px}.card b{display:block;color:#b34880;margin-bottom:20px}p{line-height:1.8}footer{color:#8c687a}</style><h1>让 AI 成为群里的自己人</h1><p>群聊上下文 → 社交决策 → 能力执行 → 人格化表达</p><main><div class="card"><b>Context</b>话题 · 指代<br>近期讨论</div>→<div class="card"><b>Social Engine</b>参与时机<br>能力启用</div>→<div class="card"><b>Model Router</b>模型档位<br>推理与篇幅</div>→<div class="card"><b>Capability / MCP</b>原子化能力<br>校园与群聊服务</div>→<div class="card"><b>Persona</b>表达风格<br>群友体验</div></main><footer>持续建设：Memory · 群友印象 · 多 OC · Skill 编排</footer>',
      )
      return
    }
    if (req.method === 'GET' && req.url === '/') {
      res.setHeader('Content-Type', 'text/html; charset=utf-8')
      res.end(html)
      return
    }
    if (req.method === 'GET' && req.url === '/status') {
      res.setHeader('Content-Type', 'application/json')
      res.end(JSON.stringify(status))
      return
    }
    if (req.method === 'POST' && ['/reset', '/play'].includes(req.url || '')) {
      if (req.headers.origin !== desk) {
        res.writeHead(403)
        res.end('请从录制控制台操作')
        return
      }
      if (status.busy) {
        res.writeHead(409)
        res.end('当前排练还在运行')
        return
      }
      if (req.url === '/reset') reset()
      else {
        void play().catch((error) => {
          status = { busy: false, message: String(error) }
        })
      }
      res.end('ok')
      return
    }
    res.writeHead(404)
    res.end()
  } catch (error) {
    res.writeHead(500)
    res.end(String(error))
  }
})
server.listen(8786, '127.0.0.1', () =>
  console.log(`Recording desk: ${desk}; WebUI: ${web}`),
)
function shutdown() {
  socket.close()
  child.kill('SIGTERM')
  server.close()
  process.exit(0)
}
process.once('SIGINT', shutdown)
process.once('SIGTERM', shutdown)

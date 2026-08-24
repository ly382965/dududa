<script setup lang="ts">
import {
  AlertTriangle,
  CheckCircle2,
  Download,
  LoaderCircle,
  PlugZap,
  X,
} from '@lucide/vue'
import { computed, nextTick, reactive, ref, watch } from 'vue'

import { mcpManagementAdapter } from '../services/mcp-management'
import type {
  McpProtocolMode,
  McpServerInstallRequest,
  McpServerInstallResult,
  McpTransport,
} from '../types/mcp-management'

const emit = defineEmits<{
  installed: []
}>()

const dialogOpen = ref(false)
const installing = ref(false)
const installError = ref('')
const installResult = ref<McpServerInstallResult>()
const serverIdInput = ref<HTMLInputElement>()

const form = reactive({
  serverId: '',
  displayName: '',
  enabled: true,
  transport: 'streamable_http' as McpTransport,
  protocolMode: 'auto' as McpProtocolMode,
  url: '',
  allowedHosts: '',
  command: '',
  cwd: '',
  args: '',
  envAllowlist: '',
  secretRefs: '',
  allowedTools: '',
  deniedTools: '',
  connectTimeout: 10,
  discoveryTimeout: 10,
  callTimeout: 30,
  maximumCallTimeout: 120,
  closeTimeout: 5,
  maximumAttempts: 1,
  baseDelayMs: 100,
  failureThreshold: 3,
  failureWindowSeconds: 60,
  openDurationSeconds: 30,
  maximumConcurrency: 1,
  schemaTtlSeconds: 300,
  configRevision: 'webui-v1',
})

const serverIdValid = computed(() => /^[a-z0-9][a-z0-9._-]{0,127}$/.test(form.serverId))
const endpointValid = computed(() => {
  if (form.transport === 'stdio') return form.command.startsWith('/') && form.cwd.startsWith('/')
  try {
    const url = new URL(form.url)
    return url.protocol === 'https:' && !url.username && !url.password && !url.search && !url.hash
  } catch {
    return false
  }
})
const allowedToolsValid = computed(() => splitList(form.allowedTools).length > 0)
const canInstall = computed(() => (
  !installing.value
  && serverIdValid.value
  && endpointValid.value
  && allowedToolsValid.value
  && Boolean(form.configRevision.trim())
))

function splitList(value: string): string[] {
  return [...new Set(value.split(/[\n,]/).map(item => item.trim()).filter(Boolean))]
}

function parseSecretRefs(value: string): McpServerInstallRequest['secretRefs'] {
  return value.split('\n').map(item => item.trim()).filter(Boolean).map((item) => {
    const separator = item.indexOf('=')
    if (separator < 1 || separator === item.length - 1) throw new Error('SecretRef 每行应为 secret-id=TARGET_NAME')
    return {
      secretId: item.slice(0, separator).trim(),
      target: form.transport === 'stdio' ? 'env' : 'header',
      targetName: item.slice(separator + 1).trim(),
    }
  })
}

function resetForm(): void {
  Object.assign(form, {
    serverId: '',
    displayName: '',
    enabled: true,
    transport: 'streamable_http',
    protocolMode: 'auto',
    url: '',
    allowedHosts: '',
    command: '',
    cwd: '',
    args: '',
    envAllowlist: '',
    secretRefs: '',
    allowedTools: '',
    deniedTools: '',
    connectTimeout: 10,
    discoveryTimeout: 10,
    callTimeout: 30,
    maximumCallTimeout: 120,
    closeTimeout: 5,
    maximumAttempts: 1,
    baseDelayMs: 100,
    failureThreshold: 3,
    failureWindowSeconds: 60,
    openDurationSeconds: 30,
    maximumConcurrency: 1,
    schemaTtlSeconds: 300,
    configRevision: 'webui-v1',
  })
}

function openDialog(): void {
  resetForm()
  installError.value = ''
  installResult.value = undefined
  dialogOpen.value = true
}

function closeDialog(): void {
  if (!installing.value) dialogOpen.value = false
}

function requestBody(): McpServerInstallRequest {
  const allowedHosts = splitList(form.allowedHosts)
  if (form.transport === 'streamable_http' && !allowedHosts.length) {
    allowedHosts.push(new URL(form.url).hostname)
  }
  return {
    serverId: form.serverId,
    ...(form.displayName.trim() ? { displayName: form.displayName.trim() } : {}),
    enabled: form.enabled,
    transport: form.transport,
    protocolMode: form.protocolMode,
    endpoint: form.transport === 'stdio'
      ? {
          command: form.command,
          args: form.args.split('\n').map(item => item.trim()).filter(Boolean),
          cwd: form.cwd,
          envAllowlist: splitList(form.envAllowlist),
        }
      : { url: form.url, allowedHosts },
    secretRefs: parseSecretRefs(form.secretRefs),
    allowedTools: splitList(form.allowedTools),
    deniedTools: splitList(form.deniedTools),
    timeoutsSeconds: {
      connect: form.connectTimeout,
      discovery: form.discoveryTimeout,
      call: form.callTimeout,
      maximumCall: form.maximumCallTimeout,
      close: form.closeTimeout,
    },
    retry: { maximumAttempts: form.maximumAttempts, baseDelayMs: form.baseDelayMs },
    circuit: {
      failureThreshold: form.failureThreshold,
      failureWindowSeconds: form.failureWindowSeconds,
      openDurationSeconds: form.openDurationSeconds,
    },
    maximumConcurrency: form.maximumConcurrency,
    schemaTtlSeconds: form.schemaTtlSeconds,
    configRevision: form.configRevision.trim(),
  }
}

async function install(): Promise<void> {
  if (!canInstall.value) return
  installing.value = true
  installError.value = ''
  installResult.value = undefined
  try {
    installResult.value = await mcpManagementAdapter.install(requestBody())
    emit('installed')
  } catch (error) {
    installError.value = error instanceof Error ? error.message : 'MCP Server 接入失败'
  } finally {
    installing.value = false
  }
}

watch(dialogOpen, async (open) => {
  if (!open) return
  await nextTick()
  serverIdInput.value?.focus()
})
</script>

<template>
  <div class="mcp-install-actions">
    <a href="/downloads/dududa-mcp-development-spec.md" download title="下载 Dududa MCP 开发与接入规范">
      <Download :size="13" /><span>下载规范</span>
    </a>
    <button type="button" title="接入 MCP Server" @click="openDialog">
      <PlugZap :size="13" /><span>接入 MCP</span>
    </button>

    <Teleport to="body">
      <div v-if="dialogOpen" class="mcp-install-backdrop" tabindex="-1" @mousedown.self="closeDialog" @keydown.esc="closeDialog">
        <section class="mcp-install-dialog" role="dialog" aria-modal="true" aria-label="接入 MCP Server">
          <header class="mcp-install-header">
            <span><PlugZap :size="20" /></span>
            <div><strong>接入 MCP Server</strong><small>登记连接事实；Capability 与 Agent 权限另行配置</small></div>
            <button type="button" title="关闭" :disabled="installing" @click="closeDialog"><X :size="18" /></button>
          </header>

          <form class="mcp-install-form" @submit.prevent="install">
            <div class="field-grid">
              <label>
                <span>Server ID *</span>
                <input ref="serverIdInput" v-model.trim="form.serverId" autocomplete="off" placeholder="campus-news" :disabled="installing" />
                <small v-if="form.serverId && !serverIdValid" class="field-error">使用小写字母、数字、点、下划线或连字符</small>
              </label>
              <label>
                <span>显示名称</span>
                <input v-model.trim="form.displayName" autocomplete="off" placeholder="校园资讯" :disabled="installing" />
              </label>
              <label>
                <span>传输方式 *</span>
                <select v-model="form.transport" :disabled="installing">
                  <option value="streamable_http">Streamable HTTP</option>
                  <option value="stdio">stdio</option>
                </select>
              </label>
              <label>
                <span>协议模式</span>
                <select v-model="form.protocolMode" :disabled="installing">
                  <option value="auto">MCP v2 / 自动</option>
                  <option value="legacy">Legacy fallback</option>
                </select>
              </label>
            </div>

            <div v-if="form.transport === 'streamable_http'" class="field-grid field-grid--endpoint">
              <label class="field-wide">
                <span>HTTPS Endpoint *</span>
                <input v-model.trim="form.url" type="url" inputmode="url" autocomplete="off" placeholder="https://mcp.example.edu/mcp" :disabled="installing" />
                <small v-if="form.url && !endpointValid" class="field-error">必须是无凭据、查询参数和片段的 HTTPS URL</small>
              </label>
              <label class="field-wide">
                <span>允许的 Host</span>
                <input v-model="form.allowedHosts" autocomplete="off" placeholder="留空时使用 Endpoint Host；多个用逗号分隔" :disabled="installing" />
              </label>
            </div>
            <div v-else class="field-grid field-grid--endpoint">
              <label>
                <span>可执行文件绝对路径 *</span>
                <input v-model.trim="form.command" autocomplete="off" placeholder="/usr/local/bin/python" :disabled="installing" />
              </label>
              <label>
                <span>工作目录绝对路径 *</span>
                <input v-model.trim="form.cwd" autocomplete="off" placeholder="/opt/mcp/server" :disabled="installing" />
              </label>
              <label class="field-wide">
                <span>启动参数</span>
                <textarea v-model="form.args" rows="3" placeholder="每行一个参数" :disabled="installing" />
              </label>
              <label class="field-wide">
                <span>允许继承的环境变量名</span>
                <input v-model="form.envAllowlist" autocomplete="off" placeholder="PATH, LANG" :disabled="installing" />
              </label>
            </div>

            <div class="field-grid">
              <label class="field-wide">
                <span>允许的 Tool *</span>
                <textarea v-model="form.allowedTools" rows="3" placeholder="每行或逗号分隔；至少一项" :disabled="installing" />
              </label>
              <label class="field-wide">
                <span>拒绝的 Tool</span>
                <textarea v-model="form.deniedTools" rows="2" placeholder="例如 delete_data, publish_message" :disabled="installing" />
              </label>
              <label class="field-wide">
                <span>SecretRef</span>
                <textarea v-model="form.secretRefs" rows="2" placeholder="每行 secret-id=ENV_NAME 或 secret-id=Header-Name；不要填写真实 Secret" :disabled="installing" />
                <small>浏览器只登记引用名。真实值由 Runtime 外部配置。</small>
              </label>
            </div>

            <details class="advanced-settings">
              <summary>连接预算与故障参数</summary>
              <div class="number-grid">
                <label><span>连接超时 (s)</span><input v-model.number="form.connectTimeout" type="number" min="1" max="3600" /></label>
                <label><span>发现超时 (s)</span><input v-model.number="form.discoveryTimeout" type="number" min="1" max="3600" /></label>
                <label><span>调用超时 (s)</span><input v-model.number="form.callTimeout" type="number" min="1" max="3600" /></label>
                <label><span>最大调用 (s)</span><input v-model.number="form.maximumCallTimeout" type="number" min="1" max="3600" /></label>
                <label><span>关闭超时 (s)</span><input v-model.number="form.closeTimeout" type="number" min="1" max="3600" /></label>
                <label><span>最大并发</span><input v-model.number="form.maximumConcurrency" type="number" min="1" max="64" /></label>
                <label><span>最大尝试</span><input v-model.number="form.maximumAttempts" type="number" min="1" /></label>
                <label><span>重试延迟 (ms)</span><input v-model.number="form.baseDelayMs" type="number" min="0" /></label>
                <label><span>失败阈值</span><input v-model.number="form.failureThreshold" type="number" min="1" /></label>
                <label><span>失败窗口 (s)</span><input v-model.number="form.failureWindowSeconds" type="number" min="1" /></label>
                <label><span>熔断时间 (s)</span><input v-model.number="form.openDurationSeconds" type="number" min="1" /></label>
                <label><span>Schema TTL (s)</span><input v-model.number="form.schemaTtlSeconds" type="number" min="1" max="86400" /></label>
              </div>
              <label class="revision-field"><span>配置版本 *</span><input v-model.trim="form.configRevision" autocomplete="off" /></label>
            </details>

            <label class="enabled-field"><input v-model="form.enabled" type="checkbox" :disabled="installing" />接入后启用连接</label>

            <div v-if="installError" class="mcp-install-result mcp-install-result--error"><AlertTriangle :size="15" /><span>{{ installError }}</span></div>
            <div v-else-if="installResult" class="mcp-install-result"><CheckCircle2 :size="15" /><span><strong>接入完成</strong>{{ installResult.message }}；尚未授予 Agent Capability。</span></div>

            <footer>
              <button type="button" :disabled="installing" @click="closeDialog">{{ installResult ? '完成' : '取消' }}</button>
              <button v-if="!installResult" type="submit" class="primary-action" :disabled="!canInstall">
                <LoaderCircle v-if="installing" :size="14" class="spinning" /><PlugZap v-else :size="14" />{{ installing ? '接入中' : '接入 Server' }}
              </button>
            </footer>
          </form>
        </section>
      </div>
    </Teleport>
  </div>
</template>

<style scoped>
.mcp-install-actions { display: flex; align-items: center; gap: 5px; }
.mcp-install-actions > a,
.mcp-install-actions > button { display: inline-flex; min-height: 28px; cursor: pointer; align-items: center; justify-content: center; gap: 4px; border: 1px solid var(--border); border-radius: 5px; color: var(--text-secondary); background: var(--surface); padding: 0 7px; font: inherit; font-size: 8px; text-decoration: none; }
.mcp-install-backdrop { position: fixed; z-index: 245; inset: 0; display: grid; place-items: center; background: #0008; padding: 16px; }
.mcp-install-dialog { display: flex; width: min(680px, 100%); max-height: calc(100dvh - 32px); overflow: hidden; flex-direction: column; border: 1px solid var(--border); border-radius: 8px; background: var(--surface); box-shadow: var(--floating-shadow); }
.mcp-install-header { display: flex; min-height: 62px; align-items: center; gap: 10px; border-bottom: 1px solid var(--border); padding: 11px 14px; }
.mcp-install-header > span { display: grid; width: 36px; height: 36px; flex: 0 0 auto; place-items: center; border-radius: 6px; color: var(--brand-strong); background: var(--brand-soft); }
.mcp-install-header > div { min-width: 0; flex: 1; }
.mcp-install-header strong, .mcp-install-header small { display: block; }
.mcp-install-header strong { color: var(--text); font-size: 13px; }
.mcp-install-header small { margin-top: 3px; color: var(--text-muted); font-size: 9px; }
.mcp-install-header > button { display: grid; width: 32px; height: 32px; cursor: pointer; place-items: center; border: 0; color: var(--text-muted); background: transparent; }
.mcp-install-form { min-height: 0; overflow-y: auto; padding: 14px; }
.field-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 10px; }
.field-grid + .field-grid { margin-top: 12px; }
.field-grid label, .revision-field { display: grid; min-width: 0; gap: 5px; }
.field-grid label > span, .revision-field > span { color: var(--text-secondary); font-size: 9px; font-weight: 650; }
.field-wide { grid-column: 1 / -1; }
.mcp-install-form input:not([type='checkbox']), .mcp-install-form select, .mcp-install-form textarea { width: 100%; min-width: 0; border: 1px solid var(--border); border-radius: 5px; color: var(--text); background: var(--surface); padding: 7px 9px; font: inherit; font-size: 9px; }
.mcp-install-form input:not([type='checkbox']), .mcp-install-form select { min-height: 36px; }
.mcp-install-form textarea { resize: vertical; line-height: 1.45; }
.mcp-install-form small { color: var(--text-muted); font-size: 8px; line-height: 1.45; }
.mcp-install-form small.field-error { color: var(--danger); }
.advanced-settings { margin-top: 12px; border: 1px solid var(--border-soft); border-radius: 6px; background: var(--surface-subtle); padding: 8px; }
.advanced-settings summary { cursor: pointer; color: var(--text-secondary); font-size: 9px; font-weight: 650; }
.number-grid { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 7px; margin-top: 10px; }
.number-grid label { display: grid; min-width: 0; gap: 4px; }
.number-grid span { color: var(--text-muted); font-size: 7px; }
.revision-field { margin-top: 8px; }
.enabled-field { display: flex; align-items: center; gap: 6px; margin-top: 12px; color: var(--text-secondary); font-size: 9px; }
.enabled-field input { accent-color: var(--brand-strong); }
.mcp-install-result { display: flex; align-items: flex-start; gap: 7px; margin-top: 12px; border: 1px solid var(--success); border-radius: 6px; color: var(--success-strong); background: var(--success-soft); padding: 9px; font-size: 9px; line-height: 1.5; }
.mcp-install-result svg { flex: 0 0 auto; margin-top: 1px; }
.mcp-install-result span, .mcp-install-result strong { display: block; }
.mcp-install-result--error { color: var(--danger); border-color: var(--danger); background: color-mix(in srgb, var(--danger) 8%, var(--surface)); }
.mcp-install-form footer { display: flex; justify-content: flex-end; gap: 7px; margin-top: 16px; border-top: 1px solid var(--border-soft); padding-top: 12px; }
.mcp-install-form footer button { display: inline-flex; min-height: 34px; cursor: pointer; align-items: center; justify-content: center; gap: 5px; border: 1px solid var(--border); border-radius: 5px; color: var(--text-secondary); background: var(--surface); padding: 0 11px; font: inherit; font-size: 9px; }
.mcp-install-form footer .primary-action { color: white; border-color: var(--brand-strong); background: var(--brand-strong); }
.mcp-install-form button:disabled, .mcp-install-header button:disabled { cursor: not-allowed; opacity: 0.5; }
@media (max-width: 620px) { .mcp-install-actions span { display: none; } .mcp-install-actions > a, .mcp-install-actions > button { width: 28px; padding: 0; } .field-grid, .number-grid { grid-template-columns: 1fr 1fr; } }
@media (max-width: 420px) { .field-grid { grid-template-columns: 1fr; } .field-wide { grid-column: auto; } }
</style>

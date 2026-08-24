<script setup lang="ts">
import {
  AlertTriangle,
  CheckCircle2,
  Download,
  ExternalLink,
  Link,
  LoaderCircle,
  Package,
  PackagePlus,
  RefreshCw,
  Upload,
  X,
} from '@lucide/vue'
import { computed, nextTick, onMounted, ref, watch } from 'vue'

import { pluginManagementAdapter } from '../services/plugin-management'
import type { PluginInstallResult, RuntimePluginCatalog } from '../types/plugin-management'

type InstallSource = 'github' | 'upload'

const catalog = ref<RuntimePluginCatalog>()
const loading = ref(false)
const loadError = ref('')
const dialogOpen = ref(false)
const installSource = ref<InstallSource>('github')
const repository = ref('')
const uploadFile = ref<File>()
const installing = ref(false)
const installError = ref('')
const installResult = ref<PluginInstallResult>()
const repositoryInput = ref<HTMLInputElement>()

const githubRepositoryValid = computed(() => {
  const value = repository.value.trim()
  if (!value) return false
  try {
    const url = new URL(value)
    const parts = url.pathname.replace(/\.git\/?$/, '').split('/').filter(Boolean)
    return url.protocol === 'https:'
      && url.hostname.toLowerCase() === 'github.com'
      && !url.username
      && !url.password
      && !url.search
      && !url.hash
      && parts.length === 2
  } catch {
    return false
  }
})
const uploadFileValid = computed(() => Boolean(uploadFile.value?.name.toLowerCase().endsWith('.zip')))

const canInstall = computed(() => (
  !installing.value
  && catalog.value?.available === true
  && (installSource.value === 'github' ? githubRepositoryValid.value : uploadFileValid.value)
))

function safeRepository(value?: string): string | undefined {
  if (!value) return undefined
  try {
    const url = new URL(value)
    return url.protocol === 'https:' ? url.toString() : undefined
  } catch {
    return undefined
  }
}

function pluginDate(value?: string): string {
  if (!value) return ''
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value
  return new Intl.DateTimeFormat('zh-CN', {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    hour12: false,
  }).format(date)
}

function fileSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${Math.round(bytes / 102.4) / 10} KB`
  return `${Math.round(bytes / 1024 / 102.4) / 10} MB`
}

async function loadPlugins(): Promise<void> {
  if (loading.value) return
  loading.value = true
  loadError.value = ''
  try {
    catalog.value = await pluginManagementAdapter.runtimePlugins()
  } catch (error) {
    loadError.value = error instanceof Error ? error.message : 'Runtime 插件列表读取失败'
  } finally {
    loading.value = false
  }
}

function openInstallDialog(): void {
  installSource.value = 'github'
  repository.value = ''
  uploadFile.value = undefined
  installError.value = ''
  installResult.value = undefined
  dialogOpen.value = true
}

function closeInstallDialog(): void {
  if (!installing.value) dialogOpen.value = false
}

function chooseSource(source: InstallSource): void {
  if (installing.value || installSource.value === source) return
  installSource.value = source
  installError.value = ''
  installResult.value = undefined
}

function selectFile(event: Event): void {
  const input = event.target as HTMLInputElement
  uploadFile.value = input.files?.[0]
  installError.value = ''
  installResult.value = undefined
}

async function install(ignoreVersionCheck = false): Promise<void> {
  if (!canInstall.value) return
  installing.value = true
  installError.value = ''
  installResult.value = undefined
  try {
    const result = installSource.value === 'github'
      ? await pluginManagementAdapter.installGithub({
          repository: repository.value.trim(),
          ...(ignoreVersionCheck ? { ignoreVersionCheck: true } : {}),
        })
      : await pluginManagementAdapter.installUpload(uploadFile.value!, ignoreVersionCheck)
    installResult.value = result
    if (result.status === 'ok') await loadPlugins()
  } catch (error) {
    installError.value = error instanceof Error ? error.message : '插件安装失败'
  } finally {
    installing.value = false
  }
}

watch(
  () => dialogOpen.value,
  async (open) => {
    if (!open) return
    await nextTick()
    repositoryInput.value?.focus()
  },
)

watch(repository, () => {
  installError.value = ''
  installResult.value = undefined
})

onMounted(() => void loadPlugins())
</script>

<template>
  <section class="plugin-manager-panel">
    <div class="plugin-manager-heading">
      <Package :size="15" />
      <span><strong>Runtime 插件</strong><small>ASTRBOT PLUGIN MANAGER</small></span>
      <div class="plugin-manager-actions">
        <a
          href="/downloads/dududa-plugin-development-spec.md"
          download
          title="下载 Dududa 插件开发规范"
        >
          <Download :size="13" />
          <span>下载规范</span>
        </a>
        <button
          type="button"
          title="安装 Runtime 插件"
          :disabled="loading || catalog?.available !== true"
          @click="openInstallDialog"
        >
          <PackagePlus :size="13" />
          <span>安装插件</span>
        </button>
        <button type="button" class="icon-action" title="刷新 Runtime 插件" :disabled="loading" @click="loadPlugins">
          <RefreshCw :size="13" :class="{ spinning: loading }" />
        </button>
      </div>
    </div>

    <p class="runtime-boundary">
      Runtime 安装状态与 Agent 能力授权分开；新插件安装后不会自动进入上方受治理 Catalog。
    </p>

    <div v-if="loading && !catalog" class="plugin-manager-state">
      <LoaderCircle :size="15" class="spinning" />正在读取 Runtime 插件
    </div>
    <div v-else-if="loadError" class="plugin-manager-state plugin-manager-state--error">
      <AlertTriangle :size="15" />
      <span>{{ loadError }}</span>
      <button type="button" @click="loadPlugins">重试</button>
    </div>
    <div v-else-if="catalog && !catalog.available" class="plugin-manager-state plugin-manager-state--error">
      <AlertTriangle :size="15" />{{ catalog.reason || 'AstrBot 插件管理后端不可用' }}
    </div>
    <div v-else-if="catalog?.plugins.length" class="runtime-plugin-list">
      <article v-for="plugin in catalog.plugins" :key="plugin.id" class="runtime-plugin-row">
        <div class="runtime-plugin-icon" :class="{ active: plugin.activated }">
          <Package :size="15" />
        </div>
        <div class="runtime-plugin-copy">
          <header>
            <strong>{{ plugin.displayName || plugin.name }}</strong>
            <small>{{ plugin.version || '版本未知' }}</small>
          </header>
          <p>{{ plugin.description || plugin.name }}</p>
          <span>
            <b :class="plugin.activated ? 'active' : 'inactive'">{{ plugin.activated ? '已启用' : '未启用' }}</b>
            <b v-if="plugin.reserved">系统保留</b>
            <small>{{ plugin.author || '未知作者' }}</small>
            <small v-if="plugin.installedAt">安装于 {{ pluginDate(plugin.installedAt) }}</small>
          </span>
        </div>
        <a
          v-if="safeRepository(plugin.repository)"
          class="repository-link"
          :href="safeRepository(plugin.repository)"
          target="_blank"
          rel="noreferrer"
          :title="`打开 ${plugin.displayName || plugin.name} 仓库`"
        >
          <ExternalLink :size="13" />
        </a>
      </article>
    </div>
    <div v-else-if="catalog" class="plugin-manager-state">当前 Runtime 没有可展示的插件</div>

    <Teleport to="body">
      <div
        v-if="dialogOpen"
        class="plugin-install-backdrop"
        role="presentation"
        tabindex="-1"
        @mousedown.self="closeInstallDialog"
        @keydown.esc="closeInstallDialog"
      >
        <section class="plugin-install-dialog" role="dialog" aria-modal="true" aria-label="安装 Runtime 插件">
          <header class="plugin-install-header">
            <span><PackagePlus :size="20" /></span>
            <div><strong>安装 Runtime 插件</strong><small>AstrBot 将在安装完成后热加载插件</small></div>
            <button type="button" title="关闭安装窗口" :disabled="installing" @click="closeInstallDialog"><X :size="18" /></button>
          </header>

          <div class="plugin-source-tabs" role="tablist" aria-label="插件来源">
            <button type="button" role="tab" :aria-selected="installSource === 'github'" :class="{ active: installSource === 'github' }" :disabled="installing" @click="chooseSource('github')">
              <Link :size="14" />GitHub URL
            </button>
            <button type="button" role="tab" :aria-selected="installSource === 'upload'" :class="{ active: installSource === 'upload' }" :disabled="installing" @click="chooseSource('upload')">
              <Upload :size="14" />ZIP 文件
            </button>
          </div>

          <form class="plugin-install-form" @submit.prevent="install(false)">
            <label v-if="installSource === 'github'">
              <span>GitHub 仓库地址</span>
              <input
                ref="repositoryInput"
                v-model.trim="repository"
                type="url"
                inputmode="url"
                autocomplete="off"
                placeholder="https://github.com/owner/repository"
                :disabled="installing"
                aria-label="GitHub 仓库地址"
              />
              <small v-if="repository && !githubRepositoryValid" class="field-error">请输入仓库首页 URL，例如 https://github.com/owner/repository</small>
            </label>
            <label v-else class="plugin-file-field">
              <span>插件 ZIP</span>
              <input type="file" accept=".zip,application/zip,application/x-zip-compressed" :disabled="installing" aria-label="选择插件 ZIP" @change="selectFile" />
              <small v-if="uploadFile" :class="{ 'field-error': !uploadFileValid }">
                {{ uploadFile.name }} · {{ fileSize(uploadFile.size) }}{{ uploadFileValid ? '' : ' · 请选择 .zip 文件' }}
              </small>
              <small v-else>选择包含 main.py 与 metadata.yaml 的 ZIP 文件</small>
            </label>

            <div v-if="installError" class="install-result install-result--error">
              <AlertTriangle :size="15" /><span>{{ installError }}</span>
            </div>
            <div v-else-if="installResult" class="install-result" :class="`install-result--${installResult.status}`">
              <CheckCircle2 v-if="installResult.status === 'ok'" :size="15" />
              <AlertTriangle v-else :size="15" />
              <span><strong>{{ installResult.status === 'ok' ? '安装完成' : '版本兼容性警告' }}</strong>{{ installResult.message }}</span>
            </div>

            <footer>
              <button type="button" :disabled="installing" @click="closeInstallDialog">
                {{ installResult?.status === 'ok' ? '完成' : '取消' }}
              </button>
              <button
                v-if="installResult?.status === 'warning' && installResult.canIgnoreVersionCheck"
                type="button"
                class="warning-action"
                :disabled="installing"
                @click="install(true)"
              >
                <LoaderCircle v-if="installing" :size="14" class="spinning" />
                <AlertTriangle v-else :size="14" />
                忽略版本检查并安装
              </button>
              <button v-else-if="installResult?.status !== 'ok'" type="submit" class="primary-action" :disabled="!canInstall">
                <LoaderCircle v-if="installing" :size="14" class="spinning" />
                <PackagePlus v-else :size="14" />
                {{ installing ? '安装中' : '安装' }}
              </button>
            </footer>
          </form>
        </section>
      </div>
    </Teleport>
  </section>
</template>

<style scoped>
.plugin-manager-panel {
  border-bottom: 1px solid var(--border-soft);
  padding: 13px 15px;
}

.plugin-manager-heading {
  display: flex;
  min-width: 0;
  align-items: center;
  gap: 7px;
}

.plugin-manager-heading > svg {
  flex: 0 0 auto;
  color: var(--brand-strong);
}

.plugin-manager-heading > span {
  min-width: 0;
  flex: 1;
}

.plugin-manager-heading strong,
.plugin-manager-heading small {
  display: block;
}

.plugin-manager-heading strong {
  color: var(--text);
  font-size: 11px;
}

.plugin-manager-heading small {
  margin-top: 1px;
  color: var(--text-muted);
  font-size: 7px;
}

.plugin-manager-actions {
  display: flex;
  flex: 0 0 auto;
  align-items: center;
  gap: 5px;
}

.plugin-manager-actions a,
.plugin-manager-actions button,
.plugin-manager-state button {
  display: inline-flex;
  min-height: 28px;
  cursor: pointer;
  align-items: center;
  justify-content: center;
  gap: 4px;
  border: 1px solid var(--border);
  border-radius: 5px;
  color: var(--text-secondary);
  background: var(--surface);
  padding: 0 7px;
  font: inherit;
  font-size: 8px;
  text-decoration: none;
}

.plugin-manager-actions .icon-action {
  width: 28px;
  padding: 0;
}

.plugin-manager-actions button:disabled,
.plugin-manager-state button:disabled {
  cursor: not-allowed;
  opacity: 0.5;
}

.runtime-boundary {
  margin: 7px 0 9px;
  color: var(--text-muted);
  font-size: 8px;
  line-height: 1.5;
}

.plugin-manager-state {
  display: flex;
  min-height: 54px;
  align-items: center;
  justify-content: center;
  gap: 7px;
  border: 1px dashed var(--border-strong);
  border-radius: 6px;
  color: var(--text-muted);
  padding: 10px;
  font-size: 8px;
  text-align: center;
}

.plugin-manager-state--error {
  color: var(--danger);
  border-color: color-mix(in srgb, var(--danger) 38%, var(--border));
}

.runtime-plugin-list {
  display: grid;
  gap: 6px;
}

.runtime-plugin-row {
  display: grid;
  min-width: 0;
  grid-template-columns: 30px minmax(0, 1fr) 27px;
  align-items: center;
  gap: 8px;
  border: 1px solid var(--border);
  border-radius: 6px;
  background: var(--surface);
  padding: 8px;
}

.runtime-plugin-icon {
  display: grid;
  width: 30px;
  height: 30px;
  place-items: center;
  border-radius: 5px;
  color: var(--text-muted);
  background: var(--surface-subtle);
}

.runtime-plugin-icon.active {
  color: var(--success-strong);
  background: var(--success-soft);
}

.runtime-plugin-copy {
  min-width: 0;
}

.runtime-plugin-copy header {
  display: flex;
  min-width: 0;
  align-items: baseline;
  gap: 6px;
}

.runtime-plugin-copy header strong,
.runtime-plugin-copy header small,
.runtime-plugin-copy p {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.runtime-plugin-copy header strong {
  min-width: 0;
  color: var(--text);
  font-size: 9px;
}

.runtime-plugin-copy header small {
  flex: 0 0 auto;
  color: var(--text-muted);
  font-family: var(--font-mono);
  font-size: 7px;
}

.runtime-plugin-copy p {
  margin: 3px 0 5px;
  color: var(--text-muted);
  font-size: 7px;
}

.runtime-plugin-copy > span {
  display: flex;
  min-width: 0;
  flex-wrap: wrap;
  align-items: center;
  gap: 4px;
}

.runtime-plugin-copy > span b,
.runtime-plugin-copy > span small {
  border-radius: 3px;
  color: var(--text-muted);
  background: var(--surface-subtle);
  padding: 2px 4px;
  font-size: 7px;
  font-weight: 500;
}

.runtime-plugin-copy > span b.active {
  color: var(--success-strong);
  background: var(--success-soft);
}

.runtime-plugin-copy > span b.inactive {
  color: var(--warning-strong);
  background: var(--warning-soft);
}

.repository-link {
  display: grid;
  width: 27px;
  height: 27px;
  place-items: center;
  color: var(--brand-strong);
  border-radius: 5px;
}

.repository-link:hover {
  background: var(--brand-soft);
}

.plugin-install-backdrop {
  position: fixed;
  z-index: 240;
  inset: 0;
  display: grid;
  place-items: center;
  background: #0008;
  padding: 16px;
}

.plugin-install-dialog {
  display: flex;
  width: min(520px, 100%);
  max-height: min(700px, calc(100dvh - 32px));
  overflow: hidden;
  flex-direction: column;
  border: 1px solid var(--border);
  border-radius: 8px;
  background: var(--surface);
  box-shadow: var(--floating-shadow);
}

.plugin-install-header {
  display: flex;
  min-height: 62px;
  align-items: center;
  gap: 10px;
  border-bottom: 1px solid var(--border);
  padding: 11px 14px;
}

.plugin-install-header > span {
  display: grid;
  width: 36px;
  height: 36px;
  flex: 0 0 auto;
  place-items: center;
  border-radius: 6px;
  color: var(--brand-strong);
  background: var(--brand-soft);
}

.plugin-install-header > div {
  min-width: 0;
  flex: 1;
}

.plugin-install-header strong,
.plugin-install-header small {
  display: block;
}

.plugin-install-header strong {
  color: var(--text);
  font-size: 13px;
}

.plugin-install-header small {
  margin-top: 3px;
  color: var(--text-muted);
  font-size: 9px;
}

.plugin-install-header button {
  display: grid;
  width: 32px;
  height: 32px;
  flex: 0 0 auto;
  cursor: pointer;
  place-items: center;
  border: 0;
  color: var(--text-muted);
  background: transparent;
}

.plugin-source-tabs {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 5px;
  border-bottom: 1px solid var(--border);
  background: var(--surface-subtle);
  padding: 8px 14px;
}

.plugin-source-tabs button {
  display: flex;
  min-height: 34px;
  cursor: pointer;
  align-items: center;
  justify-content: center;
  gap: 6px;
  border: 1px solid transparent;
  border-radius: 5px;
  color: var(--text-muted);
  background: transparent;
  font: inherit;
  font-size: 10px;
}

.plugin-source-tabs button.active {
  color: var(--brand-strong);
  border-color: var(--brand-border);
  background: var(--surface);
}

.plugin-install-form {
  min-height: 0;
  overflow-y: auto;
  padding: 14px;
}

.plugin-install-form > label {
  display: grid;
  gap: 6px;
}

.plugin-install-form > label > span {
  color: var(--text-secondary);
  font-size: 10px;
  font-weight: 650;
}

.plugin-install-form input[type='url'],
.plugin-install-form input[type='file'] {
  width: 100%;
  min-width: 0;
  min-height: 38px;
  border: 1px solid var(--border);
  border-radius: 5px;
  color: var(--text);
  background: var(--surface);
  padding: 7px 9px;
  font: inherit;
  font-size: 10px;
}

.plugin-install-form input[type='file']::file-selector-button {
  margin-right: 9px;
  cursor: pointer;
  border: 0;
  border-radius: 4px;
  color: var(--brand-strong);
  background: var(--brand-soft);
  padding: 6px 8px;
  font: inherit;
  font-size: 9px;
}

.plugin-install-form label small {
  color: var(--text-muted);
  font-size: 8px;
  line-height: 1.45;
}

.plugin-install-form label small.field-error {
  color: var(--danger);
}

.install-result {
  display: flex;
  align-items: flex-start;
  gap: 7px;
  margin-top: 12px;
  border: 1px solid var(--success);
  border-radius: 6px;
  color: var(--success-strong);
  background: var(--success-soft);
  padding: 9px;
  font-size: 9px;
  line-height: 1.5;
}

.install-result svg {
  flex: 0 0 auto;
  margin-top: 1px;
}

.install-result span,
.install-result strong {
  display: block;
}

.install-result--warning {
  color: var(--warning-strong);
  border-color: var(--warning-strong);
  background: var(--warning-soft);
}

.install-result--error {
  color: var(--danger);
  border-color: var(--danger);
  background: color-mix(in srgb, var(--danger) 8%, var(--surface));
}

.plugin-install-form footer {
  display: flex;
  justify-content: flex-end;
  gap: 7px;
  margin-top: 16px;
  border-top: 1px solid var(--border-soft);
  padding-top: 12px;
}

.plugin-install-form footer button {
  display: inline-flex;
  min-height: 34px;
  cursor: pointer;
  align-items: center;
  justify-content: center;
  gap: 5px;
  border: 1px solid var(--border);
  border-radius: 5px;
  color: var(--text-secondary);
  background: var(--surface);
  padding: 0 11px;
  font: inherit;
  font-size: 9px;
}

.plugin-install-form footer .primary-action {
  color: #fff;
  border-color: var(--brand);
  background: var(--brand);
}

.plugin-install-form footer .warning-action {
  color: var(--warning-strong);
  border-color: var(--warning-strong);
  background: var(--warning-soft);
}

.plugin-install-form footer button:disabled,
.plugin-install-header button:disabled,
.plugin-source-tabs button:disabled {
  cursor: not-allowed;
  opacity: 0.5;
}

.spinning {
  animation: plugin-manager-spin 800ms linear infinite;
}

@keyframes plugin-manager-spin {
  to { transform: rotate(360deg); }
}

@media (max-width: 560px) {
  .plugin-manager-panel {
    padding-right: 12px;
    padding-left: 12px;
  }

  .plugin-manager-heading {
    align-items: flex-start;
    flex-wrap: wrap;
  }

  .plugin-manager-heading > span {
    padding-top: 2px;
  }

  .plugin-manager-actions {
    width: 100%;
    padding-left: 22px;
  }

  .plugin-manager-actions a,
  .plugin-manager-actions button:not(.icon-action) {
    flex: 1;
  }

  .runtime-plugin-row {
    grid-template-columns: 28px minmax(0, 1fr) 27px;
    gap: 6px;
  }

  .runtime-plugin-icon {
    width: 28px;
    height: 28px;
  }

  .plugin-install-backdrop {
    align-items: end;
    padding: 0;
  }

  .plugin-install-dialog {
    width: 100%;
    max-height: min(720px, calc(100dvh - 12px));
    border-right: 0;
    border-bottom: 0;
    border-left: 0;
    border-radius: 8px 8px 0 0;
  }

  .plugin-install-form footer {
    flex-wrap: wrap;
  }

  .plugin-install-form footer .warning-action {
    width: 100%;
    order: -1;
  }
}
</style>

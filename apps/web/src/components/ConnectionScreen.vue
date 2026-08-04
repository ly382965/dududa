<script setup lang="ts">
import { Bot, ExternalLink, KeyRound, Moon, RefreshCw, Server, Sun, Unplug } from '@lucide/vue'

import type { ThemeMode, WorkspaceSnapshot } from '../types/workspace'

defineProps<{
  runtime: WorkspaceSnapshot['runtime']
  error: string
  theme: ThemeMode
}>()

const emit = defineEmits<{
  retry: []
  toggleTheme: []
}>()
</script>

<template>
  <main class="connection-screen">
    <header class="connection-brand">
      <span class="connection-logo"><Bot :size="23" /></span>
      <span><strong>嘟嘟哒</strong><small>DUDUDA QQ WORKSPACE</small></span>
      <button class="icon-button" type="button" title="切换主题" aria-label="切换主题" @click="emit('toggleTheme')">
        <Moon v-if="theme === 'light'" :size="18" />
        <Sun v-else :size="18" />
      </button>
    </header>

    <section class="connection-panel">
      <div class="connection-state" :class="{ error: error || runtime.status === 'configuration_error' }">
        <span><Unplug :size="20" /></span>
        <div>
          <small>{{ error ? 'API OFFLINE' : runtime.status === 'configuration_error' ? 'CONFIGURATION REQUIRED' : 'WAITING FOR NAPCAT' }}</small>
          <h1>{{ error ? '无法连接嘟嘟哒服务' : runtime.status === 'configuration_error' ? 'OneBot Token 尚未就绪' : '等待 QQ 账号接入' }}</h1>
          <p>{{ error || runtime.message }}</p>
        </div>
      </div>

      <div class="connection-steps">
        <div>
          <span class="step-icon"><Server :size="17" /></span>
          <span><strong>NapCat 反向 WebSocket</strong><code>ws://dududa-web-api:8000{{ runtime.reverseWebSocketPath }}</code></span>
        </div>
        <div>
          <span class="step-icon"><KeyRound :size="17" /></span>
          <span><strong>NapCat Access Token</strong><code>DUDUDA_WEB_DATA_ROOT/secrets/onebot_access_token</code></span>
        </div>
      </div>

      <footer>
        <a href="http://localhost:6099/webui" target="_blank" rel="noreferrer">
          打开 NapCat WebUI <ExternalLink :size="13" />
        </a>
        <button type="button" @click="emit('retry')"><RefreshCw :size="14" />重新检测</button>
      </footer>
    </section>
  </main>
</template>

<style scoped>
.connection-screen {
  display: flex;
  width: 100%;
  height: 100dvh;
  min-height: 0;
  flex-direction: column;
  overflow-y: auto;
  color: var(--text);
  background: var(--app-background);
}

.connection-brand {
  display: flex;
  height: 68px;
  flex: 0 0 auto;
  align-items: center;
  gap: 10px;
  border-bottom: 1px solid var(--border);
  background: var(--surface);
  padding: 0 clamp(18px, 4vw, 48px);
}

.connection-logo {
  display: grid;
  width: 38px;
  height: 38px;
  place-items: center;
  border-radius: 8px;
  color: #ffffff;
  background: var(--brand);
}

.connection-brand > span:nth-child(2) {
  min-width: 0;
  flex: 1;
}

.connection-brand strong,
.connection-brand small {
  display: block;
}

.connection-brand strong {
  font-size: 14px;
}

.connection-brand small {
  margin-top: 2px;
  color: var(--text-muted);
  font-family: var(--font-mono);
  font-size: 7px;
}

.connection-panel {
  width: min(570px, calc(100% - 32px));
  margin: auto;
  border: 1px solid var(--border-strong);
  border-radius: 8px;
  background: var(--surface);
  box-shadow: var(--floating-shadow);
}

.connection-state {
  display: flex;
  align-items: flex-start;
  gap: 13px;
  border-bottom: 1px solid var(--border);
  padding: 22px;
}

.connection-state > span {
  display: grid;
  width: 39px;
  height: 39px;
  flex: 0 0 auto;
  place-items: center;
  border-radius: 7px;
  color: var(--warning-strong);
  background: var(--warning-soft);
}

.connection-state.error > span {
  color: var(--danger);
  background: var(--danger-soft);
}

.connection-state small {
  color: var(--warning-strong);
  font-family: var(--font-mono);
  font-size: 8px;
  font-weight: 700;
}

.connection-state h1 {
  margin: 5px 0 0;
  font-size: 19px;
  font-weight: 720;
}

.connection-state p {
  margin: 7px 0 0;
  color: var(--text-secondary);
  font-size: 11px;
  line-height: 1.6;
}

.connection-steps {
  padding: 11px 22px;
}

.connection-steps > div {
  display: grid;
  grid-template-columns: 32px minmax(0, 1fr);
  align-items: center;
  gap: 9px;
  border-bottom: 1px solid var(--border-soft);
  padding: 11px 0;
}

.connection-steps > div:last-child {
  border-bottom: 0;
}

.step-icon {
  display: grid;
  width: 30px;
  height: 30px;
  place-items: center;
  border-radius: 6px;
  color: var(--brand-strong);
  background: var(--brand-soft);
}

.connection-steps strong,
.connection-steps code {
  display: block;
}

.connection-steps strong {
  color: var(--text-secondary);
  font-size: 10px;
}

.connection-steps code {
  overflow: hidden;
  margin-top: 4px;
  color: var(--text-muted);
  font-family: var(--font-mono);
  font-size: 9px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.connection-panel footer {
  display: flex;
  min-height: 52px;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  border-top: 1px solid var(--border);
  background: var(--surface-subtle);
  padding: 9px 22px;
}

.connection-panel a,
.connection-panel button {
  display: inline-flex;
  height: 30px;
  align-items: center;
  gap: 5px;
  border-radius: 5px;
  padding: 0 9px;
  font-size: 9px;
  font-weight: 650;
  text-decoration: none;
}

.connection-panel a {
  color: var(--brand-strong);
}

.connection-panel button {
  cursor: pointer;
  border: 1px solid var(--brand);
  color: #ffffff;
  background: var(--brand);
}

@media (max-width: 560px) {
  .connection-panel {
    width: calc(100% - 24px);
    box-shadow: none;
  }

  .connection-state,
  .connection-steps {
    padding-right: 15px;
    padding-left: 15px;
  }

  .connection-panel footer {
    padding-right: 12px;
    padding-left: 12px;
  }
}
</style>

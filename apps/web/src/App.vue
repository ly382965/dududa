<script setup lang="ts">
import { Bot, LoaderCircle } from '@lucide/vue'

import AccountRail from './components/AccountRail.vue'
import AgentConsole from './components/AgentConsole.vue'
import ChatPane from './components/ChatPane.vue'
import ConnectionScreen from './components/ConnectionScreen.vue'
import ConversationSidebar from './components/ConversationSidebar.vue'
import { useWorkspace } from './composables/useWorkspace'
import type { MobilePanel } from './types/workspace'

const workspace = useWorkspace()

function setMobilePanel(panel: MobilePanel): void {
  if (panel === 'agent') {
    workspace.openAgent()
    return
  }
  workspace.mobilePanel.value = panel
}

function openSettings(): void {
  workspace.openAgent('settings')
}

function addAccount(): void {
  workspace.notify('请在 NapCat WebUI 登录账号并添加嘟嘟哒反向连接')
}
</script>

<template>
  <div v-if="workspace.loading.value" class="startup-screen">
    <span class="startup-logo"><Bot :size="25" /></span>
    <LoaderCircle class="startup-spinner" :size="18" />
    <strong>嘟嘟哒工作台</strong>
  </div>

  <ConnectionScreen
    v-else-if="workspace.connectionError.value || !workspace.accounts.value.length"
    :runtime="workspace.runtime.value"
    :error="workspace.connectionError.value"
    :theme="workspace.theme.value"
    @retry="workspace.load"
    @toggle-theme="workspace.toggleTheme"
  />

  <div
    v-else
    class="workspace-shell"
    :class="{
      'agent-collapsed': workspace.agentCollapsed.value,
      [`mobile-panel--${workspace.mobilePanel.value}`]: true,
    }"
  >
    <AccountRail
      :accounts="workspace.accounts.value"
      :selected-account-id="workspace.selectedAccountId.value"
      :total-unread="workspace.totalUnread.value"
      :mobile-panel="workspace.mobilePanel.value"
      :theme="workspace.theme.value"
      :agent-active="!workspace.agentCollapsed.value || workspace.mobilePanel.value === 'agent'"
      @select-account="workspace.selectAccount"
      @set-mobile-panel="setMobilePanel"
      @toggle-theme="workspace.toggleTheme"
      @open-agent="workspace.toggleAgent"
      @open-settings="openSettings"
      @add-account="addAccount"
    />

    <ConversationSidebar
      class="inbox-panel"
      :accounts="workspace.accounts.value"
      :conversations="workspace.filteredConversations.value"
      :selected-conversation-id="workspace.selectedConversationId.value"
      :selected-account-id="workspace.selectedAccountId.value"
      :search-query="workspace.searchQuery.value"
      :unread-only="workspace.unreadOnly.value"
      :online-count="workspace.onlineCount.value"
      @select-conversation="workspace.selectConversation"
      @select-account="workspace.selectAccount"
      @update-search="workspace.searchQuery.value = $event"
      @toggle-unread="workspace.unreadOnly.value = !workspace.unreadOnly.value"
    />

    <ChatPane
      class="chat-panel"
      :conversation="workspace.selectedConversation.value"
      :account="workspace.selectedAccount.value"
      :messages="workspace.chatMessages.value"
      :selected-message-id="workspace.selectedMessageId.value"
      :agent-collapsed="workspace.agentCollapsed.value"
      :loading="workspace.messagesLoading.value"
      :error="workspace.messagesError.value"
      :sending="workspace.sendingMessage.value"
      @send="workspace.sendChat"
      @send-to-agent="workspace.sendMessageToAgent"
      @open-agent="workspace.toggleAgent"
      @back="workspace.mobilePanel.value = 'inbox'"
      @notify="workspace.notify"
    />

    <AgentConsole
      class="agent-panel"
      :conversation="workspace.selectedConversation.value"
      :account="workspace.selectedAccount.value"
      :accounts="workspace.accounts.value"
      :sessions="workspace.conversationSessions.value"
      :selected-session="workspace.selectedSession.value"
      :messages="workspace.agentMessages.value"
      :run="workspace.selectedRun.value"
      :config="workspace.selectedConfig.value"
      :tab="workspace.agentTab.value"
      :available="workspace.agentAvailable.value"
      @set-tab="workspace.agentTab.value = $event"
      @select-session="workspace.selectSession"
      @new-session="workspace.newSession"
      @send-prompt="workspace.sendAgentPrompt"
      @approve-draft="workspace.approveDraft"
      @discard-draft="workspace.discardDraft"
      @update-draft="workspace.updateDraft"
      @respond-permission="workspace.respondPermission"
      @save-settings="workspace.saveSettings"
      @back="workspace.mobilePanel.value = 'chat'"
      @collapse="workspace.toggleAgent"
      @notify="workspace.notify"
    />

    <Transition name="toast">
      <div v-if="workspace.toast.value" class="app-toast" role="status">{{ workspace.toast.value }}</div>
    </Transition>
  </div>
</template>

<style scoped>
.workspace-shell {
  position: relative;
  display: grid;
  width: 100%;
  height: 100dvh;
  min-width: 0;
  min-height: 0;
  grid-template-columns: 64px 298px minmax(390px, 1fr) minmax(390px, 438px);
  overflow: hidden;
  background: var(--app-background);
}

.workspace-shell.agent-collapsed {
  grid-template-columns: 64px 298px minmax(420px, 1fr);
}

.agent-collapsed .agent-panel {
  display: none;
}

.startup-screen {
  display: grid;
  width: 100%;
  height: 100dvh;
  place-content: center;
  place-items: center;
  gap: 10px;
  color: var(--text-muted);
  background: var(--app-background);
}

.startup-screen strong {
  color: var(--text-secondary);
  font-size: 12px;
}

.startup-logo {
  display: grid;
  width: 44px;
  height: 44px;
  place-items: center;
  border-radius: 8px;
  color: #ffffff;
  background: var(--brand);
}

.startup-spinner {
  animation: spin 850ms linear infinite;
}

.app-toast {
  position: absolute;
  z-index: 100;
  right: 18px;
  bottom: 18px;
  max-width: min(340px, calc(100vw - 32px));
  border: 1px solid var(--border-strong);
  border-radius: 6px;
  color: var(--surface);
  background: var(--toast-background);
  box-shadow: var(--floating-shadow);
  padding: 9px 12px;
  font-size: 10px;
}

.toast-enter-active,
.toast-leave-active {
  transition: opacity 160ms ease, transform 160ms ease;
}

.toast-enter-from,
.toast-leave-to {
  opacity: 0;
  transform: translateY(7px);
}

@keyframes spin {
  to {
    transform: rotate(360deg);
  }
}

@media (min-width: 1680px) {
  .workspace-shell {
    grid-template-columns: 68px 314px minmax(520px, 1fr) minmax(430px, 490px);
  }

  .workspace-shell.agent-collapsed {
    grid-template-columns: 68px 314px minmax(520px, 1fr);
  }
}

@media (max-width: 1280px) {
  .workspace-shell {
    grid-template-columns: 60px 278px minmax(370px, 1fr) 382px;
  }

  .workspace-shell.agent-collapsed {
    grid-template-columns: 60px 278px minmax(420px, 1fr);
  }
}

@media (min-width: 861px) and (max-width: 1120px) {
  .workspace-shell,
  .workspace-shell.agent-collapsed {
    grid-template-columns: 60px 278px minmax(390px, 1fr);
  }

  .agent-panel {
    position: absolute;
    z-index: 40;
    top: 0;
    right: 0;
    bottom: 0;
    display: flex;
    width: min(410px, calc(100vw - 338px));
    box-shadow: -12px 0 34px rgb(18 34 38 / 14%);
  }

  .agent-collapsed .agent-panel {
    display: none;
  }
}

@media (max-width: 860px) {
  .workspace-shell,
  .workspace-shell.agent-collapsed {
    grid-template-columns: minmax(0, 1fr);
    grid-template-rows: minmax(0, 1fr) 64px;
  }

  .inbox-panel,
  .chat-panel,
  .agent-panel {
    grid-row: 1;
    grid-column: 1;
    display: none;
  }

  .mobile-panel--inbox .inbox-panel,
  .mobile-panel--chat .chat-panel,
  .mobile-panel--agent .agent-panel {
    display: flex;
  }

  .app-toast {
    right: 50%;
    bottom: 76px;
    transform: translateX(50%);
  }

  .toast-enter-from,
  .toast-leave-to {
    opacity: 0;
    transform: translate(50%, 7px);
  }
}
</style>

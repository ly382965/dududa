<script setup lang="ts">
import { Bot, LoaderCircle } from '@lucide/vue'
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import AccountRail from './components/AccountRail.vue'
import AgentConsole from './components/AgentConsole.vue'
import ChatPane from './components/ChatPane.vue'
import ConnectionScreen from './components/ConnectionScreen.vue'
import ConversationSidebar from './components/ConversationSidebar.vue'
import ManagementAccountBar from './components/ManagementAccountBar.vue'
import GroupManagementDialog from './components/group/GroupManagementDialog.vue'
import { useWorkspace } from './composables/useWorkspace'
import { groupMemberDirectoryKey, useQqDirectoryStore } from './stores/qq-directory'
import type { MobilePanel } from './types/workspace'
import ContactsView from './views/ContactsView.vue'
import ControlPlaneView from './views/ControlPlaneView.vue'
import InternalTestView from './views/InternalTestView.vue'
import NotificationsView from './views/NotificationsView.vue'
import ApiKeyPoolsView from './views/ApiKeyPoolsView.vue'
import SettingsView from './views/SettingsView.vue'

const route = useRoute()
const router = useRouter()
const initialConversationId = route.name === 'chat-conversation'
  ? `${String(route.params.accountId ?? '')}:${String(route.params.scene ?? '')}:${String(route.params.peerId ?? '')}`
  : ''
const workspace = useWorkspace(undefined, initialConversationId)
const directoryStore = useQqDirectoryStore()
const actingAccountId = ref('')
const managedGroupId = ref('')
const managedGroupAccountId = ref('')
type WorkspaceRoute = 'chat' | 'contacts' | 'notifications' | 'control-plane' | 'internal-test' | 'api-keys' | 'settings'
const activeRoute = computed<WorkspaceRoute>(() =>
  route.meta.section === 'contacts' || route.meta.section === 'notifications' || route.meta.section === 'control-plane' || route.meta.section === 'internal-test' || route.meta.section === 'api-keys' || route.meta.section === 'settings'
    ? route.meta.section
    : 'chat',
)
const managementAccount = computed(() =>
  workspace.accounts.value.find((account) => account.id === actingAccountId.value),
)
const chatMemberDirectory = computed(() => {
  const conversation = workspace.selectedConversation.value
  if (!conversation || conversation.type !== 'group') return undefined
  return directoryStore.memberDirectories[groupMemberDirectoryKey(conversation.accountId, conversation.peerId)]
})
const chatMentionCandidates = computed(() => {
  const authoritative = chatMemberDirectory.value
  if (!authoritative) return workspace.mentionCandidates.value
  return authoritative.members
    .filter((member) => member.userId !== authoritative.selfUserId)
    .map((member) => ({ userId: member.userId, name: member.card.trim() || member.nickname.trim() || member.userId }))
})
const canMentionAll = computed(() => Boolean(chatMemberDirectory.value?.permissions.mentionAll.allowed))
const managedGroupAccount = computed(() =>
  workspace.accounts.value.find((account) => account.id === managedGroupAccountId.value),
)
const pendingNotificationCount = computed(() =>
  workspace.accounts.value.reduce(
    (total, account) =>
      total +
      (directoryStore.notificationInboxes[account.id]?.items.filter(
        (item) => item.state === 'pending' && item.actionable,
      ).length ?? 0),
    0,
  ),
)
let routeSyncVersion = 0

function chatLocation(conversation = workspace.selectedConversation.value) {
  if (!conversation) return { name: 'chat' as const }
  return {
    name: 'chat-conversation' as const,
    params: {
      accountId: conversation.accountId,
      scene: conversation.type,
      peerId: conversation.peerId,
    },
  }
}

function resolveActingAccount(): void {
  const accounts = workspace.accounts.value
  if (actingAccountId.value && accounts.some((account) => account.id === actingAccountId.value)) return
  const explicit =
    workspace.selectedAccountId.value !== 'all'
      ? accounts.find((account) => account.id === workspace.selectedAccountId.value)
      : undefined
  const selectedConversationAccount =
    workspace.selectedAccountId.value === 'all'
      ? accounts.find((account) => account.id === workspace.selectedConversation.value?.accountId)
      : undefined
  actingAccountId.value =
    explicit?.id ||
    selectedConversationAccount?.id ||
    accounts.find((account) => account.status === 'online')?.id ||
    accounts[0]?.id ||
    ''
}

function navigate(target: WorkspaceRoute): void {
  if (target !== 'chat' && target !== 'internal-test' && target !== 'api-keys') resolveActingAccount()
  if (target === 'chat') workspace.mobilePanel.value = 'inbox'
  void router.push({ name: target })
}

function setMobilePanel(panel: MobilePanel): void {
  if (panel === 'agent') {
    void router.push(chatLocation()).then(() => workspace.openAgent())
    return
  }
  void router.push(panel === 'inbox' ? { name: 'chat' } : chatLocation())
  workspace.mobilePanel.value = panel
}

function openSettings(): void {
  navigate('settings')
}

function addAccount(): void {
  workspace.notify('请在 NapCat WebUI 登录账号并添加嘟嘟哒反向连接')
}

function selectAccount(accountId: string): void {
  if (activeRoute.value !== 'chat') {
    if (accountId !== 'all') actingAccountId.value = accountId
    else resolveActingAccount()
    return
  }
  workspace.selectAccount(accountId)
  workspace.mobilePanel.value = 'inbox'
  void router.push({ name: 'chat' })
}

function selectManagementAccount(accountId: string): void {
  actingAccountId.value = accountId
}

function openConversation(type: 'group' | 'private', peerId: string): void {
  const account = managementAccount.value
  if (!account) return
  const conversationId = `${account.id}:${type}:${peerId}`
  const existing = workspace.conversations.value.find((conversation) => conversation.id === conversationId)
  const directory = directoryStore.directories[account.id]
  const contact = type === 'group'
    ? directory?.groups.find((group) => group.groupId === peerId)
    : directory?.friends.find((friend) => friend.userId === peerId)
  const conversation = existing ?? {
    id: conversationId,
    accountId: account.id,
    type,
    peerId,
    name: type === 'group'
      ? contact && 'groupName' in contact ? contact.remark.trim() || contact.groupName.trim() || peerId : peerId
      : contact && 'nickname' in contact ? contact.remark.trim() || contact.nickname.trim() || peerId : peerId,
    avatar: contact?.avatar || `/api/media/avatar/${type === 'group' ? 'group' : 'user'}/${peerId}`,
    lastMessage: '',
    lastMessageAt: '',
    unread: 0,
    pinned: false,
    muted: false,
    members: type === 'group' && contact && 'memberCount' in contact ? contact.memberCount : undefined,
    updatedAt: 0,
  }
  workspace.openConversation(conversation)
  workspace.selectAccount(account.id)
  void router.push(chatLocation(conversation))
}

function selectChatConversation(conversationId: string): void {
  const conversation = workspace.conversations.value.find((item) => item.id === conversationId)
  if (!conversation) return
  workspace.openConversation(conversation)
  void router.push(chatLocation(conversation))
}

async function syncConversationRoute(): Promise<void> {
  const version = ++routeSyncVersion
  if (workspace.loading.value) return
  if (route.name !== 'chat-conversation') {
    workspace.mobilePanel.value = 'inbox'
    if (!workspace.selectedConversation.value) workspace.selectDefaultConversation(false)
    return
  }
  const accountId = String(route.params.accountId ?? '')
  const scene = String(route.params.scene ?? '')
  const peerId = String(route.params.peerId ?? '')
  if (!/^qq-\d{5,20}$/.test(accountId) || !/^\d{5,20}$/.test(peerId)) {
    void router.replace({ name: 'chat' })
    return
  }
  if (!workspace.accounts.value.some((account) => account.id === accountId)) {
    if (version === routeSyncVersion) void router.replace({ name: 'chat' })
    return
  }
  const conversationId = `${accountId}:${scene}:${peerId}`
  let conversation = workspace.conversations.value.find((item) => item.id === conversationId)
  if (!conversation) {
    const directory = await directoryStore.loadDirectory(accountId)
    if (version !== routeSyncVersion || route.name !== 'chat-conversation') return
    const contact = scene === 'group'
      ? directory?.groups.find((item) => item.groupId === peerId)
      : directory?.friends.find((item) => item.userId === peerId)
    if (!contact) {
      void router.replace({ name: 'chat' })
      return
    }
    conversation = {
      id: conversationId,
      accountId,
      type: scene as 'group' | 'private',
      peerId,
      name: scene === 'group' && 'groupName' in contact
        ? contact.remark.trim() || contact.groupName.trim() || peerId
        : 'nickname' in contact ? contact.remark.trim() || contact.nickname.trim() || peerId : peerId,
      avatar: contact.avatar,
      lastMessage: '',
      lastMessageAt: '',
      unread: 0,
      pinned: false,
      muted: false,
      members: scene === 'group' && 'memberCount' in contact ? contact.memberCount : undefined,
      updatedAt: 0,
    }
  }
  workspace.openConversation(conversation)
  workspace.selectAccount(accountId)
  workspace.mobilePanel.value = 'chat'
}

function openGroup(groupId: string, accountId = managementAccount.value?.id): void {
  if (!accountId) return
  managedGroupAccountId.value = accountId
  managedGroupId.value = groupId
}

function closeGroup(): void {
  managedGroupId.value = ''
  managedGroupAccountId.value = ''
}

watch(
  () => [activeRoute.value, workspace.selectedAccountId.value, workspace.accounts.value.length] as const,
  ([current]) => {
    if (current !== 'chat') resolveActingAccount()
  },
  { immediate: true },
)
watch(
  () => [
    route.fullPath,
    workspace.loading.value,
    workspace.accounts.value.length,
    workspace.conversations.value.length,
  ] as const,
  () => void syncConversationRoute(),
  { immediate: true },
)
watch(
  () => workspace.selectedConversation.value,
  (conversation) => {
    if (conversation?.type === 'group') {
      void directoryStore.loadMembers(conversation.accountId, conversation.peerId)
    }
  },
  { immediate: true },
)
onMounted(() => directoryStore.startEvents())
onBeforeUnmount(() => directoryStore.stopEvents())
watch(
  () => workspace.accounts.value.map((account) => account.id).join('\n'),
  () => {
    const accountIds = workspace.accounts.value.map((account) => account.id)
    const retained = new Set(accountIds)
    for (const accountId of Object.keys(directoryStore.notificationInboxes)) {
      if (!retained.has(accountId)) directoryStore.clearAccountState(accountId)
    }
    void directoryStore.primeNotifications(accountIds)
  },
  { immediate: true },
)
</script>

<template>
  <div v-if="workspace.loading.value && activeRoute !== 'internal-test' && activeRoute !== 'api-keys'" class="startup-screen">
    <span class="startup-logo"><Bot :size="25" /></span>
    <LoaderCircle class="startup-spinner" :size="18" />
    <strong>嘟嘟哒工作台</strong>
    <span role="status">正在连接工作台，联系人与历史将在后台加载…</span>
  </div>

  <ConnectionScreen
    v-else-if="activeRoute !== 'internal-test' && activeRoute !== 'api-keys' && (workspace.connectionError.value || !workspace.accounts.value.length)"
    :runtime="workspace.runtime.value"
    :error="workspace.connectionError.value"
    :theme="workspace.resolvedTheme.value"
    @retry="workspace.load"
    @toggle-theme="workspace.toggleTheme"
    @open-internal-test="navigate('internal-test')"
  />

  <div
    v-else
    class="workspace-shell"
    :class="{
      'agent-collapsed': workspace.agentCollapsed.value,
      'management-mode': activeRoute !== 'chat',
      [`mobile-panel--${workspace.mobilePanel.value}`]: true,
    }"
  >
    <AccountRail
      :accounts="workspace.accounts.value"
      :selected-account-id="activeRoute === 'chat' ? workspace.selectedAccountId.value : actingAccountId"
      :total-unread="workspace.totalUnread.value"
      :mobile-panel="workspace.mobilePanel.value"
      :theme="workspace.resolvedTheme.value"
      :agent-active="!workspace.agentCollapsed.value || workspace.mobilePanel.value === 'agent'"
      :active-route="activeRoute"
      :notification-count="pendingNotificationCount"
      @select-account="selectAccount"
      @set-mobile-panel="setMobilePanel"
      @toggle-theme="workspace.toggleTheme"
      @open-agent="setMobilePanel('agent')"
      @open-settings="openSettings"
      @add-account="addAccount"
      @navigate="navigate"
    />

    <template v-if="activeRoute === 'chat'">
    <ConversationSidebar
      class="inbox-panel"
      :accounts="workspace.accounts.value"
      :conversations="workspace.filteredConversations.value"
      :drafts="workspace.drafts.value"
      :selected-conversation-id="workspace.selectedConversationId.value"
      :selected-account-id="workspace.selectedAccountId.value"
      :search-query="workspace.searchQuery.value"
      :unread-only="workspace.unreadOnly.value"
      :online-count="workspace.onlineCount.value"
      @select-conversation="selectChatConversation"
      @select-account="selectAccount"
      @update-search="workspace.searchQuery.value = $event"
      @toggle-unread="workspace.unreadOnly.value = !workspace.unreadOnly.value"
    />

    <ChatPane
      class="chat-panel"
      :conversation="workspace.selectedConversation.value"
      :account="workspace.selectedAccount.value"
      :conversations="workspace.conversations.value"
      :messages="workspace.chatMessages.value"
      :draft="workspace.chatDraft.value"
      :reply-to="workspace.replyToMessage.value"
      :mention-candidates="chatMentionCandidates"
      :can-mention-all="canMentionAll"
      :selected-message-id="workspace.selectedMessageId.value"
      :unread-target-id="workspace.chatUnread.value?.messageId"
      :unread-count="workspace.chatUnread.value?.count"
      :agent-collapsed="workspace.agentCollapsed.value"
      :loading="workspace.messagesLoading.value"
      :error="workspace.messagesError.value"
      :sending="workspace.sendingMessage.value"
      :upload-status="workspace.uploadStatus.value"
      :history="workspace.chatHistory.value"
      :load-older="workspace.loadOlderMessages"
      :load-newer="workspace.loadNewerMessages"
      :load-latest="workspace.loadLatestMessages"
      :send-rich="workspace.sendRichMessage"
      :send-files="workspace.sendFiles"
      :load-custom-faces="workspace.loadCustomFaces"
      :send-custom-face="workspace.sendCustomFace"
      :recall-message="workspace.recallChatMessage"
      :refresh-message="workspace.refreshMessageMedia"
      :load-message-file="workspace.loadMessageFile"
      :forward-message="workspace.forwardChatMessage"
      :nudge-message="workspace.nudgeMessageSender"
      @update-draft="workspace.updateChatDraft"
      @update-reply-to="workspace.updateReplyTo"
      @jump-message="workspace.jumpToMessage"
      @consume-unread="workspace.consumeUnreadTarget"
      @retry-connection="workspace.refreshWorkspace(true)"
      @send-to-agent="workspace.sendMessageToAgent"
      @open-agent="workspace.toggleAgent"
      @back="setMobilePanel('inbox')"
      @notify="workspace.notify"
      @open-group="openGroup($event, workspace.selectedConversation.value?.accountId)"
    />
    </template>

    <section v-else class="management-panel">
      <ManagementAccountBar
        v-if="activeRoute !== 'internal-test' && activeRoute !== 'api-keys'"
        :accounts="workspace.accounts.value"
        :account-id="actingAccountId"
        @select="selectManagementAccount"
      />
      <InternalTestView
        v-if="activeRoute === 'internal-test'"
      />
      <ApiKeyPoolsView
        v-else-if="activeRoute === 'api-keys'"
        @notify="workspace.notify"
      />
      <ContactsView
        v-else-if="activeRoute === 'contacts'"
        :account="managementAccount"
        @open-conversation="openConversation"
        @open-group="openGroup"
      />
      <NotificationsView
        v-else-if="activeRoute === 'notifications'"
        :account="managementAccount"
        @notify="workspace.notify"
      />
      <ControlPlaneView
        v-else-if="activeRoute === 'control-plane'"
        :account="managementAccount"
        @notify="workspace.notify"
      />
      <SettingsView
        v-else
        :account="managementAccount"
        :conversations="workspace.conversations.value"
        :theme="workspace.theme.value"
        @toggle-theme="workspace.toggleTheme"
        @set-theme="workspace.setTheme"
        @notify="workspace.notify"
      />
    </section>

    <GroupManagementDialog
      :open="Boolean(managedGroupId)"
      :account="managedGroupAccount"
      :group-id="managedGroupId"
      @close="closeGroup"
      @quit="workspace.load"
      @notify="workspace.notify"
    />

    <AgentConsole
      v-if="activeRoute === 'chat'"
      class="agent-panel"
      :conversation="workspace.selectedConversation.value"
      :account="workspace.selectedAccount.value"
      :accounts="workspace.accounts.value"
      :sessions="workspace.conversationSessions.value"
      :selected-session="workspace.selectedSession.value"
      :messages="workspace.agentMessages.value"
      :run="workspace.selectedRun.value"
      :catalog="workspace.agentCatalog.value"
      :policy="workspace.agentPolicy.value"
      :policy-dirty="workspace.agentPolicyDirty.value"
      :policy-loading="workspace.agentPolicyLoading.value"
      :policy-saving="workspace.agentPolicySaving.value"
      :policy-error="workspace.agentPolicyError.value || workspace.agentCatalogError.value"
      :context-messages="workspace.agentContextMessages"
      :answer-profile-hint="workspace.answerProfileHint.value"
      :tab="workspace.agentTab.value"
      :available="workspace.agentAvailable.value"
      :runtime-loading="workspace.agentRuntimeLoading.value"
      :runtime-error="workspace.agentRuntimeError.value"
      :runtime-warning="workspace.agentRuntimeStatus.value?.readinessReason ?? ''"
      :runtime-controls="workspace.agentRuntimeStatus.value?.runtimeControls"
      @set-tab="workspace.agentTab.value = $event"
      @select-session="workspace.selectSession"
      @new-session="workspace.newSession"
      @send-prompt="workspace.sendAgentPrompt"
      @set-answer-profile="workspace.setAnswerProfile"
      @update-policy="workspace.updateAgentPolicy"
      @approve-draft="workspace.approveDraft"
      @discard-draft="workspace.discardDraft"
      @update-draft="workspace.updateDraft"
      @respond-permission="workspace.respondPermission"
      @save-settings="workspace.saveAgentPolicy"
      @back="setMobilePanel('chat')"
      @collapse="workspace.toggleAgent"
      @reconnect="workspace.refreshAgentRuntimeStatus"
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

.workspace-shell.management-mode {
  grid-template-columns: 64px minmax(0, 1fr);
}

.management-panel {
  display: flex;
  min-width: 0;
  min-height: 0;
  flex-direction: column;
  grid-column: 2;
  overflow: hidden;
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

  .workspace-shell.management-mode {
    grid-template-columns: 68px minmax(0, 1fr);
  }
}

@media (max-width: 1280px) {
  .workspace-shell {
    grid-template-columns: 60px 278px minmax(370px, 1fr) 382px;
  }

  .workspace-shell.agent-collapsed {
    grid-template-columns: 60px 278px minmax(420px, 1fr);
  }

  .workspace-shell.management-mode {
    grid-template-columns: 60px minmax(0, 1fr);
  }
}

@media (min-width: 861px) and (max-width: 1120px) {
  .workspace-shell,
  .workspace-shell.agent-collapsed {
    grid-template-columns: 60px 278px minmax(390px, 1fr);
  }

  .workspace-shell.management-mode,
  .workspace-shell.agent-collapsed.management-mode {
    grid-template-columns: 60px minmax(0, 1fr);
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

  .workspace-shell.management-mode,
  .workspace-shell.agent-collapsed.management-mode {
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

  .management-panel {
    display: flex;
    grid-row: 1;
    grid-column: 1;
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

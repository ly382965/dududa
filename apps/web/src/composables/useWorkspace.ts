import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'

import { workspaceAdapter, type WorkspaceAdapter } from '../services/workspace-adapter'
import type {
  Account,
  AgentConfig,
  AgentMessage,
  AgentPart,
  AgentSession,
  AgentTab,
  ChatMessage,
  Conversation,
  MobilePanel,
  ReplyDraftPart,
  ThemeMode,
  WorkspaceEvent,
  WorkspaceSnapshot,
} from '../types/workspace'

const defaultConfig = (): AgentConfig => ({
  enabled: false,
  agent: '未连接',
  model: '未连接',
  reasoning: 'medium',
  trigger: 'manual',
  contextMessages: 30,
  includeReplyChain: true,
  includeImages: false,
  longTermMemory: false,
  tools: { course: false, web: false, groupFiles: false, shell: false },
  sendPermission: 'ask',
  toolPermission: 'ask',
})

function emptySnapshot(): WorkspaceSnapshot {
  return {
    runtime: {
      status: 'waiting',
      message: '正在连接嘟嘟哒服务',
      reverseWebSocketPath: '/onebot/v11/ws',
    },
    accounts: [],
    capabilities: {},
    conversations: [],
    messages: {},
    sessions: [],
    agentMessages: {},
    runs: [],
    configs: {},
  }
}

function messageIdentity(message: ChatMessage): string {
  return message.id
}

export function useWorkspace(adapter: WorkspaceAdapter = workspaceAdapter) {
  const snapshot = ref<WorkspaceSnapshot>(emptySnapshot())
  const loading = ref(true)
  const connectionError = ref('')
  const messagesLoading = ref(false)
  const messagesError = ref('')
  const sendingMessage = ref(false)
  const selectedAccountId = ref('all')
  const selectedConversationId = ref('')
  const selectedSessionId = ref('')
  const searchQuery = ref('')
  const unreadOnly = ref(false)
  const agentTab = ref<AgentTab>('conversation')
  const mobilePanel = ref<MobilePanel>('inbox')
  const agentCollapsed = ref(false)
  const toast = ref('')
  const selectedMessageId = ref('')
  const fallbackConfig = ref(defaultConfig())
  const theme = ref<ThemeMode>(
    typeof window !== 'undefined' && window.localStorage.getItem('dududa-theme') === 'dark' ? 'dark' : 'light',
  )
  let toastTimer: ReturnType<typeof setTimeout> | undefined
  let unsubscribe: (() => void) | undefined
  let messageLoadVersion = 0

  const accounts = computed(() => snapshot.value.accounts)
  const conversations = computed(() => snapshot.value.conversations)
  const filteredConversations = computed(() => {
    const query = searchQuery.value.trim().toLocaleLowerCase('zh-CN')
    return conversations.value
      .filter((item) => selectedAccountId.value === 'all' || item.accountId === selectedAccountId.value)
      .filter((item) => !unreadOnly.value || item.unread > 0)
      .filter((item) => !query || `${item.name} ${item.lastMessage} ${item.peerId}`.toLocaleLowerCase('zh-CN').includes(query))
      .sort(
        (left, right) =>
          Number(right.pinned) - Number(left.pinned) ||
          (right.updatedAt ?? 0) - (left.updatedAt ?? 0) ||
          left.name.localeCompare(right.name, 'zh-CN'),
      )
  })
  const selectedConversation = computed<Conversation | undefined>(() =>
    conversations.value.find((item) => item.id === selectedConversationId.value),
  )
  const selectedAccount = computed<Account | undefined>(() =>
    accounts.value.find((item) => item.id === selectedConversation.value?.accountId),
  )
  const chatMessages = computed<ChatMessage[]>(() => snapshot.value.messages[selectedConversationId.value] ?? [])
  const conversationSessions = computed<AgentSession[]>(() =>
    snapshot.value.sessions.filter((item) => item.conversationId === selectedConversationId.value),
  )
  const selectedSession = computed<AgentSession | undefined>(() =>
    snapshot.value.sessions.find((item) => item.id === selectedSessionId.value),
  )
  const agentMessages = computed<AgentMessage[]>(() => snapshot.value.agentMessages[selectedSessionId.value] ?? [])
  const selectedRun = computed(() =>
    snapshot.value.runs.find(
      (item) => item.conversationId === selectedConversationId.value && item.sessionId === selectedSessionId.value,
    ),
  )
  const selectedConfig = computed<AgentConfig>(() => {
    const conversationId = selectedConversationId.value
    if (!conversationId) return fallbackConfig.value
    if (!snapshot.value.configs[conversationId]) snapshot.value.configs[conversationId] = defaultConfig()
    return snapshot.value.configs[conversationId]
  })
  const totalUnread = computed(() => conversations.value.reduce((total, item) => total + item.unread, 0))
  const onlineCount = computed(() => accounts.value.filter((item) => item.status === 'online').length)
  const agentAvailable = computed(() => snapshot.value.sessions.length > 0)

  function applyTheme(): void {
    if (typeof document !== 'undefined') document.documentElement.dataset.theme = theme.value
    if (typeof window !== 'undefined') window.localStorage.setItem('dududa-theme', theme.value)
  }

  function notify(message: string): void {
    toast.value = message
    if (toastTimer) clearTimeout(toastTimer)
    toastTimer = setTimeout(() => {
      toast.value = ''
    }, 2600)
  }

  function mergeMessages(conversationId: string, incoming: ChatMessage[]): void {
    const existing = snapshot.value.messages[conversationId] ?? []
    const merged = new Map(existing.map((message) => [messageIdentity(message), message]))
    for (const message of incoming) merged.set(messageIdentity(message), message)
    snapshot.value.messages[conversationId] = [...merged.values()].sort((left, right) => {
      const leftSequence = Number(left.messageSeq ?? left.sequence)
      const rightSequence = Number(right.messageSeq ?? right.sequence)
      return Number.isFinite(leftSequence) && Number.isFinite(rightSequence) ? leftSequence - rightSequence : 0
    })
  }

  function mergeWorkspace(next: WorkspaceSnapshot): void {
    const previous = snapshot.value
    const previousConversations = new Map(previous.conversations.map((item) => [item.id, item]))
    next.conversations = next.conversations.map((item) => ({
      ...item,
      unread: previousConversations.get(item.id)?.unread ?? item.unread,
    }))
    next.messages = previous.messages
    next.configs = { ...previous.configs, ...next.configs }
    snapshot.value = next
    const stillSelected = next.conversations.some((item) => item.id === selectedConversationId.value)
    if (!stillSelected) selectedConversationId.value = next.conversations[0]?.id ?? ''
    if (selectedAccountId.value !== 'all' && !next.accounts.some((item) => item.id === selectedAccountId.value)) {
      selectedAccountId.value = 'all'
    }
  }

  async function refreshWorkspace(force = false): Promise<void> {
    try {
      const next = await adapter.load(force)
      connectionError.value = ''
      const previousSelection = selectedConversationId.value
      mergeWorkspace(next)
      if (selectedConversationId.value && selectedConversationId.value !== previousSelection) {
        await loadConversationMessages(selectedConversation.value)
      }
    } catch (error) {
      connectionError.value = error instanceof Error ? error.message : '无法连接嘟嘟哒服务'
    }
  }

  async function loadConversationMessages(conversation = selectedConversation.value): Promise<void> {
    const version = ++messageLoadVersion
    messagesError.value = ''
    if (!conversation) return
    messagesLoading.value = true
    try {
      const cached = await adapter.loadCachedMessages(conversation, 50)
      if (version === messageLoadVersion && selectedConversationId.value === conversation.id) {
        mergeMessages(conversation.id, cached)
      }
      const messages = (await adapter.loadHistory(conversation, { limit: 50 })).messages
      if (version !== messageLoadVersion || selectedConversationId.value !== conversation.id) return
      mergeMessages(conversation.id, messages)
      void adapter.markRead(conversation).catch(() => undefined)
    } catch (error) {
      if (version === messageLoadVersion) {
        messagesError.value = error instanceof Error ? error.message : '历史消息加载失败'
      }
    } finally {
      if (version === messageLoadVersion) messagesLoading.value = false
    }
  }

  function selectAccount(accountId: string): void {
    selectedAccountId.value = accountId
    const current = selectedConversation.value
    if (accountId !== 'all' && current?.accountId !== accountId) {
      const next = conversations.value.find((item) => item.accountId === accountId)
      if (next) selectConversation(next.id, false)
    }
    mobilePanel.value = 'inbox'
  }

  function selectConversation(conversationId: string, openChat = true): void {
    const conversation = conversations.value.find((item) => item.id === conversationId)
    if (!conversation) return
    selectedConversationId.value = conversationId
    conversation.unread = 0
    selectedMessageId.value = ''
    const session = snapshot.value.sessions.find((item) => item.conversationId === conversationId)
    selectedSessionId.value = session?.id ?? ''
    void loadConversationMessages(conversation)
    if (openChat) mobilePanel.value = 'chat'
  }

  function selectSession(sessionId: string): void {
    if (snapshot.value.sessions.some((item) => item.id === sessionId)) selectedSessionId.value = sessionId
  }

  function openAgent(tab: AgentTab = 'conversation'): void {
    agentTab.value = tab
    agentCollapsed.value = false
    mobilePanel.value = 'agent'
  }

  function toggleAgent(): void {
    if (typeof window !== 'undefined' && window.matchMedia('(max-width: 860px)').matches) {
      openAgent()
      return
    }
    agentCollapsed.value = !agentCollapsed.value
  }

  async function sendChat(content: string): Promise<void> {
    const value = content.trim()
    const conversation = selectedConversation.value
    if (!value || !conversation || sendingMessage.value) return
    sendingMessage.value = true
    try {
      const message = await adapter.sendMessage(conversation, value)
      mergeMessages(conversation.id, [message])
      void adapter.cacheMessages(conversation, [message])
      conversation.lastMessage = `${selectedAccount.value?.shortName ?? '我'}：${value}`
      notify('消息已由 NapCat 发送')
    } catch (error) {
      notify(error instanceof Error ? error.message : '消息发送失败')
    } finally {
      sendingMessage.value = false
    }
  }

  function sendAgentPrompt(): void {
    notify('Agent Runtime 尚未接入，未生成本地模拟结果')
  }

  function sendMessageToAgent(message: ChatMessage): void {
    selectedMessageId.value = message.id
    openAgent('conversation')
    notify('Agent Runtime 尚未接入，未生成本地模拟结果')
  }

  function updateDraft(draft: ReplyDraftPart, content: string): void {
    draft.content = content.trim()
  }

  async function approveDraft(draft: ReplyDraftPart): Promise<void> {
    const conversation = conversations.value.find((item) => item.id === draft.conversationId)
    if (!conversation || draft.status !== 'draft') return
    try {
      const message = await adapter.sendMessage(conversation, draft.content)
      mergeMessages(conversation.id, [message])
      void adapter.cacheMessages(conversation, [message])
      draft.status = 'sent'
      notify('草稿已由 NapCat 发送')
    } catch (error) {
      notify(error instanceof Error ? error.message : '草稿发送失败')
    }
  }

  function discardDraft(draft: ReplyDraftPart): void {
    if (draft.status === 'draft') draft.status = 'discarded'
  }

  function respondPermission(part: Extract<AgentPart, { type: 'permission' }>, allow: boolean): void {
    part.state = allow ? 'allowed' : 'denied'
  }

  function newSession(): void {
    notify('Agent Runtime 尚未接入，未创建本地会话')
  }

  function saveSettings(): void {
    notify('Agent Runtime 尚未接入，配置未提交')
  }

  function toggleTheme(): void {
    theme.value = theme.value === 'light' ? 'dark' : 'light'
  }

  async function handleWorkspaceEvent(event: WorkspaceEvent): Promise<void> {
    if (event.type === 'workspace.refresh') {
      await refreshWorkspace()
      if (selectedConversation.value) await loadConversationMessages(selectedConversation.value)
      return
    }
    if (event.type === 'runtime.status') {
      snapshot.value.runtime = event.status
      return
    }
    if (event.type === 'capabilities.changed') {
      snapshot.value.capabilities ??= {}
      snapshot.value.capabilities[event.accountId] = event.capabilities
      const account = snapshot.value.accounts.find((item) => item.id === event.accountId)
      if (account) {
        account.implementation = event.capabilities.implementation
        account.capabilities = event.capabilities.actions
      }
      return
    }
    if (event.type === 'message.deleted') {
      const messages = snapshot.value.messages[event.conversationId]
      if (messages) snapshot.value.messages[event.conversationId] = messages.filter((message) => message.id !== event.messageId)
      return
    }
    const existing = conversations.value.find((item) => item.id === event.conversation.id)
    if (existing) Object.assign(existing, event.conversation)
    else snapshot.value.conversations.unshift(event.conversation)
    mergeMessages(event.conversation.id, [event.message])
    void adapter.cacheMessages(event.conversation, [event.message])
    if (event.conversation.id !== selectedConversationId.value && !event.message.mine) {
      const target = conversations.value.find((item) => item.id === event.conversation.id)
      if (target) target.unread += 1
    }
  }

  async function load(): Promise<void> {
    loading.value = true
    await refreshWorkspace(true)
    loading.value = false
    if (selectedConversation.value) await loadConversationMessages(selectedConversation.value)
  }

  watch(theme, applyTheme, { immediate: true })
  onMounted(async () => {
    unsubscribe = adapter.subscribe((event) => void handleWorkspaceEvent(event))
    await load()
  })
  onBeforeUnmount(() => {
    unsubscribe?.()
    if (toastTimer) clearTimeout(toastTimer)
  })

  return {
    loading,
    connectionError,
    messagesLoading,
    messagesError,
    sendingMessage,
    accounts,
    conversations,
    filteredConversations,
    selectedConversation,
    selectedAccount,
    chatMessages,
    conversationSessions,
    selectedSession,
    selectedSessionId,
    agentMessages,
    selectedRun,
    selectedConfig,
    selectedAccountId,
    selectedConversationId,
    selectedMessageId,
    searchQuery,
    unreadOnly,
    agentTab,
    mobilePanel,
    agentCollapsed,
    toast,
    theme,
    totalUnread,
    onlineCount,
    agentAvailable,
    runtime: computed(() => snapshot.value.runtime),
    selectAccount,
    selectConversation,
    selectSession,
    openAgent,
    toggleAgent,
    sendChat,
    sendAgentPrompt,
    sendMessageToAgent,
    updateDraft,
    approveDraft,
    discardDraft,
    respondPermission,
    newSession,
    saveSettings,
    toggleTheme,
    load,
    notify,
  }
}

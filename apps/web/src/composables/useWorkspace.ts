import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'

import type { ComposerContentSegment } from '../services/composer-content'
import { workspaceAdapter, type WorkspaceAdapter } from '../services/workspace-adapter'
import type {
  Account,
  AgentConfig,
  AgentMessage,
  AgentPart,
  AgentSession,
  AgentTab,
  ChatMessage,
  CapabilityName,
  Conversation,
  HistoryPage,
  MobilePanel,
  OutgoingMessageSegment,
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
  const uploadStatus = ref('')
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
  const replyToMessage = ref<ChatMessage | null>(null)
  const drafts = ref<Record<string, string>>({})
  const unreadTargets = ref<Record<string, { messageId: string; count: number }>>({})
  const historyStates = ref<
    Record<
      string,
      {
        beforeCursor?: string
        afterCursor?: string
        hasMoreBefore: boolean
        hasMoreAfter: boolean
        loadingBefore: boolean
        loadingAfter: boolean
      }
    >
  >({})
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
  const chatDraft = computed(() => drafts.value[selectedConversationId.value] ?? '')
  const chatHistory = computed(
    () =>
      historyStates.value[selectedConversationId.value] ?? {
        hasMoreBefore: false,
        hasMoreAfter: false,
        loadingBefore: false,
        loadingAfter: false,
      },
  )
  const chatUnread = computed(() => unreadTargets.value[selectedConversationId.value])
  const mentionCandidates = computed(() => {
    const seen = new Set<string>()
    return chatMessages.value.flatMap((message) => {
      if (message.mine || seen.has(message.senderId)) return []
      seen.add(message.senderId)
      return [{ userId: message.senderId, name: message.senderName }]
    })
  })
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

  function requireCapability(conversation: Conversation, name: CapabilityName): void {
    const account = accounts.value.find((item) => item.id === conversation.accountId)
    const capability = account?.capabilities?.[name]
    if (capability?.status !== 'supported') throw new Error(capability?.reason || `当前 QQ 账号不支持 ${name}`)
  }

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

  function mergeMessages(conversationId: string, incoming: ChatMessage[], direction: 'before' | 'latest' = 'latest'): void {
    const conversation = snapshot.value.conversations.find((item) => item.id === conversationId)
    if (!conversation) return
    const existing = snapshot.value.messages[conversationId] ?? []
    const merged = new Map(existing.map((message) => [messageIdentity(message), message]))
    for (const message of incoming) {
      if (message.accountId === conversation.accountId && message.conversationId === conversation.id) {
        merged.set(messageIdentity(message), message)
      }
    }
    let messages = [...merged.values()].sort((left, right) => {
      const leftSequence = Number(left.messageSeq ?? left.sequence)
      const rightSequence = Number(right.messageSeq ?? right.sequence)
      return Number.isFinite(leftSequence) && Number.isFinite(rightSequence) ? leftSequence - rightSequence : 0
    })
    if (messages.length > 5_000) {
      messages = direction === 'before' ? messages.slice(0, 5_000) : messages.slice(-5_000)
      const history = historyStates.value[conversationId]
      if (history) {
        if (direction === 'before') history.hasMoreAfter = true
        else history.hasMoreBefore = true
      }
    }
    snapshot.value.messages[conversationId] = messages
  }

  function applyHistoryPage(conversationId: string, page: HistoryPage, direction: 'initial' | 'before' | 'after'): void {
    const previous = historyStates.value[conversationId]
    historyStates.value[conversationId] = {
      beforeCursor:
        direction === 'after' ? previous?.beforeCursor ?? page.beforeCursor : page.beforeCursor ?? previous?.beforeCursor,
      afterCursor:
        direction === 'before' ? previous?.afterCursor ?? page.afterCursor : page.afterCursor ?? previous?.afterCursor,
      hasMoreBefore: direction === 'after' ? previous?.hasMoreBefore ?? page.hasMoreBefore : page.hasMoreBefore,
      hasMoreAfter: direction === 'before' ? previous?.hasMoreAfter ?? page.hasMoreAfter : page.hasMoreAfter,
      loadingBefore: false,
      loadingAfter: false,
    }
  }

  async function loadConversationDraft(conversation: Conversation): Promise<void> {
    const stored = await adapter.loadDraft(conversation)
    if (stored?.conversationId === conversation.id && typeof stored.content === 'string') {
      drafts.value[conversation.id] = stored.content
    }
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

  async function refreshWorkspace(force = false): Promise<boolean> {
    try {
      const next = await adapter.load(force)
      connectionError.value = ''
      const previousSelection = selectedConversationId.value
      mergeWorkspace(next)
      if (selectedConversationId.value && selectedConversationId.value !== previousSelection) {
        await loadConversationMessages(selectedConversation.value)
        if (selectedConversation.value) await loadConversationDraft(selectedConversation.value)
        return true
      }
    } catch (error) {
      connectionError.value = error instanceof Error ? error.message : '无法连接嘟嘟哒服务'
    }
    return false
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
      const page = await adapter.loadHistory(conversation, { limit: 50 })
      if (version !== messageLoadVersion || selectedConversationId.value !== conversation.id) return
      mergeMessages(conversation.id, page.messages)
      applyHistoryPage(conversation.id, page, 'initial')
      void adapter.markRead(conversation).catch(() => undefined)
    } catch (error) {
      if (version === messageLoadVersion) {
        messagesError.value = error instanceof Error ? error.message : '历史消息加载失败'
      }
    } finally {
      if (version === messageLoadVersion) messagesLoading.value = false
    }
  }

  async function loadOlderMessages(): Promise<void> {
    const conversation = selectedConversation.value
    if (!conversation) return
    const state = historyStates.value[conversation.id]
    if (!state?.beforeCursor || !state.hasMoreBefore || state.loadingBefore) return
    state.loadingBefore = true
    try {
      const page = await adapter.loadHistory(conversation, { limit: 50, before: state.beforeCursor })
      if (selectedConversationId.value !== conversation.id) return
      mergeMessages(conversation.id, page.messages, 'before')
      applyHistoryPage(conversation.id, page, 'before')
    } catch (error) {
      notify(error instanceof Error ? error.message : '更早消息加载失败')
    } finally {
      state.loadingBefore = false
    }
  }

  async function loadNewerMessages(): Promise<void> {
    const conversation = selectedConversation.value
    if (!conversation) return
    const state = historyStates.value[conversation.id]
    if (!state?.afterCursor || !state.hasMoreAfter || state.loadingAfter) return
    state.loadingAfter = true
    try {
      const page = await adapter.loadHistory(conversation, { limit: 50, after: state.afterCursor })
      if (selectedConversationId.value !== conversation.id) return
      mergeMessages(conversation.id, page.messages)
      applyHistoryPage(conversation.id, page, 'after')
    } catch (error) {
      notify(error instanceof Error ? error.message : '更新消息加载失败')
    } finally {
      state.loadingAfter = false
    }
  }

  async function loadLatestMessages(): Promise<void> {
    await loadConversationMessages(selectedConversation.value)
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
    replyToMessage.value = null
    conversation.unread = 0
    selectedMessageId.value = ''
    const session = snapshot.value.sessions.find((item) => item.conversationId === conversationId)
    selectedSessionId.value = session?.id ?? ''
    void loadConversationMessages(conversation)
    void loadConversationDraft(conversation)
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

  async function sendRichMessage(
    contentSegments: ComposerContentSegment[],
    files: Array<{ fileId: string; file: File }>,
    complete: (success: boolean) => void,
  ): Promise<void> {
    const conversation = selectedConversation.value
    if (!conversation || sendingMessage.value) {
      complete(false)
      return
    }
    sendingMessage.value = true
    try {
      const filesById = new Map(files.map((item) => [item.fileId, item.file]))
      const outgoing: OutgoingMessageSegment[] = []
      let uploaded = 0
      for (const segment of contentSegments) {
        if (segment.type !== 'pending_image') {
          const capability: CapabilityName =
            segment.type === 'text'
              ? 'message.send.text'
              : segment.type === 'mention'
                ? 'message.send.mention'
                : segment.type === 'reply'
                  ? 'message.send.reply'
                  : segment.type === 'face'
                    ? 'message.send.face'
                    : (`message.send.${segment.type}` as CapabilityName)
          requireCapability(conversation, capability)
          outgoing.push(segment)
          continue
        }
        requireCapability(conversation, 'message.send.image')
        const file = filesById.get(segment.fileId)
        if (!file) throw new Error('待发送图片已失效，请重新选择')
        uploadStatus.value = `正在上传图片 ${uploaded + 1}/${files.length}`
        const upload = await adapter.stageMedia(conversation, file)
        uploaded += 1
        if (upload.kind !== 'image') throw new Error('图片上传类型不匹配')
        outgoing.push({ type: 'image', uploadId: upload.uploadId, name: segment.summary })
      }
      uploadStatus.value = '正在通过 NapCat 发送消息'
      const message = await adapter.sendSegments(conversation, outgoing)
      mergeMessages(conversation.id, [message])
      void adapter.cacheMessages(conversation, [message])
      conversation.lastMessage = `${selectedAccount.value?.shortName ?? '我'}：${message.content}`
      drafts.value[conversation.id] = ''
      void adapter.saveDraft({
        accountId: conversation.accountId,
        conversationId: conversation.id,
        content: '',
        updatedAt: Date.now(),
      })
      notify('消息已由 NapCat 发送')
      complete(true)
    } catch (error) {
      notify(error instanceof Error ? error.message : '消息发送失败')
      complete(false)
    } finally {
      uploadStatus.value = ''
      sendingMessage.value = false
    }
  }

  async function sendFiles(files: File[]): Promise<boolean> {
    const conversation = selectedConversation.value
    if (!conversation || sendingMessage.value || !files.length) return false
    sendingMessage.value = true
    try {
      for (const [index, file] of files.entries()) {
        uploadStatus.value = `正在上传文件 ${index + 1}/${files.length}`
        if (/^(?:image|audio|video)\//.test(file.type)) {
          const kind = file.type.split('/', 1)[0] as 'image' | 'audio' | 'video'
          requireCapability(conversation, `message.send.${kind}` as CapabilityName)
          const upload = await adapter.stageMedia(conversation, file)
          const message = await adapter.sendSegments(conversation, [
            { type: upload.kind, uploadId: upload.uploadId, name: upload.name },
          ])
          mergeMessages(conversation.id, [message])
          void adapter.cacheMessages(conversation, [message])
        } else {
          requireCapability(conversation, 'message.send.file')
          await adapter.sendFile(conversation, file)
        }
      }
      notify(`${files.length} 个文件已由 NapCat 发送`)
      return true
    } catch (error) {
      notify(error instanceof Error ? error.message : '文件发送失败')
      return false
    } finally {
      uploadStatus.value = ''
      sendingMessage.value = false
    }
  }

  async function recallChatMessage(message: ChatMessage): Promise<void> {
    const conversation = selectedConversation.value
    if (!conversation || message.conversationId !== conversation.id) return
    try {
      await adapter.recallMessage(conversation, message)
      message.status = 'recalled'
      message.content = '此消息已撤回'
      message.segments = []
      notify('消息已撤回')
    } catch (error) {
      notify(error instanceof Error ? error.message : '撤回失败')
    }
  }

  async function refreshMessageMedia(message: ChatMessage): Promise<void> {
    const conversation = conversations.value.find((item) => item.id === message.conversationId)
    if (!conversation || conversation.accountId !== message.accountId) return
    try {
      const refreshed = await adapter.refreshMessage(conversation, message)
      mergeMessages(conversation.id, [refreshed])
      void adapter.cacheMessages(conversation, [refreshed])
    } catch (error) {
      notify(error instanceof Error ? error.message : '媒体地址刷新失败')
    }
  }

  async function loadMessageFile(message: ChatMessage, fileId: string): Promise<void> {
    const conversation = conversations.value.find((item) => item.id === message.conversationId)
    if (!conversation || conversation.accountId !== message.accountId) return
    try {
      const segment = message.segments.find((item) => item.type === 'file' && item.fileId === fileId)
      const url = await adapter.loadFileUrl(conversation, fileId, segment?.type === 'file' ? segment.name : undefined)
      if (segment?.type === 'file') segment.url = url
      void adapter.cacheMessages(conversation, [message])
    } catch (error) {
      notify(error instanceof Error ? error.message : '文件下载地址获取失败')
    }
  }

  async function forwardChatMessage(message: ChatMessage, target: Conversation): Promise<boolean> {
    const source = conversations.value.find((item) => item.id === message.conversationId)
    if (!source) return false
    try {
      await adapter.forwardMessage(message, source, target)
      notify(`已转发到 ${target.name}`)
      return true
    } catch (error) {
      notify(error instanceof Error ? error.message : '转发失败')
      return false
    }
  }

  async function nudgeMessageSender(message: ChatMessage): Promise<void> {
    const conversation = selectedConversation.value
    if (!conversation || message.conversationId !== conversation.id) return
    try {
      const userId = conversation.type === 'private' ? conversation.peerId : message.senderId
      await adapter.nudge(conversation, userId)
      notify(`已戳一戳 ${conversation.type === 'private' ? conversation.name : message.senderName}`)
    } catch (error) {
      notify(error instanceof Error ? error.message : '戳一戳失败')
    }
  }

  function updateChatDraft(conversationId: string, value: string): void {
    const conversation = conversations.value.find((item) => item.id === conversationId)
    if (!conversation) return
    drafts.value[conversation.id] = value
    void adapter.saveDraft({
      accountId: conversation.accountId,
      conversationId: conversation.id,
      content: value,
      updatedAt: Date.now(),
    })
  }

  function updateReplyTo(conversationId: string, message: ChatMessage | null): void {
    if (selectedConversationId.value === conversationId) replyToMessage.value = message
  }

  function replyTo(message: ChatMessage): void {
    if (message.conversationId === selectedConversationId.value) replyToMessage.value = message
  }

  function jumpToMessage(message: ChatMessage): void {
    selectedMessageId.value = message.id
    window.setTimeout(() => {
      if (selectedMessageId.value === message.id) selectedMessageId.value = ''
    }, 2_000)
  }

  function consumeUnreadTarget(conversationId: string): void {
    delete unreadTargets.value[conversationId]
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
      const message = messages?.find((item) => item.id === event.messageId)
      if (message) {
        message.status = 'recalled'
        message.content = '此消息已撤回'
        message.segments = []
      }
      void adapter.deleteCachedMessage(event.accountId, event.conversationId, event.messageId)
      return
    }
    const existing = conversations.value.find((item) => item.id === event.conversation.id)
    if (event.message.accountId !== event.conversation.accountId || event.message.conversationId !== event.conversation.id) return
    if (existing) {
      const unread = existing.unread
      Object.assign(existing, event.conversation)
      existing.unread = Math.max(unread, event.conversation.unread)
    }
    else snapshot.value.conversations.unshift(event.conversation)
    mergeMessages(event.conversation.id, [event.message])
    void adapter.cacheMessages(event.conversation, [event.message])
    if (event.conversation.id !== selectedConversationId.value && !event.message.mine) {
      const target = conversations.value.find((item) => item.id === event.conversation.id)
      if (target) {
        target.unread += 1
        const unread = unreadTargets.value[target.id]
        unreadTargets.value[target.id] = unread
          ? { ...unread, count: unread.count + 1 }
          : { messageId: event.message.id, count: 1 }
      }
    }
  }

  async function load(): Promise<void> {
    loading.value = true
    const selectionLoaded = await refreshWorkspace(true)
    loading.value = false
    if (selectedConversation.value && !selectionLoaded) {
      await Promise.all([loadConversationMessages(selectedConversation.value), loadConversationDraft(selectedConversation.value)])
    }
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
    uploadStatus,
    accounts,
    conversations,
    filteredConversations,
    selectedConversation,
    selectedAccount,
    chatMessages,
    chatDraft,
    chatHistory,
    chatUnread,
    mentionCandidates,
    replyToMessage,
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
    sendRichMessage,
    sendFiles,
    recallChatMessage,
    refreshMessageMedia,
    loadMessageFile,
    forwardChatMessage,
    nudgeMessageSender,
    updateChatDraft,
    updateReplyTo,
    replyTo,
    jumpToMessage,
    consumeUnreadTarget,
    loadOlderMessages,
    loadNewerMessages,
    loadLatestMessages,
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

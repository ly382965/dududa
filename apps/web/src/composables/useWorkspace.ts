import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'

import type { ComposerContentSegment } from '../services/composer-content'
import { internalTestAdapter, type InternalTestAgentAdapter } from '../services/internal-test'
import {
  clearUncertainGroupUpload,
  groupUploadFingerprint,
  markUncertainGroupUpload,
  uncertainGroupUploadBlocked,
} from '../services/upload-guard'
import { workspaceAdapter, type WorkspaceAdapter } from '../services/workspace-adapter'
import type {
  Account,
  AgentMessage,
  AgentPart,
  AgentRun,
  AgentSession,
  AgentTab,
  ChatMessage,
  CapabilityName,
  Conversation,
  CustomFaceCatalog,
  HistoryPage,
  MobilePanel,
  OutgoingMessageSegment,
  ReplyDraftPart,
  ThemeMode,
  WorkspaceEvent,
  WorkspaceSnapshot,
} from '../types/workspace'
import type {
  InternalTestAgentCatalog,
  InternalTestAgentPolicy,
  InternalTestAgentScope,
  InternalTestAgentStatus,
  InternalTestAnswerProfile,
} from '../types/internal-test'

const fallbackAgentContextMessages = 60

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

function normalizedMessageSequence(message: ChatMessage): string | undefined {
  const value = [message.messageSeq, message.sequence].find((candidate) => /^\d{1,24}$/.test(candidate ?? ''))
  return value?.replace(/^0+(?=\d)/, '')
}

function compareMessageSequence(left: string | undefined, right: string | undefined): number {
  if (left === right) return 0
  if (left === undefined) return -1
  if (right === undefined) return 1
  if (left.length !== right.length) return left.length - right.length
  return left < right ? -1 : 1
}

function compareMessages(left: ChatMessage, right: ChatMessage): number {
  const leftTimestamp = Number.isFinite(left.timestampMs) ? left.timestampMs as number : 0
  const rightTimestamp = Number.isFinite(right.timestampMs) ? right.timestampMs as number : 0
  if (leftTimestamp !== rightTimestamp) return leftTimestamp - rightTimestamp

  const sequenceOrder = compareMessageSequence(
    normalizedMessageSequence(left),
    normalizedMessageSequence(right),
  )
  if (sequenceOrder !== 0) return sequenceOrder

  const leftId = messageIdentity(left)
  const rightId = messageIdentity(right)
  return leftId === rightId ? 0 : leftId < rightId ? -1 : 1
}

export function useWorkspace(
  adapter: WorkspaceAdapter = workspaceAdapter,
  initialConversationId = '',
  agentAdapter: InternalTestAgentAdapter = internalTestAdapter,
) {
  const snapshot = ref<WorkspaceSnapshot>(emptySnapshot())
  const loading = ref(true)
  const connectionError = ref('')
  const messagesLoading = ref(false)
  const messagesError = ref('')
  const sendingMessage = ref(false)
  const uploadStatus = ref('')
  const selectedAccountId = ref('all')
  const selectedConversationId = ref(initialConversationId)
  const selectedSessionId = ref('')
  const searchQuery = ref('')
  const unreadOnly = ref(false)
  const agentTab = ref<AgentTab>('conversation')
  const mobilePanel = ref<MobilePanel>('inbox')
  const agentCollapsed = ref(false)
  const toast = ref('')
  const selectedMessageId = ref('')
  const replyToMessage = ref<ChatMessage | null>(null)
  const agentRuntimeStatus = ref<InternalTestAgentStatus | null>(null)
  const agentRuntimeError = ref('')
  const agentRuntimeLoading = ref(false)
  const agentPromptSending = ref(false)
  const agentCatalog = ref<InternalTestAgentCatalog>()
  const agentCatalogError = ref('')
  const agentPolicy = ref<InternalTestAgentPolicy>()
  const agentPolicyLoading = ref(false)
  const agentPolicySaving = ref(false)
  const agentPolicyError = ref('')
  const answerProfileHint = ref<InternalTestAnswerProfile>()
  const localAgentSessions = ref<AgentSession[]>([])
  const localAgentMessages = ref<Record<string, AgentMessage[]>>({})
  const localAgentRuns = ref<AgentRun[]>([])
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
  const storedTheme = typeof window !== 'undefined' ? window.localStorage.getItem('dududa-theme') : null
  const theme = ref<ThemeMode>(storedTheme === 'light' || storedTheme === 'dark' || storedTheme === 'system' ? storedTheme : 'system')
  const systemDark = ref(
    typeof window !== 'undefined' && window.matchMedia?.('(prefers-color-scheme: dark)').matches,
  )
  const resolvedTheme = computed<'light' | 'dark'>(() =>
    theme.value === 'system' ? (systemDark.value ? 'dark' : 'light') : theme.value,
  )
  let toastTimer: ReturnType<typeof setTimeout> | undefined
  let unsubscribe: (() => void) | undefined
  let colorSchemeQuery: MediaQueryList | undefined
  let agentStatusTimer: ReturnType<typeof setInterval> | undefined
  let agentPolicyGeneration = 0
  let messageLoadVersion = 0
  let initialLoadComplete = false
  const initialWorkspaceEvents: WorkspaceEvent[] = []
  const draftRevisions = new Map<string, number>()
  const updateSystemTheme = (event: MediaQueryListEvent | MediaQueryList) => (systemDark.value = event.matches)

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
  const agentAvailable = computed(
    () => agentRuntimeStatus.value?.available === true && agentRuntimeStatus.value.providerConfigured,
  )
  const allAgentSessions = computed(() => [...localAgentSessions.value, ...snapshot.value.sessions])
  const conversationSessions = computed<AgentSession[]>(() =>
    allAgentSessions.value.filter((item) => item.conversationId === selectedConversationId.value),
  )
  const selectedSession = computed<AgentSession | undefined>(() =>
    allAgentSessions.value.find((item) => item.id === selectedSessionId.value),
  )
  const agentMessages = computed<AgentMessage[]>(
    () => localAgentMessages.value[selectedSessionId.value] ?? snapshot.value.agentMessages[selectedSessionId.value] ?? [],
  )
  const selectedRun = computed(() =>
    localAgentRuns.value.find(
      (item) => item.conversationId === selectedConversationId.value && item.sessionId === selectedSessionId.value,
    ) ?? snapshot.value.runs.find(
      (item) => item.conversationId === selectedConversationId.value && item.sessionId === selectedSessionId.value,
    ),
  )
  const selectedAgentScope = computed<InternalTestAgentScope | undefined>(() => {
    const conversation = selectedConversation.value
    if (!conversation) return undefined
    return { accountId: conversation.accountId, conversationId: conversation.id }
  })
  const preferredAgentModel = computed(() => {
    const tier = agentPolicy.value?.modelTier.preferred
    if (!tier) return '动态路由'
    return agentCatalog.value?.models.find((model) => model.tier === tier && model.available)?.displayName
      ?? agentCatalog.value?.models.find((model) => model.tier === tier)?.displayName
      ?? tier
  })
  const totalUnread = computed(() => conversations.value.reduce((total, item) => total + item.unread, 0))
  const onlineCount = computed(() => accounts.value.filter((item) => item.status === 'online').length)

  function requireCapability(conversation: Conversation, name: CapabilityName): void {
    const account = accounts.value.find((item) => item.id === conversation.accountId)
    const capability = account?.capabilities?.[name]
    if (capability?.status !== 'supported') throw new Error(capability?.reason || `当前 QQ 账号不支持 ${name}`)
  }

  function applyTheme(): void {
    if (typeof document !== 'undefined') document.documentElement.dataset.theme = resolvedTheme.value
    if (typeof window !== 'undefined') window.localStorage.setItem('dududa-theme', theme.value)
  }

  function notify(message: string): void {
    toast.value = message
    if (toastTimer) clearTimeout(toastTimer)
    toastTimer = setTimeout(() => {
      toast.value = ''
    }, 2600)
  }

  async function loadAgentRuntimeStatus(): Promise<void> {
    if (agentRuntimeLoading.value) return
    agentRuntimeLoading.value = true
    try {
      agentRuntimeStatus.value = await agentAdapter.agentStatus()
      agentRuntimeError.value = ''
    } catch (error) {
      agentRuntimeStatus.value = null
      agentRuntimeError.value = error instanceof Error ? error.message : '内测 Agent Runtime 不可用'
    } finally {
      agentRuntimeLoading.value = false
    }
  }

  function refreshAgentRuntimeWhenVisible(): void {
    if (typeof document === 'undefined' || document.visibilityState === 'visible') {
      void Promise.all([loadAgentRuntimeStatus(), loadAgentCatalog()])
    }
  }

  async function loadAgentCatalog(): Promise<void> {
    try {
      agentCatalog.value = await agentAdapter.agentCatalog()
      agentCatalogError.value = ''
    } catch (error) {
      agentCatalog.value = undefined
      agentCatalogError.value = error instanceof Error ? error.message : 'Agent Catalog 读取失败'
    }
  }

  function maxAgentContextMessages(): number {
    const limits = agentCatalog.value?.contextLengths.map((item) => item.messageLimit) ?? []
    return limits.length ? Math.max(...limits) : fallbackAgentContextMessages
  }

  async function loadAgentPolicy(scope = selectedAgentScope.value): Promise<void> {
    const generation = ++agentPolicyGeneration
    agentPolicy.value = undefined
    agentPolicyError.value = ''
    answerProfileHint.value = undefined
    if (!scope) {
      agentPolicyLoading.value = false
      return
    }
    agentPolicyLoading.value = true
    try {
      const policy = await agentAdapter.agentConfig(scope)
      if (generation !== agentPolicyGeneration) return
      if (policy.scope.accountId !== scope.accountId || policy.scope.conversationId !== scope.conversationId) {
        throw new Error('Agent 配置响应与当前会话不匹配')
      }
      agentPolicy.value = policy
    } catch (error) {
      if (generation !== agentPolicyGeneration) return
      agentPolicyError.value = error instanceof Error ? error.message : 'Agent 配置读取失败'
    } finally {
      if (generation === agentPolicyGeneration) agentPolicyLoading.value = false
    }
  }

  function updateAgentPolicy(policy: InternalTestAgentPolicy): void {
    const scope = selectedAgentScope.value
    if (!scope || policy.scope.accountId !== scope.accountId || policy.scope.conversationId !== scope.conversationId) return
    agentPolicy.value = {
      ...policy,
      scope: { ...policy.scope },
      modelTier: { ...policy.modelTier, allowed: [...policy.modelTier.allowed] },
      reasoning: { ...policy.reasoning, allowed: [...policy.reasoning.allowed] },
      answerProfile: { ...policy.answerProfile, allowed: [...policy.answerProfile.allowed] },
      replyIntensity: { ...policy.replyIntensity, allowed: [...policy.replyIntensity.allowed] },
      contextLength: { ...policy.contextLength, allowed: [...policy.contextLength.allowed] },
      groupChatStyle: { ...policy.groupChatStyle, allowed: [...policy.groupChatStyle.allowed] },
      proactiveTalk: { ...policy.proactiveTalk },
      plugins: { ...policy.plugins },
    }
    agentPolicyError.value = ''
  }

  async function saveAgentPolicy(): Promise<void> {
    const scope = selectedAgentScope.value
    const policy = agentPolicy.value
    if (!scope || !policy || agentPolicySaving.value) return
    agentPolicySaving.value = true
    agentPolicyError.value = ''
    try {
      const saved = await agentAdapter.saveAgentConfig(scope, policy)
      if (selectedAgentScope.value?.accountId !== scope.accountId || selectedAgentScope.value?.conversationId !== scope.conversationId) return
      agentPolicy.value = saved
      notify('Agent 会话配置已保存；未锁定项仍可由 Agent 每轮调整')
    } catch (error) {
      if (selectedAgentScope.value?.accountId === scope.accountId && selectedAgentScope.value?.conversationId === scope.conversationId) {
        agentPolicyError.value = error instanceof Error ? error.message : 'Agent 配置保存失败'
      }
    } finally {
      agentPolicySaving.value = false
    }
  }

  function clock(value = new Date()): string {
    return value.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit', hour12: false })
  }

  function createAgentSession(): AgentSession | undefined {
    const conversation = selectedConversation.value
    if (!conversation) {
      notify('请先选择一个 QQ 会话')
      return undefined
    }
    if (!agentAvailable.value) {
      notify(agentRuntimeError.value || '内测 Agent Runtime 尚未就绪')
      return undefined
    }
    const session: AgentSession = {
      id: `internal-session-${crypto.randomUUID()}`,
      conversationId: conversation.id,
      title: '新建内测对话',
      updatedAt: clock(),
      status: 'idle',
      agent: '内测 Runtime',
      model: preferredAgentModel.value,
    }
    localAgentSessions.value.unshift(session)
    localAgentMessages.value[session.id] = []
    selectedSessionId.value = session.id
    return session
  }

  function activeAgentSession(): AgentSession | undefined {
    const current = localAgentSessions.value.find((item) => item.id === selectedSessionId.value)
    if (current?.conversationId === selectedConversationId.value) return current
    return localAgentSessions.value.find((item) => item.conversationId === selectedConversationId.value)
      ?? createAgentSession()
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
    let messages = [...merged.values()].sort(compareMessages)
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
    const revision = draftRevisions.get(conversation.id) ?? 0
    try {
      const stored = await adapter.loadDraft(conversation)
      const current = conversations.value.find((item) => item.id === conversation.id)
      if (current?.accountId !== conversation.accountId || (draftRevisions.get(conversation.id) ?? 0) !== revision) return
      if (
        stored?.accountId === conversation.accountId &&
        stored.conversationId === conversation.id &&
        typeof stored.content === 'string'
      ) drafts.value[conversation.id] = stored.content
      else delete drafts.value[conversation.id]
    } catch {
      // A cache read failure must not block the live NapCat workspace.
    }
  }

  async function loadConversationDrafts(items: Conversation[]): Promise<void> {
    await Promise.all(items.map((conversation) => loadConversationDraft(conversation)))
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
    const activeConversationIds = new Set(next.conversations.map((item) => item.id))
    for (const conversation of previous.conversations) {
      if (activeConversationIds.has(conversation.id)) continue
      draftRevisions.set(conversation.id, (draftRevisions.get(conversation.id) ?? 0) + 1)
      delete drafts.value[conversation.id]
    }
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
      await loadConversationDrafts(next.conversations)
      if (selectedConversationId.value && selectedConversationId.value !== previousSelection) {
        await loadConversationMessages(selectedConversation.value)
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
    const session = allAgentSessions.value.find((item) => item.conversationId === conversationId)
    selectedSessionId.value = session?.id ?? ''
    void loadConversationMessages(conversation)
    void loadConversationDraft(conversation)
    if (openChat) mobilePanel.value = 'chat'
  }

  function selectDefaultConversation(openChat = false): void {
    const next = conversations.value.find(
      (item) => selectedAccountId.value === 'all' || item.accountId === selectedAccountId.value,
    )
    if (next) selectConversation(next.id, openChat)
    else selectedConversationId.value = ''
  }

  function openConversation(conversation: Conversation, openChat = true): void {
    const expectedId = `${conversation.accountId}:${conversation.type}:${conversation.peerId}`
    if (conversation.id !== expectedId) throw new Error('会话账号、场景或 QQ 标识不匹配')
    const existing = snapshot.value.conversations.find((item) => item.id === conversation.id)
    if (!existing) snapshot.value.conversations.push({ ...conversation })
    if (selectedConversationId.value !== conversation.id) selectConversation(conversation.id, openChat)
    else if (openChat) mobilePanel.value = 'chat'
  }

  function selectSession(sessionId: string): void {
    if (allAgentSessions.value.some((item) => item.id === sessionId)) selectedSessionId.value = sessionId
  }

  function setAnswerProfile(answerProfile: InternalTestAnswerProfile | undefined): void {
    answerProfileHint.value = answerProfile
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

  async function loadCustomFaces(): Promise<CustomFaceCatalog> {
    const conversation = selectedConversation.value
    if (!conversation) throw new Error('请先选择 QQ 会话')
    requireCapability(conversation, 'message.custom_faces')
    const catalog = await adapter.loadCustomFaces(conversation)
    if (
      catalog.accountId !== conversation.accountId ||
      catalog.conversationId !== conversation.id ||
      selectedConversation.value?.id !== conversation.id
    ) {
      throw new Error('收藏表情响应与当前 QQ 会话不匹配')
    }
    return catalog
  }

  async function sendCustomFace(handle: string): Promise<boolean> {
    const conversation = selectedConversation.value
    if (!conversation || sendingMessage.value || !/^[a-f0-9]{32}$/.test(handle)) return false
    sendingMessage.value = true
    try {
      requireCapability(conversation, 'message.custom_faces')
      const message = await adapter.sendSegments(conversation, [{ type: 'custom_face', handle }])
      mergeMessages(conversation.id, [message])
      void adapter.cacheMessages(conversation, [message])
      const account = accounts.value.find((item) => item.id === conversation.accountId)
      conversation.lastMessage = `${account?.shortName ?? '我'}：${message.content || '[表情]'}`
      notify('收藏表情已由 NapCat 发送')
      return true
    } catch (error) {
      notify(error instanceof Error ? error.message : '收藏表情发送失败')
      return false
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
                    : segment.type === 'custom_face'
                      ? 'message.custom_faces'
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
      draftRevisions.set(conversation.id, (draftRevisions.get(conversation.id) ?? 0) + 1)
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
          if (conversation.type === 'group') {
            const fingerprint = await groupUploadFingerprint(
              conversation.accountId,
              conversation.peerId,
              '/',
              file,
            )
            if (uncertainGroupUploadBlocked(fingerprint)) {
              throw new Error('相同群文件正在上传或上次结果未知；为避免重复上传，请等待 10 分钟并先刷新群文件列表')
            }
            if (!markUncertainGroupUpload(fingerprint)) {
              throw new Error('无法写入群文件防重状态；为避免重复上传，本次请求未发送到 NapCat')
            }
            await adapter.sendFile(conversation, file)
            clearUncertainGroupUpload(fingerprint)
          } else {
            await adapter.sendFile(conversation, file)
          }
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
    draftRevisions.set(conversation.id, (draftRevisions.get(conversation.id) ?? 0) + 1)
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

  async function sendAgentPrompt(content: string): Promise<void> {
    const prompt = content.trim()
    const conversation = selectedConversation.value
    if (!prompt || !conversation || agentPromptSending.value) return
    const session = activeAgentSession()
    if (!session) return

    const now = new Date()
    const operatorMessage: AgentMessage = {
      id: `internal-message-${crypto.randomUUID()}`,
      sessionId: session.id,
      role: 'operator',
      author: '操作员',
      timestamp: clock(now),
      parts: [{ type: 'text', text: prompt }],
    }
    const messages = (localAgentMessages.value[session.id] ??= [])
    messages.push(operatorMessage)
    session.status = 'running'
    session.updatedAt = clock(now)
    if (session.title === '新建内测对话') session.title = prompt.length > 18 ? `${prompt.slice(0, 18)}…` : prompt

    const context = chatMessages.value
      .filter((message) => message.content.trim())
      .slice(-maxAgentContextMessages())
      .map((message) => ({
        senderName: message.senderName,
        content: message.content,
        mine: message.mine,
      }))
    const requestedAnswerProfile = answerProfileHint.value
    answerProfileHint.value = undefined
    const run: AgentRun = {
      id: `pending-${crypto.randomUUID()}`,
      conversationId: conversation.id,
      sessionId: session.id,
      status: 'running',
      triggerSender: '操作员',
      triggerAvatar: selectedAccount.value?.avatar ?? '',
      triggerContent: prompt,
      startedAt: clock(now),
      duration: '运行中',
      tokens: '—',
      cost: '—',
      contextMessages: context.length,
      model: session.model,
      steps: [
        {
          id: 'context',
          label: '读取群聊上下文',
          detail: `已选取最近 ${context.length} 条消息`,
          status: 'completed',
        },
        {
          id: 'candidate',
          label: '运行 2.0 内测预览',
          detail: '允许只读 Capability；不写 Memory、不发送 QQ 消息',
          status: 'running',
        },
      ],
    }
    localAgentRuns.value.unshift(run)
    agentPromptSending.value = true
    try {
      const result = await agentAdapter.respond({
        accountId: conversation.accountId,
        conversationId: conversation.id,
        conversationName: conversation.name,
        conversationType: conversation.type,
        prompt,
        messages: context,
        answerProfile: requestedAnswerProfile,
      })
      run.id = result.runId
      run.status = 'completed'
      run.duration = `${result.latencyMs} ms`
      run.model = result.model
      run.modelTier = result.tier
      run.reasoning = result.reasoning
      run.answerProfile = result.answerProfile
      run.contextMessages = result.contextUsage.messagesRead
      run.plugins = Object.entries(result.effectiveSelection.plugins)
        .filter(([, plugin]) => plugin.selectedForRun)
        .map(([id]) => id)
      run.reasonCodes = [...result.reasonCodes]
      run.effectiveSelection = result.effectiveSelection
      run.runtimePath = result.runtimePath
      run.toolCalls = result.toolCalls
      run.steps[0] = {
        ...run.steps[0],
        detail: `实际读取 ${result.contextUsage.messagesRead} 条 / ${result.contextUsage.charactersRead.toLocaleString('zh-CN')} 字符（预算上限 ${result.contextUsage.messageLimit} 条 / ${result.contextUsage.characterLimit.toLocaleString('zh-CN')} 字符）`,
      }
      run.steps[1] = {
        ...run.steps[1],
        detail: `${result.runtimePath === 'dududa_2_preview' ? 'Dududa 2.0 Runtime' : '候选回退'} · ${result.tier} · ${result.model} · Tool ${result.toolCalls}`,
        status: 'completed',
        duration: `${result.latencyMs} ms`,
      }
      session.status = 'idle'
      session.model = result.model
      session.updatedAt = clock(new Date(result.generatedAt))
      messages.push({
        id: `internal-message-${crypto.randomUUID()}`,
        sessionId: session.id,
        role: 'assistant',
        author: 'Dududa Agent',
        timestamp: session.updatedAt,
        parts: [
          { type: 'text', text: result.candidate },
          {
            type: 'status',
            label: `${result.tier} · ${result.model} · Tool ${result.toolCalls} · ${result.latencyMs} ms · 未发送`,
            tone: 'success',
          },
        ],
      })
    } catch (error) {
      const detail = error instanceof Error ? error.message : '生成候选回答失败'
      session.status = 'idle'
      run.status = 'completed'
      run.duration = '失败'
      run.steps[1] = {
        ...run.steps[1],
        label: '候选生成失败',
        detail,
        status: 'completed',
      }
      messages.push({
        id: `internal-message-${crypto.randomUUID()}`,
        sessionId: session.id,
        role: 'system',
        author: '内测 Runtime',
        timestamp: clock(),
        parts: [{ type: 'status', label: detail, tone: 'warning' }],
      })
      notify(detail)
    } finally {
      agentPromptSending.value = false
    }
  }

  function sendMessageToAgent(message: ChatMessage): void {
    selectedMessageId.value = message.id
    openAgent('conversation')
    void sendAgentPrompt(`请结合当前群聊上下文分析这条消息：\n${message.senderName}：${message.content}`)
  }

  function updateDraft(draft: ReplyDraftPart, content: string): void {
    draft.content = content.trim()
  }

  async function approveDraft(draft: ReplyDraftPart): Promise<void> {
    const conversation = conversations.value.find((item) => item.id === draft.conversationId)
    if (!conversation || draft.status !== 'draft') return
    notify('Agent 草稿发送命令尚未接入，未发送 QQ 消息')
  }

  function discardDraft(draft: ReplyDraftPart): void {
    if (draft.status === 'draft') draft.status = 'discarded'
  }

  function respondPermission(part: Extract<AgentPart, { type: 'permission' }>, allow: boolean): void {
    if (part.state !== 'pending') return
    void allow
    notify('Agent 权限命令尚未接入，状态未变更')
  }

  function newSession(): void {
    if (createAgentSession()) openAgent('conversation')
  }

  function toggleTheme(): void {
    theme.value = resolvedTheme.value === 'light' ? 'dark' : 'light'
  }

  function setTheme(mode: ThemeMode): void {
    theme.value = mode
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
    if (event.type !== 'message.created') return
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
    const [selectionLoaded] = await Promise.all([
      refreshWorkspace(true),
      loadAgentRuntimeStatus(),
      loadAgentCatalog(),
    ])
    loading.value = false
    if (selectedConversation.value && !selectionLoaded) {
      await loadConversationMessages(selectedConversation.value)
    }
  }

  watch([theme, resolvedTheme], applyTheme, { immediate: true })
  watch(
    [
      () => selectedAgentScope.value?.accountId,
      () => selectedAgentScope.value?.conversationId,
    ],
    ([accountId, conversationId]) => void loadAgentPolicy(
      accountId && conversationId ? { accountId, conversationId } : undefined,
    ),
    { immediate: true },
  )
  onMounted(async () => {
    colorSchemeQuery = window.matchMedia?.('(prefers-color-scheme: dark)')
    colorSchemeQuery?.addEventListener('change', updateSystemTheme)
    window.addEventListener('focus', refreshAgentRuntimeWhenVisible)
    document.addEventListener('visibilitychange', refreshAgentRuntimeWhenVisible)
    agentStatusTimer = setInterval(refreshAgentRuntimeWhenVisible, 12_000)
    unsubscribe = adapter.subscribe((event) => {
      if (!initialLoadComplete) {
        initialWorkspaceEvents.push(event)
        return
      }
      void handleWorkspaceEvent(event)
    })
    await load()
    while (initialWorkspaceEvents.length > 0) {
      const event = initialWorkspaceEvents.shift()
      if (event) await handleWorkspaceEvent(event)
    }
    initialLoadComplete = true
  })
  onBeforeUnmount(() => {
    unsubscribe?.()
    window.removeEventListener('focus', refreshAgentRuntimeWhenVisible)
    document.removeEventListener('visibilitychange', refreshAgentRuntimeWhenVisible)
    if (agentStatusTimer) clearInterval(agentStatusTimer)
    if (colorSchemeQuery) {
      colorSchemeQuery.removeEventListener('change', updateSystemTheme)
    }
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
    drafts,
    chatHistory,
    chatUnread,
    mentionCandidates,
    replyToMessage,
    conversationSessions,
    selectedSession,
    selectedSessionId,
    agentMessages,
    selectedRun,
    agentCatalog,
    agentCatalogError,
    agentPolicy,
    agentPolicyLoading,
    agentPolicySaving,
    agentPolicyError,
    answerProfileHint,
    get agentContextMessages() {
      return maxAgentContextMessages()
    },
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
    resolvedTheme,
    totalUnread,
    onlineCount,
    agentAvailable,
    agentRuntimeStatus,
    agentRuntimeError,
    agentRuntimeLoading,
    agentPromptSending,
    runtime: computed(() => snapshot.value.runtime),
    selectAccount,
    selectConversation,
    selectDefaultConversation,
    openConversation,
    selectSession,
    setAnswerProfile,
    updateAgentPolicy,
    openAgent,
    toggleAgent,
    sendChat,
    loadCustomFaces,
    sendCustomFace,
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
    saveAgentPolicy,
    toggleTheme,
    setTheme,
    load,
    refreshAgentRuntimeStatus: loadAgentRuntimeStatus,
    notify,
  }
}

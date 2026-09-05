import type {
  AccountCapabilityDocument,
  AccountDirectory,
  ChatMessage,
  Conversation,
  ConversationDraft,
  CustomFaceCatalog,
  EssencePage,
  FileSendReceipt,
  ForwardedMessageBundle,
  GroupAnnouncement,
  GroupFilePage,
  GroupMemberDirectory,
  HistoryPage,
  NotificationInbox,
  OutgoingMessageSegment,
  QqNotification,
  UploadReceipt,
  WorkspaceEvent,
  WorkspaceSnapshot,
} from '../types/workspace'
import {
  workspaceCache,
  type MessageSearchPage,
  type MessageSearchRequest,
  type WorkspaceCache,
} from './database'

export interface HistoryRequest {
  limit?: number
  before?: string
  after?: string
  signal?: AbortSignal
  cacheRequired?: boolean
}

export interface WorkspaceAdapter {
  load(force?: boolean): Promise<WorkspaceSnapshot>
  loadCapabilities(accountId: string): Promise<AccountCapabilityDocument>
  loadDirectory(accountId: string, refresh?: boolean): Promise<AccountDirectory>
  loadNotifications(accountId: string, refresh?: boolean): Promise<NotificationInbox>
  loadCustomFaces(conversation: Conversation): Promise<CustomFaceCatalog>
  loadCachedNotifications?(accountId: string): Promise<QqNotification[]>
  cacheNotifications?(accountId: string, notifications: QqNotification[]): Promise<void>
  resolveNotification(accountId: string, notificationId: string, action: 'accept' | 'reject'): Promise<QqNotification>
  loadGroupMembers(accountId: string, groupId: string, refresh?: boolean): Promise<GroupMemberDirectory>
  setGroupAdmin(accountId: string, groupId: string, userId: string, enabled: boolean): Promise<void>
  kickGroupMember(accountId: string, groupId: string, userId: string): Promise<void>
  setGroupCard(accountId: string, groupId: string, userId: string, card: string): Promise<void>
  renameGroup(accountId: string, groupId: string, name: string): Promise<void>
  setGroupMuteAll(accountId: string, groupId: string, enabled: boolean): Promise<void>
  quitGroup(accountId: string, groupId: string): Promise<void>
  loadEssence(accountId: string, groupId: string): Promise<EssencePage>
  loadAnnouncements(accountId: string, groupId: string): Promise<GroupAnnouncement[]>
  deleteAnnouncement(accountId: string, groupId: string, announcementId: string): Promise<void>
  loadGroupFiles(accountId: string, groupId: string, parentId?: string): Promise<GroupFilePage>
  loadGroupFileUrl(accountId: string, groupId: string, fileId: string, fileName: string): Promise<string>
  uploadGroupFile(accountId: string, groupId: string, parentId: string, file: File): Promise<FileSendReceipt>
  moveGroupFile(
    accountId: string,
    groupId: string,
    fileId: string,
    currentParentId: string,
    targetParentId: string,
  ): Promise<void>
  renameGroupFile(
    accountId: string,
    groupId: string,
    fileId: string,
    currentParentId: string,
    name: string,
  ): Promise<void>
  deleteGroupFile(accountId: string, groupId: string, fileId: string): Promise<void>
  createGroupFolder(accountId: string, groupId: string, name: string): Promise<void>
  deleteGroupFolder(accountId: string, groupId: string, folderId: string): Promise<void>
  loadCachedMessages(conversation: Conversation, limit?: number): Promise<ChatMessage[]>
  loadHistory(conversation: Conversation, request?: HistoryRequest): Promise<HistoryPage>
  loadMessages(conversation: Conversation, limit?: number): Promise<ChatMessage[]>
  sendSegments(conversation: Conversation, segments: OutgoingMessageSegment[]): Promise<ChatMessage>
  sendMessage(conversation: Conversation, content: string): Promise<ChatMessage>
  stageMedia(conversation: Conversation, file: File): Promise<UploadReceipt>
  sendFile(conversation: Conversation, file: File): Promise<FileSendReceipt>
  recallMessage(conversation: Conversation, message: ChatMessage): Promise<void>
  refreshMessage(conversation: Conversation, message: ChatMessage): Promise<ChatMessage>
  forwardMessage(message: ChatMessage, source: Conversation, target: Conversation): Promise<void>
  loadForwarded(conversation: Conversation, forwardId: string): Promise<ForwardedMessageBundle>
  loadFileUrl(conversation: Conversation, fileId: string, fileName?: string): Promise<string>
  nudge(conversation: Conversation, userId: string): Promise<void>
  loadDraft(conversation: Conversation): Promise<ConversationDraft | undefined>
  saveDraft(draft: ConversationDraft): Promise<void>
  searchMessages(request: MessageSearchRequest): Promise<MessageSearchPage>
  cacheMessages(conversation: Conversation, messages: ChatMessage[]): Promise<void>
  deleteCachedMessage(accountId: string, conversationId: string, messageId: string): Promise<void>
  markRead(conversation: Conversation): Promise<void>
  subscribe(handler: (event: WorkspaceEvent) => void): () => void
}

interface SendMessageResponse {
  message: ChatMessage
}

export class NapCatWorkspaceAdapter implements WorkspaceAdapter {
  constructor(
    private readonly baseUrl = '',
    private readonly cache: WorkspaceCache = workspaceCache,
  ) {}

  async load(force = false): Promise<WorkspaceSnapshot> {
    const snapshot = await this.request<WorkspaceSnapshot>(`/api/workspace${force ? '?refresh=1' : ''}`, {
      signal: AbortSignal.timeout(10_000),
    }).catch((error: unknown) => {
      if (error instanceof Error && error.name === 'TimeoutError') {
        throw new Error('连接工作台超时，请检查网关服务后重新检测')
      }
      throw error
    })
    await Promise.allSettled(snapshot.conversations.map((conversation) => this.cache.saveConversation(conversation)))
    return snapshot
  }

  async loadCapabilities(accountId: string): Promise<AccountCapabilityDocument> {
    return this.request<AccountCapabilityDocument>(`/api/accounts/${encodeURIComponent(accountId)}/capabilities`)
  }

  async loadDirectory(accountId: string, refresh = false): Promise<AccountDirectory> {
    return this.request<AccountDirectory>(
      `/api/accounts/${encodeURIComponent(accountId)}/directory?refresh=${refresh ? '1' : '0'}`,
    )
  }

  async loadNotifications(accountId: string, refresh = false): Promise<NotificationInbox> {
    return this.request<NotificationInbox>(
      `/api/accounts/${encodeURIComponent(accountId)}/notifications?refresh=${refresh ? '1' : '0'}`,
    )
  }

  async loadCustomFaces(conversation: Conversation): Promise<CustomFaceCatalog> {
    return this.request<CustomFaceCatalog>(`${this.conversationPath(conversation)}/custom-faces`)
  }

  async loadCachedNotifications(accountId: string): Promise<QqNotification[]> {
    return this.cache.cachedNotifications(accountId).catch(() => [])
  }

  async cacheNotifications(accountId: string, notifications: QqNotification[]): Promise<void> {
    await this.cache.saveNotifications(accountId, notifications)
  }

  async resolveNotification(
    accountId: string,
    notificationId: string,
    action: 'accept' | 'reject',
  ): Promise<QqNotification> {
    const result = await this.request<{ notification: QqNotification }>(
      `/api/accounts/${encodeURIComponent(accountId)}/notifications/${encodeURIComponent(notificationId)}/resolve`,
      {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ action }),
      },
    )
    return result.notification
  }

  async loadGroupMembers(accountId: string, groupId: string, refresh = false): Promise<GroupMemberDirectory> {
    return this.request<GroupMemberDirectory>(
      `${this.groupPath(accountId, groupId)}/members?refresh=${refresh ? '1' : '0'}`,
    )
  }

  async setGroupAdmin(accountId: string, groupId: string, userId: string, enabled: boolean): Promise<void> {
    await this.jsonMutation(`${this.groupPath(accountId, groupId)}/members/${encodeURIComponent(userId)}/admin`, 'PUT', {
      enabled,
    })
  }

  async kickGroupMember(accountId: string, groupId: string, userId: string): Promise<void> {
    await this.request(`${this.groupPath(accountId, groupId)}/members/${encodeURIComponent(userId)}`, { method: 'DELETE' })
  }

  async setGroupCard(accountId: string, groupId: string, userId: string, card: string): Promise<void> {
    await this.jsonMutation(`${this.groupPath(accountId, groupId)}/members/${encodeURIComponent(userId)}/card`, 'PUT', {
      card,
    })
  }

  async renameGroup(accountId: string, groupId: string, name: string): Promise<void> {
    await this.jsonMutation(this.groupPath(accountId, groupId), 'PATCH', { name })
  }

  async setGroupMuteAll(accountId: string, groupId: string, enabled: boolean): Promise<void> {
    await this.jsonMutation(`${this.groupPath(accountId, groupId)}/mute-all`, 'PUT', { enabled })
  }

  async quitGroup(accountId: string, groupId: string): Promise<void> {
    await this.request(this.groupPath(accountId, groupId), { method: 'DELETE' })
  }

  async loadEssence(accountId: string, groupId: string): Promise<EssencePage> {
    return this.request<EssencePage>(`${this.groupPath(accountId, groupId)}/essence`)
  }

  async loadAnnouncements(accountId: string, groupId: string): Promise<GroupAnnouncement[]> {
    return this.request<GroupAnnouncement[]>(`${this.groupPath(accountId, groupId)}/announcements`)
  }

  async deleteAnnouncement(accountId: string, groupId: string, announcementId: string): Promise<void> {
    await this.request(`${this.groupPath(accountId, groupId)}/announcements/${encodeURIComponent(announcementId)}`, {
      method: 'DELETE',
    })
  }

  async loadGroupFiles(accountId: string, groupId: string, parentId = '/'): Promise<GroupFilePage> {
    const search = new URLSearchParams({ parentId, limit: '500' })
    return this.request<GroupFilePage>(`${this.groupPath(accountId, groupId)}/files?${search.toString()}`)
  }

  async loadGroupFileUrl(accountId: string, groupId: string, fileId: string, fileName: string): Promise<string> {
    const search = new URLSearchParams({ name: fileName })
    const result = await this.request<{ url: string }>(
      `${this.groupPath(accountId, groupId)}/files/${encodeURIComponent(fileId)}/url?${search.toString()}`,
    )
    return result.url
  }

  async uploadGroupFile(
    accountId: string,
    groupId: string,
    parentId: string,
    file: File,
  ): Promise<FileSendReceipt> {
    const body = new FormData()
    body.append('file', file, file.name)
    const search = new URLSearchParams({ parentId })
    return this.request<FileSendReceipt>(`${this.groupPath(accountId, groupId)}/files/uploads?${search.toString()}`, {
      method: 'POST',
      body,
    })
  }

  async moveGroupFile(
    accountId: string,
    groupId: string,
    fileId: string,
    currentParentId: string,
    targetParentId: string,
  ): Promise<void> {
    await this.jsonMutation(`${this.groupPath(accountId, groupId)}/files/${encodeURIComponent(fileId)}`, 'PATCH', {
      operation: 'move',
      currentParentId,
      targetParentId,
    })
  }

  async renameGroupFile(
    accountId: string,
    groupId: string,
    fileId: string,
    currentParentId: string,
    name: string,
  ): Promise<void> {
    await this.jsonMutation(`${this.groupPath(accountId, groupId)}/files/${encodeURIComponent(fileId)}`, 'PATCH', {
      operation: 'rename',
      currentParentId,
      name,
    })
  }

  async deleteGroupFile(accountId: string, groupId: string, fileId: string): Promise<void> {
    await this.request(`${this.groupPath(accountId, groupId)}/files/${encodeURIComponent(fileId)}`, { method: 'DELETE' })
  }

  async createGroupFolder(accountId: string, groupId: string, name: string): Promise<void> {
    await this.jsonMutation(`${this.groupPath(accountId, groupId)}/folders`, 'POST', { name })
  }

  async deleteGroupFolder(accountId: string, groupId: string, folderId: string): Promise<void> {
    await this.request(`${this.groupPath(accountId, groupId)}/folders/${encodeURIComponent(folderId)}`, { method: 'DELETE' })
  }

  async loadCachedMessages(conversation: Conversation, limit = 50): Promise<ChatMessage[]> {
    return this.cache.recentMessages(conversation.accountId, conversation.id, limit).catch(() => [])
  }

  async loadHistory(conversation: Conversation, request: HistoryRequest = {}): Promise<HistoryPage> {
    const cacheGeneration = this.cache.captureWriteGeneration(conversation.accountId)
    const search = new URLSearchParams()
    search.set('limit', String(Math.min(Math.max(request.limit ?? 50, 1), 100)))
    if (request.before) search.set('before', request.before)
    if (request.after) search.set('after', request.after)
    const page = await this.request<HistoryPage>(`${this.conversationPath(conversation)}/messages?${search.toString()}`, {
      signal: request.signal,
    })
    const direction = request.before ? 'before' : request.after ? 'after' : 'initial'
    if (request.cacheRequired) {
      const receipt = await this.cache.saveHistoryPage(conversation, page, direction, cacheGeneration)
      if (receipt.persistedMessageCount < receipt.requestedMessageCount || !receipt.coverageRetained) {
        throw new Error('本地缓存已达到有界上限，本页历史未被完整保留')
      }
    } else await this.cache.saveHistoryPage(conversation, page, direction, cacheGeneration).catch(() => undefined)
    return page
  }

  async loadMessages(conversation: Conversation, limit = 50): Promise<ChatMessage[]> {
    return (await this.loadHistory(conversation, { limit })).messages
  }

  async sendSegments(conversation: Conversation, segments: OutgoingMessageSegment[]): Promise<ChatMessage> {
    const result = await this.request<SendMessageResponse>(`${this.conversationPath(conversation)}/messages`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ segments }),
    })
    return result.message
  }

  async sendMessage(conversation: Conversation, content: string): Promise<ChatMessage> {
    const result = await this.request<SendMessageResponse>(`${this.conversationPath(conversation)}/messages`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ content }),
    })
    return result.message
  }

  async stageMedia(conversation: Conversation, file: File): Promise<UploadReceipt> {
    return this.upload<UploadReceipt>(conversation, file, 'media')
  }

  async sendFile(conversation: Conversation, file: File): Promise<FileSendReceipt> {
    return this.upload<FileSendReceipt>(conversation, file, 'file')
  }

  async recallMessage(conversation: Conversation, message: ChatMessage): Promise<void> {
    await this.request<{ ok: true }>(
      `${this.conversationPath(conversation)}/messages/${encodeURIComponent(message.messageId)}`,
      { method: 'DELETE' },
    )
    await this.cache.deleteMessage(conversation.accountId, conversation.id, message.id).catch(() => undefined)
  }

  async refreshMessage(conversation: Conversation, message: ChatMessage): Promise<ChatMessage> {
    const result = await this.request<SendMessageResponse>(
      `${this.conversationPath(conversation)}/messages/${encodeURIComponent(message.messageId)}`,
    )
    return result.message
  }

  async forwardMessage(message: ChatMessage, source: Conversation, target: Conversation): Promise<void> {
    await this.request<{ messageId?: string }>(
      `${this.conversationPath(source)}/messages/${encodeURIComponent(message.messageId)}/forward`,
      {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          target: { accountId: target.accountId, type: target.type, peerId: target.peerId },
        }),
      },
    )
  }

  async loadForwarded(conversation: Conversation, forwardId: string): Promise<ForwardedMessageBundle> {
    return this.request<ForwardedMessageBundle>(
      `${this.conversationPath(conversation)}/forwards/${encodeURIComponent(forwardId)}`,
    )
  }

  async loadFileUrl(conversation: Conversation, fileId: string, fileName?: string): Promise<string> {
    const search = new URLSearchParams()
    if (fileName) search.set('name', fileName)
    const result = await this.request<{ url: string }>(
      `${this.conversationPath(conversation)}/files/${encodeURIComponent(fileId)}/url?${search.toString()}`,
    )
    return result.url
  }

  async nudge(conversation: Conversation, userId: string): Promise<void> {
    await this.request<{ ok: true }>(`${this.conversationPath(conversation)}/nudge`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ userId }),
    })
  }

  async loadDraft(conversation: Conversation): Promise<ConversationDraft | undefined> {
    return this.cache.draft(conversation.accountId, conversation.id).catch(() => undefined)
  }

  async saveDraft(draft: ConversationDraft): Promise<void> {
    await this.cache.saveDraft(draft).catch(() => undefined)
  }

  async searchMessages(request: MessageSearchRequest): Promise<MessageSearchPage> {
    return this.cache.searchMessages(request).catch(() => ({ messages: [], hasMore: false }))
  }

  async cacheMessages(conversation: Conversation, messages: ChatMessage[]): Promise<void> {
    await this.cache.saveMessages(conversation, messages).catch(() => undefined)
  }

  async deleteCachedMessage(accountId: string, conversationId: string, messageId: string): Promise<void> {
    await this.cache.deleteMessage(accountId, conversationId, messageId).catch(() => undefined)
  }

  async markRead(conversation: Conversation): Promise<void> {
    await this.request<{ ok: true }>(`${this.conversationPath(conversation)}/read`, { method: 'POST' })
  }

  subscribe(handler: (event: WorkspaceEvent) => void): () => void {
    if (typeof EventSource === 'undefined') return () => undefined
    const source = new EventSource(`${this.baseUrl}/api/events`)
    const onEvent = (event: MessageEvent<string>) => {
      try {
        handler(JSON.parse(event.data) as WorkspaceEvent)
      } catch {
        // Ignore malformed events; the next workspace refresh repairs state.
      }
    }
    source.addEventListener('workspace', onEvent as EventListener)
    return () => source.close()
  }

  private conversationPath(conversation: Conversation): string {
    return `/api/accounts/${encodeURIComponent(conversation.accountId)}/conversations/${conversation.type}/${encodeURIComponent(conversation.peerId)}`
  }

  private groupPath(accountId: string, groupId: string): string {
    return `/api/accounts/${encodeURIComponent(accountId)}/groups/${encodeURIComponent(groupId)}`
  }

  private async jsonMutation(
    path: string,
    method: 'POST' | 'PUT' | 'PATCH',
    body: Record<string, unknown>,
  ): Promise<void> {
    await this.request(path, {
      method,
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    })
  }

  private async upload<T>(conversation: Conversation, file: File, purpose: 'media' | 'file'): Promise<T> {
    const body = new FormData()
    body.append('file', file, file.name)
    return this.request<T>(`${this.conversationPath(conversation)}/uploads?purpose=${purpose}`, {
      method: 'POST',
      body,
    })
  }

  private async request<T>(path: string, init?: RequestInit): Promise<T> {
    const response = await fetch(`${this.baseUrl}${path}`, {
      ...init,
      headers: {
        Accept: 'application/json',
        ...init?.headers,
      },
    })
    const body = (await response.json().catch(() => ({}))) as { error?: string }
    if (!response.ok) throw new Error(body.error || `请求失败: ${response.status}`)
    return body as T
  }
}

export const workspaceAdapter: WorkspaceAdapter = new NapCatWorkspaceAdapter()

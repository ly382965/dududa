import type { WorkspaceAdapter } from './workspace-adapter'
import type { Conversation } from '../types/workspace'

export interface HistoryBackfillProgress {
  completedConversations: number
  totalConversations: number
  fetchedMessages: number
  coveredMessages: number
  failedConversations: number
  truncatedConversations: number
  truncations: Array<{ conversationId: string; reason: string }>
  activeConversationId?: string
  cancelled: boolean
}

export interface HistoryBackfillLimits {
  maxPagesPerConversation?: number
  maxMessagesPerConversation?: number
}

const defaultMaxPagesPerConversation = 200
const defaultMaxMessagesPerConversation = 20_000

export async function backfillHistory(
  conversations: Conversation[],
  startTimeMs: number,
  endTimeMs: number,
  signal: AbortSignal,
  onProgress: (progress: HistoryBackfillProgress) => void,
  adapter: WorkspaceAdapter,
  limits: HistoryBackfillLimits = {},
): Promise<HistoryBackfillProgress> {
  if (new Set(conversations.map((conversation) => conversation.accountId)).size > 1) {
    throw new Error('历史补齐不能跨 QQ 账号执行')
  }
  const progress: HistoryBackfillProgress = {
    completedConversations: 0,
    totalConversations: conversations.length,
    fetchedMessages: 0,
    coveredMessages: 0,
    failedConversations: 0,
    truncatedConversations: 0,
    truncations: [],
    cancelled: false,
  }
  const maxPagesPerConversation = Math.max(1, Math.floor(limits.maxPagesPerConversation ?? defaultMaxPagesPerConversation))
  const maxMessagesPerConversation = Math.max(
    1,
    Math.floor(limits.maxMessagesPerConversation ?? defaultMaxMessagesPerConversation),
  )
  onProgress({ ...progress })
  for (const conversation of conversations) {
    if (signal.aborted) {
      progress.cancelled = true
      break
    }
    progress.activeConversationId = conversation.id
    onProgress({ ...progress })
    let before: string | undefined
    let fetchedForConversation = 0
    const seenCursors = new Set<string>()
    const seenMessageIds = new Set<string>()
    try {
      let completed = false
      let truncationReason = ''
      for (let pageNumber = 0; pageNumber < maxPagesPerConversation; pageNumber += 1) {
        if (signal.aborted) throw new DOMException('历史补齐已取消', 'AbortError')
        const remaining = maxMessagesPerConversation - fetchedForConversation
        if (remaining <= 0) {
          truncationReason = `达到每个会话 ${maxMessagesPerConversation.toLocaleString()} 条的本地补齐上限`
          break
        }
        const page = await adapter.loadHistory(conversation, {
          limit: Math.min(100, remaining),
          before,
          signal,
          cacheRequired: true,
        })
        if (signal.aborted) throw new DOMException('历史补齐已取消', 'AbortError')
        const uniqueMessages = page.messages.filter((message) => {
          if (seenMessageIds.has(message.id)) return false
          seenMessageIds.add(message.id)
          return true
        })
        progress.fetchedMessages += uniqueMessages.length
        fetchedForConversation += uniqueMessages.length
        progress.coveredMessages += uniqueMessages.filter(
          (message) =>
            (message.timestampMs ?? 0) >= startTimeMs &&
            (message.timestampMs ?? 0) <= endTimeMs,
        ).length
        onProgress({ ...progress })
        const oldest = page.messages.reduce(
          (value, message) => Math.min(value, message.timestampMs ?? Number.POSITIVE_INFINITY),
          Number.POSITIVE_INFINITY,
        )
        if (
          !page.hasMoreBefore ||
          oldest <= startTimeMs
        ) {
          completed = true
          break
        }
        if (fetchedForConversation >= maxMessagesPerConversation) {
          truncationReason = `达到每个会话 ${maxMessagesPerConversation.toLocaleString()} 条的本地补齐上限`
          break
        }
        const next = page.beforeCursor
        if (!next || next === before || seenCursors.has(next)) throw new Error('NapCat 历史游标没有继续前进')
        seenCursors.add(next)
        before = next
        if (pageNumber + 1 >= maxPagesPerConversation) {
          truncationReason = `达到每个会话 ${maxPagesPerConversation.toLocaleString()} 页的本地补齐上限`
        }
      }
      if (completed) progress.completedConversations += 1
      else if (truncationReason) {
        progress.truncatedConversations += 1
        progress.truncations.push({ conversationId: conversation.id, reason: truncationReason })
      } else {
        progress.failedConversations += 1
      }
    } catch (cause) {
      if (signal.aborted || (cause instanceof DOMException && cause.name === 'AbortError')) {
        progress.cancelled = true
        break
      }
      progress.failedConversations += 1
    }
    onProgress({ ...progress })
  }
  progress.activeConversationId = undefined
  onProgress({ ...progress })
  return progress
}

/** Preview evidence, not authority to send a message or change Runtime policy. */
export type PreviewOutcome = 'response' | 'no_reply' | 'deferred' | 'failed' | 'reaction' | 'empty'

export interface PreviewEvidence {
  outcome?: PreviewOutcome
  runtimeState?: string
  generationObserved?: boolean
}

export interface PreviewCoverage {
  source: 'server_recent' | 'synthetic' | 'unavailable'
  partial: true
  truncated: boolean
  historyMessagesRead: number
  oldestAt: string | null
  newestAt: string | null
}

export interface PreviewHistoryMessage {
  id: string
  senderId: string
  senderName: string
  content: string
  timestamp: string | null
  replyToId?: string
}

export interface PreviewHistory {
  accountId: string
  conversationId: string
  source: 'server_recent' | 'synthetic'
  messages: PreviewHistoryMessage[]
  truncated: boolean
}

export type InternalTestTier = 'haiku' | 'sonnet' | 'opus'
export type InternalTestAnswerProfile = 'short' | 'medium' | 'long'
export type InternalTestVerdict = 'accepted' | 'rejected' | 'needs_review'

export interface InternalTestPrediction<T> {
  label: T
  confidence: number
}

export interface InternalTestMessage {
  message_ref: string
  sender_ref: string
  text: string
  reply_to_ref?: string | null
  mention_refs?: string[]
  attachment_kinds?: string[]
  self_authored?: boolean
}

export interface InternalTestSilver {
  need_tools: boolean
  semantic_complexity: string
  answer_profile: InternalTestAnswerProfile
  task_kind?: string
  coarse_topic?: string
  teacher_confidence?: number
  expected_tool_steps?: number
  capability_categories?: string[]
}

export interface InternalTestStudent {
  need_tools?: InternalTestPrediction<boolean>
  semantic_complexity?: InternalTestPrediction<string>
  answer_profile?: InternalTestPrediction<InternalTestAnswerProfile>
}

export interface InternalTestTierPreview {
  selected_tier?: InternalTestTier
  reason_codes?: string[]
  input_complexity?: string
  input_confidence?: number
  production_route?: false
  notice?: string
}

export interface InternalTestSample {
  window_id: string
  primary_bucket?: string
  buckets?: string[]
  message_count?: number
  speaker_count?: number
  messages: InternalTestMessage[]
  silver?: InternalTestSilver
  student?: InternalTestStudent
  complexity_assessment?: Record<string, unknown>
  semantic?: Record<string, unknown>
  tier_preview?: InternalTestTierPreview
  validation?: Record<string, boolean>
}

export interface InternalTestStatus {
  available: boolean
  evidenceMode: 'private_silver_shadow'
  outputEnabled: false
  providerConfigured: boolean
  sampleCount: number
  modelMapping?: Record<InternalTestTier, string>
  generatedAt?: string
  warnings: string[]
}

export interface InternalTestSamplesQuery {
  q?: string
  bucket?: string
  complexity?: string
  profile?: string
  tools?: string
  offset?: number
  limit?: number
}

export interface InternalTestSamplesPage {
  items: InternalTestSample[]
  total: number
  offset: number
  limit: number
}

export interface InternalTestProgress {
  total: number
  evaluated: number
  pending: number
  accepted: number
  rejected: number
  needsReview: number
}

export interface InternalTestCandidate {
  runId: string
  windowId: string
  candidate: string
  tier: InternalTestTier
  model: string
  answerProfile: InternalTestAnswerProfile
  latencyMs: number
  generatedAt: string
  evidenceMode: 'private_silver_shadow'
  providerCalls: 1
  outputCalls: 0
  memoryWrites: 0
  toolCalls: 0
}

export interface InternalTestFeedback {
  windowId: string
  runId: string
  verdict: InternalTestVerdict
  note?: string
  evaluation: {
    shouldReply: 'yes' | 'no' | 'uncertain'
    routingReasonable: number
    correctness: number
    naturalness: number
    groupFit: number
    lengthFit: number
  }
  corrected: {
    semanticComplexity?: string
    answerProfile?: InternalTestAnswerProfile
  }
}

export interface InternalTestFeedbackResult {
  ok: true
  feedbackId: string
  progress: InternalTestProgress
}

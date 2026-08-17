export type InternalTestTier = 'haiku' | 'sonnet' | 'opus'
export type InternalTestAnswerProfile = 'short' | 'medium' | 'long'
export type InternalTestSelectionMode = 'adaptive' | 'preferred' | 'locked'
export type InternalTestReasoningLevel = 'low' | 'medium' | 'high'
export type InternalTestPluginMode = 'off' | 'auto' | 'on' | 'locked'
export type InternalTestReplyIntensity = 'quiet' | 'normal' | 'active'
export type InternalTestContextLength = 'compact' | 'standard' | 'extended'
export type InternalTestGroupChatStyle = 'restrained' | 'natural' | 'lively' | 'technical'
export type InternalTestVerdict = 'accepted' | 'rejected' | 'needs_review'

export interface InternalTestAdaptiveSetting<T extends string> {
  mode: InternalTestSelectionMode
  preferred: T
  allowed: T[]
}

export interface InternalTestAgentScope {
  accountId: string
  conversationId: string
}

export interface InternalTestAgentPolicyDefaults {
  enabled: boolean
  modelTier: InternalTestAdaptiveSetting<InternalTestTier>
  reasoning: InternalTestAdaptiveSetting<InternalTestReasoningLevel>
  answerProfile: InternalTestAdaptiveSetting<InternalTestAnswerProfile>
  replyIntensity: InternalTestAdaptiveSetting<InternalTestReplyIntensity>
  contextLength: InternalTestAdaptiveSetting<InternalTestContextLength>
  groupChatStyle: InternalTestAdaptiveSetting<InternalTestGroupChatStyle>
  plugins: Record<string, InternalTestPluginMode>
}

export interface InternalTestAgentPolicy extends InternalTestAgentPolicyDefaults {
  schemaVersion: 1
  scope: InternalTestAgentScope
  updatedAt?: string
}

export interface InternalTestCatalogModel {
  id: string
  tier: InternalTestTier
  displayName: string
  available: boolean
  modalities: Array<'text'>
  reasoningLevels: InternalTestReasoningLevel[]
  unavailableReason?: string
}

export interface InternalTestCatalogPlugin {
  id: string
  displayName: string
  kind: 'mcp' | 'image_generation' | 'readonly_query' | 'social_automation'
  installed: boolean
  available: boolean
  builtIn?: boolean
  policyManaged: boolean
  requiredRole?: 'super_admin' | 'admin'
  executionRole?: 'admin'
  runtimeTarget: 'web_agent' | 'astrbot'
  runtimeReadiness: 'configured' | 'unavailable'
  executionKind: 'agent_capability' | 'command_auto_reply' | 'passive_behavior'
  description: string
  unavailableReason?: string
  model?: string
}

export interface InternalTestAgentCatalog {
  agent: {
    id: 'dududa'
    displayName: string
    consoleRole?: 'super_admin'
    executionRole?: 'admin'
  }
  selectionModes: InternalTestSelectionMode[]
  pluginModes: InternalTestPluginMode[]
  models: InternalTestCatalogModel[]
  reasoningLevels: InternalTestReasoningLevel[]
  answerProfiles: InternalTestAnswerProfile[]
  replyIntensities: InternalTestReplyIntensity[]
  contextLengths: Array<{
    id: InternalTestContextLength
    messageLimit: number
    characterLimit: number
  }>
  groupChatStyles: InternalTestGroupChatStyle[]
  replyIntensityNotice: string
  plugins: InternalTestCatalogPlugin[]
  policyDefaults: InternalTestAgentPolicyDefaults
}

export interface InternalTestEffectivePlugin {
  mode: InternalTestPluginMode
  available: boolean
  eligible: boolean
  selectedForRun: boolean
  applicable: boolean
  triggerMatched: boolean
  runtimeTarget: InternalTestCatalogPlugin['runtimeTarget']
  runtimeReadiness: InternalTestCatalogPlugin['runtimeReadiness']
  selectionReason: 'unavailable' | 'off' | 'not_applicable' | 'trigger_matched'
}

export interface InternalTestEffectiveSelection {
  scope: InternalTestAgentScope
  policySource: 'default' | 'saved'
  modelTier: InternalTestTier
  model: string
  reasoning: InternalTestReasoningLevel
  answerProfile: InternalTestAnswerProfile
  replyIntensity: InternalTestReplyIntensity
  contextLength: InternalTestContextLength
  groupChatStyle: InternalTestGroupChatStyle
  contextUsage: InternalTestContextUsage
  plugins: Record<string, InternalTestEffectivePlugin>
}

export interface InternalTestContextUsage {
  messageLimit: number
  characterLimit: number
  messagesRead: number
  charactersRead: number
}

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

export interface InternalTestAgentStatus {
  available: boolean
  outputEnabled: false
  providerConfigured: boolean
  modelMapping: Record<InternalTestTier, string>
  runtimeControls: {
    passiveAutoReply: {
      actualEnabled: false
      state: 'disabled'
      rolloutMode: 'off'
      deliveryEnabled: false
      killSwitch: true
      summary: string
    }
    proactiveGroupParticipation: {
      actualEnabled: false
      state: 'shadow'
      stage: 'probe_shadow'
      deliveryEnabled: false
      summary: string
    }
  }
  warnings: string[]
}

export interface InternalTestAgentContextMessage {
  senderName: string
  content: string
  mine: boolean
}

export interface InternalTestAgentRequest {
  accountId?: string
  scope?: InternalTestAgentScope
  conversationId: string
  conversationName: string
  conversationType: 'group' | 'private'
  prompt: string
  messages: InternalTestAgentContextMessage[]
  answerProfile?: InternalTestAnswerProfile
}

export interface InternalTestAgentResponse {
  runId: string
  candidate: string
  tier: InternalTestTier
  model: string
  reasoning: InternalTestReasoningLevel
  answerProfile: InternalTestAnswerProfile
  replyIntensity: InternalTestReplyIntensity
  contextLength: InternalTestContextLength
  groupChatStyle: InternalTestGroupChatStyle
  contextUsage: InternalTestContextUsage
  effectiveSelection: InternalTestEffectiveSelection
  reasonCodes: string[]
  latencyMs: number
  generatedAt: string
  outputCalls: 0
  memoryWrites: 0
  toolCalls: 0
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

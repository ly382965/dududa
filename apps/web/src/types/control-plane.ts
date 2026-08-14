export type GroupServiceStatus = 'active' | 'paused' | 'rolled_back' | 'revoked'
export type GroupServiceAction = 'activate' | 'update' | 'pause' | 'resume' | 'rollback'

export interface ControlPlaneScope {
  platform: string
  botId: string
  groupId: string
}

export interface PendingGroup {
  scope: ControlPlaneScope
  status: 'pending_profile' | 'preview_ready'
  revision: number
  firstSeenAt: string
  updatedAt: string
  previewId?: string
}

export interface PendingInbox {
  platform: string
  botId: string
  items: PendingGroup[]
  generatedAt: string
}

export interface ManagedGroup {
  onboarding: PendingGroup
  assignment: GroupServiceAssignment
}

export interface ManagedGroups {
  platform: string
  botId: string
  items: ManagedGroup[]
  generatedAt: string
}

export interface GroupServiceProfile {
  profileId: string
  revision: number
  displayName: string
  requestedServiceIds: string[]
  personaRef: string
  triggerPolicyRef: string
  responsePolicyRef: string
  modelBudgetPolicyRef: string
  memoryMode: 'off' | 'read' | 'manual_write'
  proactiveDefaultEnabled: false
  strictServices: boolean
}

export interface ProfileCatalog {
  revision: string
  profiles: GroupServiceProfile[]
  generatedAt: string
}

export interface ServiceResolution {
  serviceId: string
  eligible: boolean
  reasonCodes: string[]
}

export interface GroupServicePreview {
  previewId: string
  scope: ControlPlaneScope
  profileId: string
  profileRevision: number
  previewDigest: string
  onboardingRevision: number
  assignmentRevision?: number
  catalogRevision: string
  desiredServiceIds: string[]
  effectiveServiceIds: string[]
  resolutions: ServiceResolution[]
  expiresAt: string
}

export interface GroupServiceAssignment {
  scope: ControlPlaneScope
  assignmentRevision: number
  status: GroupServiceStatus
  profileId: string
  profileRevision: number
  desiredServiceIds: string[]
  effectiveServiceIds: string[]
  previousRevision?: number
  lastKnownGoodRevision: number
  activatedAt: string
}

export interface ControlPlaneReceipt {
  receiptId: string
  commandId: string
  action: string
  outcome: 'succeeded' | 'denied' | 'conflict' | 'failed'
  reasonCodes: string[]
  committedAt: string
}

export interface PreviewRequest {
  profileId: string
  profileRevision: number
  expectedOnboardingRevision: number
  expectedAssignmentRevision?: number
}

export interface PreviewResponse {
  preview: GroupServicePreview
  onboardingRevision: number
  receipt: ControlPlaneReceipt
}

export interface GroupServiceCommandRequest {
  action: GroupServiceAction
  expectedOnboardingRevision: number
  expectedAssignmentRevision?: number
  previewId?: string
  previewDigest?: string
  rollbackRevision?: number
}

export interface GroupServiceCommandResponse {
  assignment: GroupServiceAssignment
  receipt: ControlPlaneReceipt
}

export interface ControlPlaneStatus {
  available: boolean
  reason?: string
}

export type OperationalSurface =
  | 'runs'
  | 'model_router'
  | 'mcp_capability'
  | 'plugins'
  | 'memory'
  | 'proactive'

export type OperationalStatus = 'ready' | 'degraded' | 'off' | 'shadow' | 'unavailable'

export type OperationalEvidenceMode =
  | 'unavailable'
  | 'fixture'
  | 'offline'
  | 'shadow'
  | 'canary'
  | 'live'

export interface OperationalScope {
  platform: string
  botId: string
  groupId?: string
}

export interface OperationalFact {
  factId: string
  label: string
  status: OperationalStatus
  revision: string
  detail: string
  reasonCodes: string[]
  observedAt: string
}

export interface OperationalProjection {
  surface: OperationalSurface
  scope: OperationalScope
  revision: string
  evidenceMode: OperationalEvidenceMode
  status: OperationalStatus
  facts: OperationalFact[]
  reasonCodes: string[]
  observedAt: string
}

export interface GovernedMutationDescriptor {
  action: string
  displayName: string
  handlerId: string
  scopeKind: 'bot' | 'group'
  riskLevel: 'low' | 'medium' | 'high' | 'critical'
}

export interface GovernedOperationsProjection {
  scope: OperationalScope
  projections: OperationalProjection[]
  mutations: GovernedMutationDescriptor[]
  generatedAt: string
}

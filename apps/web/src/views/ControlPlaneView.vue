<script setup lang="ts">
import {
  Check,
  CircleAlert,
  CircleCheck,
  Eye,
  LoaderCircle,
  Pause,
  Play,
  RefreshCw,
  RotateCcw,
  ShieldCheck,
  SlidersHorizontal,
  UsersRound,
} from '@lucide/vue'
import { computed, ref, watch } from 'vue'

import {
  controlPlaneAdapter,
  type ControlPlaneAdapter,
} from '../services/control-plane'
import type {
  ControlPlaneReceipt,
  ControlPlaneStatus,
  GroupServiceAssignment,
  GroupServicePreview,
  ManagedGroups,
  PendingGroup,
  PendingInbox,
  ProfileCatalog,
} from '../types/control-plane'
import type { Account } from '../types/workspace'

const props = withDefaults(defineProps<{
  account?: Account
  adapter?: ControlPlaneAdapter
}>(), {
  adapter: () => controlPlaneAdapter,
})

const emit = defineEmits<{ notify: [message: string] }>()
const status = ref<ControlPlaneStatus>({ available: false })
const inbox = ref<PendingInbox>()
const managedGroups = ref<ManagedGroups>()
const catalog = ref<ProfileCatalog>()
const selectedGroupId = ref('')
const selectedProfileId = ref('')
const onboardingRevision = ref(0)
const preview = ref<GroupServicePreview>()
const assignment = ref<GroupServiceAssignment>()
const receipt = ref<ControlPlaneReceipt>()
const loading = ref(false)
const busyAction = ref('')
const error = ref('')
let loadGeneration = 0

interface GroupEntry {
  onboarding: PendingGroup
  assignment?: GroupServiceAssignment
}

const groupEntries = computed<GroupEntry[]>(() => [
  ...(inbox.value?.items.map((onboarding) => ({ onboarding })) ?? []),
  ...(managedGroups.value?.items ?? []),
])
const selectedEntry = computed(() =>
  groupEntries.value.find((item) => item.onboarding.scope.groupId === selectedGroupId.value),
)
const selectedGroup = computed(() => selectedEntry.value?.onboarding)
const selectedProfile = computed(() =>
  catalog.value?.profiles.find((profile) => profile.profileId === selectedProfileId.value),
)
const canRollback = computed(() => Boolean(
  assignment.value && assignment.value.lastKnownGoodRevision < assignment.value.assignmentRevision,
))
const primaryAction = computed<'activate' | 'update'>(() => assignment.value ? 'update' : 'activate')

const reasonLabels: Record<string, string> = {
  service_not_installed: '未安装',
  service_unhealthy: '健康检查未通过',
  service_not_granted: '未授权',
  service_rollout_blocked: '尚未开放',
  preview_ready: '预览已生成',
  activate_committed: '服务已激活',
  update_committed: '配置已更新',
  pause_committed: '服务已暂停',
  resume_committed: '服务已恢复',
  rollback_committed: '已回滚到稳定版本',
}

function reasonLabel(code: string): string {
  return reasonLabels[code] ?? code
}

function memoryLabel(mode: string): string {
  if (mode === 'read') return '只读'
  if (mode === 'manual_write') return '人工写入'
  return '关闭'
}

function formatTime(value: string): string {
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString('zh-CN', { hour12: false })
}

function clearSelectionState(entry?: GroupEntry): void {
  preview.value = undefined
  assignment.value = entry?.assignment
  receipt.value = undefined
  onboardingRevision.value = entry?.onboarding.revision ?? 0
  error.value = ''
}

function selectGroup(entry: GroupEntry): void {
  selectedGroupId.value = entry.onboarding.scope.groupId
  selectedProfileId.value = entry.assignment?.profileId || catalog.value?.profiles[0]?.profileId || ''
  clearSelectionState(entry)
}

async function load(): Promise<void> {
  const account = props.account
  const generation = ++loadGeneration
  inbox.value = undefined
  managedGroups.value = undefined
  catalog.value = undefined
  selectedGroupId.value = ''
  selectedProfileId.value = ''
  clearSelectionState()
  status.value = { available: false }
  if (!account) return
  loading.value = true
  try {
    const currentStatus = await props.adapter.status()
    if (generation !== loadGeneration) return
    status.value = currentStatus
    if (!currentStatus.available) return
    const [nextInbox, nextManagedGroups, nextCatalog] = await Promise.all([
      props.adapter.pendingInbox(account.id),
      props.adapter.managedGroups(account.id),
      props.adapter.profileCatalog(account.id),
    ])
    if (generation !== loadGeneration) return
    inbox.value = nextInbox
    managedGroups.value = nextManagedGroups
    catalog.value = nextCatalog
    selectedProfileId.value = nextCatalog.profiles[0]?.profileId ?? ''
    const first = groupEntries.value[0]
    if (first) selectGroup(first)
  } catch (cause) {
    if (generation !== loadGeneration) return
    error.value = cause instanceof Error ? cause.message : 'Control Plane 读取失败'
  } finally {
    if (generation === loadGeneration) loading.value = false
  }
}

async function createPreview(): Promise<void> {
  const account = props.account
  const group = selectedGroup.value
  const profile = selectedProfile.value
  if (!account || !group || !profile || busyAction.value) return
  busyAction.value = 'preview'
  preview.value = undefined
  receipt.value = undefined
  error.value = ''
  try {
    const response = await props.adapter.preview(account.id, group.scope.groupId, {
      profileId: profile.profileId,
      profileRevision: profile.revision,
      expectedOnboardingRevision: onboardingRevision.value,
      ...(assignment.value ? { expectedAssignmentRevision: assignment.value.assignmentRevision } : {}),
    })
    preview.value = response.preview
    receipt.value = response.receipt
    onboardingRevision.value = response.onboardingRevision
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : '服务预览失败'
  } finally {
    busyAction.value = ''
  }
}

async function applyPreview(): Promise<void> {
  const currentPreview = preview.value
  if (!currentPreview) return
  await runCommand(primaryAction.value, {
    previewId: currentPreview.previewId,
    previewDigest: currentPreview.previewDigest,
  })
}

async function runCommand(
  action: 'activate' | 'update' | 'pause' | 'resume' | 'rollback',
  fields: { previewId?: string; previewDigest?: string } = {},
): Promise<void> {
  const account = props.account
  const group = selectedGroup.value
  if (!account || !group || busyAction.value) return
  busyAction.value = action
  error.value = ''
  try {
    const expectedAssignmentRevision = assignment.value?.assignmentRevision
    const request = action === 'activate' || action === 'update'
      ? {
          action,
          expectedOnboardingRevision: onboardingRevision.value,
          ...(expectedAssignmentRevision ? { expectedAssignmentRevision } : {}),
          previewId: fields.previewId!,
          previewDigest: fields.previewDigest!,
        }
      : action === 'rollback'
        ? {
            action,
            expectedOnboardingRevision: onboardingRevision.value,
            expectedAssignmentRevision: expectedAssignmentRevision!,
            rollbackRevision: assignment.value!.lastKnownGoodRevision,
          }
        : {
            action,
            expectedOnboardingRevision: onboardingRevision.value,
            expectedAssignmentRevision: expectedAssignmentRevision!,
          }
    const response = await props.adapter.command(account.id, group.scope.groupId, request)
    assignment.value = response.assignment
    receipt.value = response.receipt
    if (action === 'activate' || action === 'update') preview.value = undefined
    emit('notify', response.receipt.reasonCodes.map(reasonLabel).join(' · '))
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : '群服务命令失败'
  } finally {
    busyAction.value = ''
  }
}

watch(() => props.account?.id, () => void load(), { immediate: true })
watch(selectedProfileId, () => {
  preview.value = undefined
  receipt.value = undefined
})
</script>

<template>
  <main class="control-plane-view">
    <header class="view-header">
      <div><small>BOT CONTROL PLANE</small><h1>群服务</h1></div>
      <button class="icon-button" type="button" title="刷新群服务" :disabled="loading" @click="load">
        <RefreshCw :class="{ spin: loading }" :size="17" />
      </button>
    </header>

    <div v-if="loading" class="page-state"><LoaderCircle class="spin" :size="25" />正在读取群服务</div>
    <div v-else-if="!status.available" class="page-state unavailable">
      <CircleAlert :size="26" />
      <strong>Control Plane 不可用</strong>
      <span>{{ status.reason || error || '后端未连接' }}</span>
    </div>
    <p v-else-if="error && !inbox" class="inline-error" role="alert">{{ error }}</p>

    <div v-else class="control-workspace">
      <aside class="pending-panel">
        <div class="panel-heading">
          <span><UsersRound :size="16" /><strong>待配置群</strong></span>
          <b>{{ groupEntries.length }}</b>
        </div>
        <div class="pending-list">
          <button
            v-for="entry in groupEntries"
            :key="entry.onboarding.scope.groupId"
            type="button"
            :class="{ active: selectedGroupId === entry.onboarding.scope.groupId }"
            @click="selectGroup(entry)"
          >
            <span class="group-mark"><UsersRound :size="16" /></span>
            <span><strong>群 {{ entry.onboarding.scope.groupId }}</strong><small>{{ entry.assignment ? entry.assignment.status : entry.onboarding.status === 'preview_ready' ? '预览待确认' : '等待选择服务' }}</small></span>
            <i>r{{ entry.assignment?.assignmentRevision || entry.onboarding.revision }}</i>
          </button>
          <div v-if="!groupEntries.length" class="empty-list"><CircleCheck :size="22" />当前账号没有群服务配置</div>
        </div>
      </aside>

      <section class="onboarding-detail">
        <div v-if="!selectedGroup" class="detail-state"><SlidersHorizontal :size="26" />未选择群</div>
        <template v-else>
          <header class="scope-header">
            <div><small>{{ selectedGroup.scope.platform.toUpperCase() }} · {{ selectedGroup.scope.botId }}</small><h2>群 {{ selectedGroup.scope.groupId }}</h2></div>
            <span :class="assignment?.status || selectedGroup.status">
              {{ assignment?.status || selectedGroup.status }}
            </span>
          </header>

          <section class="profile-section">
            <div class="section-heading"><ShieldCheck :size="17" /><span><strong>服务档案</strong><small>Catalog {{ catalog?.revision }}</small></span></div>
            <label class="profile-select">
              <select v-model="selectedProfileId" aria-label="群服务档案">
                <option v-for="profile in catalog?.profiles" :key="`${profile.profileId}:${profile.revision}`" :value="profile.profileId">
                  {{ profile.displayName }} · r{{ profile.revision }}
                </option>
              </select>
            </label>
            <dl v-if="selectedProfile" class="profile-facts">
              <div><dt>人格</dt><dd>{{ selectedProfile.personaRef }}</dd></div>
              <div><dt>Memory</dt><dd>{{ memoryLabel(selectedProfile.memoryMode) }}</dd></div>
              <div><dt>服务策略</dt><dd>{{ selectedProfile.strictServices ? '严格' : '允许降级' }}</dd></div>
              <div><dt>主动消息初值</dt><dd>关闭</dd></div>
            </dl>
            <button class="preview-button" type="button" :disabled="!selectedProfile || Boolean(busyAction)" @click="createPreview">
              <LoaderCircle v-if="busyAction === 'preview'" class="spin" :size="15" /><Eye v-else :size="15" />预览
            </button>
          </section>

          <section v-if="preview" class="diff-section" aria-label="服务生效差异">
            <div class="section-heading"><SlidersHorizontal :size="17" /><span><strong>Desired / Effective</strong><small>有效至 {{ formatTime(preview.expiresAt) }}</small></span></div>
            <div class="service-table">
              <div class="service-row service-row--header"><span>服务</span><span>Desired</span><span>Effective</span><span>结果</span></div>
              <div v-for="resolution in preview.resolutions" :key="resolution.serviceId" class="service-row">
                <strong>{{ resolution.serviceId }}</strong>
                <Check :size="14" />
                <Check v-if="resolution.eligible" class="eligible" :size="14" />
                <CircleAlert v-else class="excluded" :size="14" />
                <span :class="{ eligible: resolution.eligible, excluded: !resolution.eligible }">
                  {{ resolution.eligible ? '可用' : resolution.reasonCodes.map(reasonLabel).join(' · ') }}
                </span>
              </div>
            </div>
            <div class="commit-strip">
              <span><strong>{{ selectedProfile?.displayName }}</strong><small>{{ preview.effectiveServiceIds.length }} / {{ preview.desiredServiceIds.length }} 项服务可生效</small></span>
              <button class="primary" type="button" :disabled="Boolean(busyAction)" @click="applyPreview">
                <LoaderCircle v-if="busyAction === primaryAction" class="spin" :size="15" /><Play v-else :size="15" />
                {{ primaryAction === 'activate' ? '激活' : '更新' }}
              </button>
            </div>
          </section>

          <section v-if="assignment" class="assignment-section">
            <div class="section-heading"><CircleCheck :size="17" /><span><strong>当前 Assignment</strong><small>revision {{ assignment.assignmentRevision }} · LKG {{ assignment.lastKnownGoodRevision }}</small></span></div>
            <dl class="assignment-facts">
              <div><dt>状态</dt><dd>{{ assignment.status }}</dd></div>
              <div><dt>Profile</dt><dd>{{ assignment.profileId }} · r{{ assignment.profileRevision }}</dd></div>
              <div><dt>Desired</dt><dd>{{ assignment.desiredServiceIds.join(', ') }}</dd></div>
              <div><dt>Effective</dt><dd>{{ assignment.effectiveServiceIds.join(', ') || '无' }}</dd></div>
            </dl>
            <div class="lifecycle-actions">
              <button v-if="assignment.status === 'paused'" type="button" :disabled="Boolean(busyAction)" @click="runCommand('resume')"><Play :size="15" />恢复</button>
              <button v-else type="button" :disabled="Boolean(busyAction)" @click="runCommand('pause')"><Pause :size="15" />暂停</button>
              <button type="button" :disabled="!canRollback || Boolean(busyAction)" @click="runCommand('rollback')"><RotateCcw :size="15" />回滚</button>
            </div>
          </section>

          <p v-if="error" class="inline-error" role="alert">{{ error }}</p>
          <div v-if="receipt" class="receipt-strip" role="status">
            <CircleCheck v-if="receipt.outcome === 'succeeded'" :size="16" />
            <CircleAlert v-else :size="16" />
            <span><strong>{{ receipt.reasonCodes.map(reasonLabel).join(' · ') }}</strong><small>{{ receipt.receiptId }} · {{ formatTime(receipt.committedAt) }}</small></span>
          </div>
        </template>
      </section>
    </div>
  </main>
</template>

<style scoped>
.control-plane-view { display: flex; min-height: 0; flex: 1; flex-direction: column; overflow: hidden; background: var(--app-background); padding: 24px clamp(16px, 3vw, 38px) 34px; }
.view-header { display: flex; flex: 0 0 auto; align-items: center; justify-content: space-between; border-bottom: 1px solid var(--border); padding-bottom: 17px; }
.view-header small { color: var(--brand-strong); font-size: 9px; font-weight: 800; }
h1 { margin: 4px 0 0; color: var(--text); font-size: 22px; letter-spacing: 0; }
.control-workspace { display: grid; min-width: 0; min-height: 0; flex: 1; grid-template-columns: minmax(220px, 290px) minmax(0, 1fr); border-bottom: 1px solid var(--border); }
.pending-panel { min-height: 0; overflow-y: auto; border-right: 1px solid var(--border); background: var(--surface); }
.panel-heading { display: flex; height: 48px; align-items: center; justify-content: space-between; border-bottom: 1px solid var(--border); padding: 0 12px; }
.panel-heading span { display: flex; align-items: center; gap: 7px; color: var(--text); font-size: 11px; }
.panel-heading b { min-width: 21px; border-radius: 10px; color: var(--brand-strong); background: var(--brand-soft); padding: 3px 6px; font-size: 9px; text-align: center; }
.pending-list { display: grid; }
.pending-list > button { display: grid; min-width: 0; min-height: 64px; cursor: pointer; grid-template-columns: 34px minmax(0, 1fr) auto; align-items: center; gap: 8px; border: 0; border-bottom: 1px solid var(--border); color: inherit; background: transparent; padding: 8px 11px; text-align: left; }
.pending-list > button:hover { background: var(--surface-hover); }
.pending-list > button.active { box-shadow: inset 3px 0 var(--brand); background: var(--brand-soft); }
.group-mark { display: grid; width: 32px; height: 32px; place-items: center; border-radius: 6px; color: var(--brand-strong); background: var(--surface-muted); }
.pending-list button > span:nth-child(2) { display: grid; min-width: 0; gap: 3px; }
.pending-list strong, .pending-list small { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.pending-list strong { color: var(--text); font-size: 11px; }
.pending-list small, .pending-list i { color: var(--text-muted); font-size: 9px; font-style: normal; }
.empty-list, .detail-state, .page-state { display: grid; min-height: 220px; place-content: center; place-items: center; gap: 8px; color: var(--text-muted); font-size: 10px; text-align: center; }
.onboarding-detail { min-width: 0; min-height: 0; overflow-y: auto; padding: 0 clamp(14px, 2.5vw, 30px) 30px; }
.scope-header { display: flex; min-height: 72px; align-items: center; justify-content: space-between; gap: 16px; border-bottom: 1px solid var(--border); }
.scope-header small { color: var(--text-muted); font-size: 9px; }
.scope-header h2 { margin: 4px 0 0; color: var(--text); font-size: 17px; letter-spacing: 0; }
.scope-header > span { border-radius: 4px; color: var(--text-muted); background: var(--surface-muted); padding: 4px 7px; font-size: 9px; text-transform: uppercase; }
.scope-header > span.active, .scope-header > span.rolled_back { color: var(--success); background: var(--success-soft); }
.scope-header > span.paused { color: var(--warning); background: var(--warning-soft); }
.profile-section, .diff-section, .assignment-section { display: grid; grid-template-columns: minmax(170px, .55fr) minmax(260px, 1.45fr) auto; align-items: start; gap: 18px; border-bottom: 1px solid var(--border); padding: 18px 0; }
.diff-section, .assignment-section { grid-template-columns: minmax(170px, .55fr) minmax(0, 1.45fr); }
.section-heading { display: flex; align-items: flex-start; gap: 8px; color: var(--brand-strong); }
.section-heading span { display: grid; min-width: 0; gap: 3px; }
.section-heading strong { color: var(--text); font-size: 11px; }
.section-heading small { overflow-wrap: anywhere; color: var(--text-muted); font-size: 9px; line-height: 1.4; }
.profile-select select { width: 100%; min-width: 0; height: 35px; border: 1px solid var(--border); border-radius: 5px; color: var(--text); background: var(--surface); padding: 0 9px; font: inherit; font-size: 10px; }
.profile-facts, .assignment-facts { display: grid; grid-column: 2; margin: 0; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 1px; background: var(--border); }
.profile-facts div, .assignment-facts div { display: grid; min-width: 0; gap: 3px; background: var(--surface); padding: 9px 10px; }
dt { color: var(--text-muted); font-size: 9px; }
dd { min-width: 0; margin: 0; overflow-wrap: anywhere; color: var(--text); font-size: 10px; font-weight: 650; }
.preview-button, .commit-strip button, .lifecycle-actions button { display: flex; height: 35px; cursor: pointer; align-items: center; justify-content: center; gap: 5px; border: 1px solid var(--border); border-radius: 5px; color: var(--text-secondary); background: var(--surface); padding: 0 11px; font-size: 10px; }
.preview-button:disabled, .commit-strip button:disabled, .lifecycle-actions button:disabled { cursor: not-allowed; opacity: .5; }
.service-table { display: grid; min-width: 0; border: 1px solid var(--border); }
.service-row { display: grid; min-height: 36px; grid-template-columns: minmax(120px, 1fr) 70px 70px minmax(110px, 1fr); align-items: center; border-bottom: 1px solid var(--border); padding: 0 10px; color: var(--text-secondary); font-size: 9px; }
.service-row:last-child { border-bottom: 0; }
.service-row--header { min-height: 30px; color: var(--text-muted); background: var(--surface-muted); font-weight: 700; }
.service-row strong { overflow-wrap: anywhere; color: var(--text); font-size: 10px; }
.eligible { color: var(--success); }
.excluded { color: var(--warning); }
.commit-strip { display: flex; grid-column: 2; align-items: center; justify-content: flex-end; gap: 12px; }
.commit-strip > span { display: grid; min-width: 0; gap: 2px; text-align: right; }
.commit-strip strong { color: var(--text); font-size: 10px; }
.commit-strip small { color: var(--text-muted); font-size: 9px; }
.commit-strip button.primary { border-color: var(--brand); color: #fff; background: var(--brand); }
.assignment-facts { grid-column: 2; }
.lifecycle-actions { display: flex; grid-column: 2; justify-content: flex-end; gap: 7px; }
.inline-error { margin: 14px 0 0; border-left: 3px solid var(--danger); color: var(--danger); background: var(--danger-soft); padding: 8px 10px; font-size: 10px; }
.receipt-strip { display: flex; align-items: center; gap: 8px; margin-top: 14px; border-left: 3px solid var(--success); color: var(--success); background: var(--success-soft); padding: 8px 10px; }
.receipt-strip span { display: grid; min-width: 0; gap: 2px; }
.receipt-strip strong { color: var(--text); font-size: 10px; }
.receipt-strip small { overflow-wrap: anywhere; color: var(--text-muted); font-size: 9px; }
.page-state { min-height: 320px; }
.page-state strong { color: var(--text); font-size: 12px; }
.page-state span { color: var(--text-muted); font-size: 10px; }
.spin { animation: spin 850ms linear infinite; }
@keyframes spin { to { transform: rotate(360deg); } }
@media (max-width: 840px) {
  .control-plane-view { padding: 18px 13px 26px; }
  .control-workspace { grid-template-columns: minmax(0, 1fr); overflow-y: auto; }
  .pending-panel { max-height: 210px; border-right: 0; border-bottom: 1px solid var(--border); }
  .onboarding-detail { min-height: 400px; overflow: visible; padding: 0 2px 24px; }
  .profile-section, .diff-section, .assignment-section { grid-template-columns: minmax(0, 1fr); gap: 12px; }
  .profile-facts, .assignment-facts, .commit-strip, .lifecycle-actions { grid-column: 1; }
  .service-table { overflow-x: auto; }
  .service-row { min-width: 540px; }
}
</style>

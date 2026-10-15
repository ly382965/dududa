<script setup lang="ts">
import { Bell, Check, LoaderCircle, RefreshCw, UserRound, UsersRound, X } from '@lucide/vue'
import { computed, ref, watch } from 'vue'

import AppAvatar from '../components/AppAvatar.vue'
import { useQqDirectoryStore } from '../stores/qq-directory'
import type { Account, QqNotification } from '../types/workspace'

const props = defineProps<{ account?: Account }>()
const emit = defineEmits<{ notify: [message: string] }>()
const store = useQqDirectoryStore()
const tab = ref<'friend' | 'group'>('friend')
const busyId = ref('')
const inbox = computed(() => (props.account ? store.notificationInboxes[props.account.id] : undefined))
const requestKey = computed(() => `notifications:${props.account?.id ?? ''}`)
const loading = computed(() => Boolean(store.loading[requestKey.value]))
const error = computed(() => store.errors[requestKey.value] || '')
const items = computed(() =>
  (inbox.value?.items ?? []).filter((item) =>
    tab.value === 'friend' ? item.kind === 'friend-request' : item.kind !== 'friend-request',
  ),
)
const friendPending = computed(() =>
  (inbox.value?.items ?? []).filter((item) => item.kind === 'friend-request' && item.state === 'pending').length,
)
const groupPending = computed(() =>
  (inbox.value?.items ?? []).filter((item) => item.kind !== 'friend-request' && item.state === 'pending').length,
)

function title(item: QqNotification): string {
  if (item.kind === 'friend-request') return item.userName || item.userId
  return item.groupName || item.groupId || '群通知'
}

function description(item: QqNotification): string {
  const user = item.userName || item.userId
  const operator = item.operatorName || item.operatorId || ''
  if (item.kind === 'friend-request') return item.comment || `${user} 请求添加好友`
  if (item.kind === 'group-request') return `${user} 申请加入群聊${item.comment ? ` · ${item.comment}` : ''}`
  if (item.kind === 'group-invitation') return `${user} 邀请当前 QQ 加入群聊`
  if (item.kind === 'group-member-increase') return `${user} 加入群聊`
  if (item.kind === 'group-member-decrease') return operator ? `${user} 离开或被 ${operator} 移出群聊` : `${user} 离开群聊`
  return item.comment === 'set' ? `${user} 被设为管理员` : `${user} 的管理员身份发生变化`
}

function stateLabel(item: QqNotification): string {
  if (item.state === 'pending') return '待处理'
  if (item.state === 'accepted') return '已同意'
  if (item.state === 'rejected') return '已拒绝'
  return '已处理'
}

async function resolve(item: QqNotification, action: 'accept' | 'reject'): Promise<void> {
  if (!props.account || busyId.value) return
  const capability = props.account.capabilities?.[
    item.kind === 'friend-request' ? 'request.friend.resolve' : 'request.group.resolve'
  ]
  if (capability?.status !== 'supported') {
    emit('notify', capability?.reason || '当前 QQ 不支持处理该申请')
    return
  }
  busyId.value = item.id
  try {
    await store.resolveNotification(props.account.id, item.id, action)
  } catch (cause) {
    emit('notify', cause instanceof Error ? cause.message : '通知处理失败')
  } finally {
    busyId.value = ''
  }
}

watch(
  () => props.account?.id,
  (accountId) => {
    if (accountId) void store.loadNotifications(accountId, true)
  },
  { immediate: true },
)
</script>

<template>
  <main class="notifications-view">
    <header class="view-header">
      <div><small>REQUESTS & EVENTS</small><h1>通知</h1></div>
      <button
        class="icon-button"
        type="button"
        title="刷新通知"
        :disabled="loading || !account"
        @click="account && store.loadNotifications(account.id, true)"
      >
        <RefreshCw :class="{ spin: loading }" :size="17" />
      </button>
    </header>

    <div class="notification-tabs" role="tablist" aria-label="通知类型">
      <button :class="{ active: tab === 'friend' }" type="button" @click="tab = 'friend'">
        <UserRound :size="16" />好友申请 <b v-if="friendPending">{{ friendPending }}</b>
      </button>
      <button :class="{ active: tab === 'group' }" type="button" @click="tab = 'group'">
        <UsersRound :size="16" />群通知 <b v-if="groupPending">{{ groupPending }}</b>
      </button>
    </div>

    <p v-if="tab === 'friend' && inbox?.limitations.friendHistory" class="protocol-note">
      {{ inbox.limitations.friendHistory }}
    </p>
    <p v-if="error" class="inline-error" role="alert">{{ error }}</p>

    <div v-if="loading && !inbox" class="notification-state"><LoaderCircle class="spin" :size="24" />正在读取 NapCat 通知</div>
    <section v-else class="notification-list" :aria-label="tab === 'friend' ? '好友申请' : '群通知'">
      <article v-for="item in items" :key="item.id" class="notification-item">
        <AppAvatar
          :src="item.kind === 'friend-request' ? `/api/media/avatar/user/${item.userId}` : `/api/media/avatar/group/${item.groupId}`"
          :name="title(item)"
          size="md"
        />
        <div class="notification-copy">
          <strong>{{ title(item) }}</strong>
          <p>{{ description(item) }}</p>
          <small>{{ stateLabel(item) }}<template v-if="item.state === 'pending' && !item.actionable && item.actionReason"> · {{ item.actionReason }}</template></small>
        </div>
        <div v-if="item.actionable && item.state === 'pending'" class="request-actions">
          <button type="button" :disabled="Boolean(busyId)" @click="resolve(item, 'reject')">
            <LoaderCircle v-if="busyId === item.id" class="spin" :size="15" /><X v-else :size="15" />拒绝
          </button>
          <button class="primary" type="button" :disabled="Boolean(busyId)" @click="resolve(item, 'accept')">
            <Check :size="15" />同意
          </button>
        </div>
      </article>
      <div v-if="!items.length" class="notification-state"><Bell :size="27" />暂无{{ tab === 'friend' ? '好友申请' : '群通知' }}</div>
    </section>
  </main>
</template>

<style scoped>
.notifications-view { min-height: 0; overflow-y: auto; background: var(--app-background); padding: 24px clamp(16px, 3vw, 38px) 40px; }
.view-header { display: flex; align-items: center; justify-content: space-between; border-bottom: 1px solid var(--border); padding-bottom: 17px; }
.view-header small { color: var(--brand-strong); font-size: 9px; font-weight: 800; }
h1 { margin: 4px 0 0; color: var(--text); font-size: 22px; letter-spacing: 0; }
.notification-tabs { display: flex; gap: 4px; margin: 18px 0 12px; border-bottom: 1px solid var(--border); }
.notification-tabs button { display: flex; min-width: 130px; height: 38px; cursor: pointer; align-items: center; justify-content: center; gap: 7px; border: 0; border-bottom: 2px solid transparent; color: var(--text-muted); background: transparent; font-size: 11px; font-weight: 650; }
.notification-tabs button.active { border-bottom-color: var(--brand); color: var(--brand-strong); }
.notification-tabs b { min-width: 17px; border-radius: 9px; color: #fff; background: var(--danger); padding: 2px 4px; font-size: 8px; }
.protocol-note { margin: 0 0 10px; border-left: 3px solid var(--warning); color: var(--text-secondary); background: var(--warning-soft); padding: 8px 10px; font-size: 10px; }
.notification-list { border-top: 1px solid var(--border); }
.notification-item { display: grid; min-height: 78px; grid-template-columns: auto minmax(0, 1fr) auto; align-items: center; gap: 12px; border-bottom: 1px solid var(--border); background: var(--surface); padding: 11px 13px; }
.notification-copy { min-width: 0; }
.notification-copy strong { color: var(--text); font-size: 12px; }
.notification-copy p { margin: 4px 0; color: var(--text-secondary); font-size: 10px; line-height: 1.5; }
.notification-copy small { color: var(--text-muted); font-size: 9px; }
.request-actions { display: flex; gap: 6px; }
.request-actions button { display: flex; height: 34px; cursor: pointer; align-items: center; gap: 5px; border: 1px solid var(--border); border-radius: 5px; color: var(--text-secondary); background: var(--surface); padding: 0 10px; font-size: 10px; }
.request-actions button.primary { border-color: var(--brand); color: #fff; background: var(--brand); }
.request-actions button:disabled { cursor: wait; opacity: .55; }
.notification-state { display: grid; min-height: 220px; place-content: center; place-items: center; gap: 9px; color: var(--text-muted); font-size: 11px; }
.inline-error { border-left: 3px solid var(--danger); color: var(--danger); background: var(--danger-soft); padding: 8px 10px; font-size: 10px; }
.spin { animation: spin 850ms linear infinite; }
@keyframes spin { to { transform: rotate(360deg); } }
@media (max-width: 620px) {
  .notifications-view { padding: 18px 13px 28px; }
  .notification-tabs button { min-width: 0; flex: 1; }
  .notification-item { grid-template-columns: auto minmax(0, 1fr); }
  .request-actions { grid-column: 2; }
}
</style>

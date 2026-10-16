<script setup lang="ts">
import {
  Check,
  Folder,
  LoaderCircle,
  LogOut,
  Pencil,
  Settings2,
  ShieldCheck,
  ShieldOff,
  Trash2,
  UserMinus,
  Users,
  Volume2,
  VolumeX,
  X,
} from '@lucide/vue'
import { computed, ref, watch } from 'vue'

import { createSearchMatcher } from '../../services/search'
import { groupMemberDirectoryKey, useQqDirectoryStore } from '../../stores/qq-directory'
import type { Account, CapabilityName, GroupMember, GroupPermissions, OperationPermission } from '../../types/workspace'
import AppAvatar from '../AppAvatar.vue'
import GroupResourcesPanel from './GroupResourcesPanel.vue'

const props = defineProps<{
  open: boolean
  account?: Account
  groupId?: string
}>()
const emit = defineEmits<{ close: []; quit: []; notify: [message: string] }>()
const store = useQqDirectoryStore()
const tab = ref<'overview' | 'members' | 'resources'>('overview')
const query = ref('')
const sort = ref<'default' | 'join' | 'last'>('default')
const busyUserId = ref('')
const busyAction = ref('')
const prompt = ref<'name' | 'card' | ''>('')
const promptValue = ref('')
const pendingKick = ref<GroupMember>()
const pendingQuit = ref(false)

const directory = computed(() => (props.account ? store.directories[props.account.id] : undefined))
const group = computed(() => directory.value?.groups.find((item) => item.groupId === props.groupId))
const memberDirectory = computed(() =>
  props.account && props.groupId
    ? store.memberDirectories[groupMemberDirectoryKey(props.account.id, props.groupId)]
    : undefined,
)
const membersKey = computed(() => `members:${props.account?.id ?? ''}:group:${props.groupId ?? ''}`)
const membersLoading = computed(() => Boolean(store.loading[membersKey.value]))
const membersError = computed(() => store.errors[membersKey.value] || '')
const selfMember = computed(() =>
  memberDirectory.value?.members.find((member) => member.userId === memberDirectory.value?.selfUserId),
)
function capabilityPermission(name: CapabilityName): OperationPermission {
  const capability = props.account?.capabilities?.[name]
  return capability?.status === 'supported'
    ? { allowed: true }
    : { allowed: false, reason: capability?.reason || '当前 NapCat 未提供此能力' }
}
const readOnlyResourcePermissions = computed<GroupPermissions>(() => ({
  mentionAll: { allowed: false, reason: '无法确认群成员权限' },
  setAdmin: { allowed: false, reason: '无法确认群成员权限' },
  kickMembers: { allowed: false, reason: '无法确认群成员权限' },
  editOwnCard: { allowed: false, reason: '无法确认群成员权限' },
  rename: { allowed: false, reason: '无法确认群成员权限' },
  muteAll: { allowed: false, reason: '无法确认群成员权限' },
  quit: { allowed: false, reason: '无法确认群成员权限' },
  readEssence: capabilityPermission('group.essence'),
  readAnnouncements: capabilityPermission('group.announcements'),
  deleteAnnouncements: { allowed: false, reason: '无法确认当前 QQ 的群管理权限' },
  readFiles: capabilityPermission('group.files'),
  uploadFiles: { allowed: false, reason: '无法确认当前 QQ 的群成员身份' },
  manageFiles: { allowed: false, reason: '无法确认当前 QQ 的群管理权限' },
  packetFiles: { allowed: false, reason: '读取群文件后确认 NapCat Packet 状态' },
  renameFolders: { allowed: false, reason: 'NapCat 4.18.7 不支持重命名群文件夹' },
}))
const resourcePermissions = computed(() => memberDirectory.value?.permissions ?? readOnlyResourcePermissions.value)
const filteredMembers = computed(() => {
  const matches = createSearchMatcher(query.value)
  const members = (memberDirectory.value?.members ?? []).filter((member) =>
    matches(`${member.card}\n${member.nickname}\n${member.userId}`),
  )
  if (sort.value === 'default') return members
  const field = sort.value === 'join' ? 'joinTime' : 'lastSentTime'
  return [...members].sort((left, right) => (right[field] ?? 0) - (left[field] ?? 0))
})

function displayName(member: GroupMember): string {
  return member.card.trim() || member.nickname.trim() || member.userId
}

function canSetAdmin(member: GroupMember): boolean {
  return memberDirectory.value?.selfRole === 'owner' && member.userId !== memberDirectory.value.selfUserId && member.role !== 'owner'
}

function canKick(member: GroupMember): boolean {
  const selfRole = memberDirectory.value?.selfRole
  if (member.userId === memberDirectory.value?.selfUserId || member.role === 'owner') return false
  return selfRole === 'owner' || (selfRole === 'admin' && member.role === 'member')
}

function openPrompt(type: 'name' | 'card'): void {
  prompt.value = type
  promptValue.value = type === 'name' ? group.value?.groupName ?? '' : selfMember.value?.card ?? ''
}

async function submitPrompt(): Promise<void> {
  if (!props.account || !props.groupId || busyAction.value || !prompt.value) return
  busyAction.value = prompt.value
  try {
    if (prompt.value === 'name') await store.renameGroup(props.account.id, props.groupId, promptValue.value.trim())
    if (prompt.value === 'card' && memberDirectory.value) {
      await store.setCard(props.account.id, props.groupId, memberDirectory.value.selfUserId, promptValue.value.trim())
    }
    prompt.value = ''
  } catch (cause) {
    emit('notify', cause instanceof Error ? cause.message : '群设置更新失败')
  } finally {
    busyAction.value = ''
  }
}

async function toggleMute(): Promise<void> {
  if (!props.account || !props.groupId || busyAction.value) return
  busyAction.value = 'mute'
  try {
    await store.setMuteAll(props.account.id, props.groupId, !group.value?.wholeMuted)
  } catch (cause) {
    emit('notify', cause instanceof Error ? cause.message : '全员禁言设置失败')
  } finally {
    busyAction.value = ''
  }
}

async function toggleAdmin(member: GroupMember): Promise<void> {
  if (!props.account || !props.groupId || busyUserId.value) return
  busyUserId.value = member.userId
  try {
    await store.setAdmin(props.account.id, props.groupId, member.userId, member.role !== 'admin')
  } catch (cause) {
    emit('notify', cause instanceof Error ? cause.message : '管理员设置失败')
  } finally {
    busyUserId.value = ''
  }
}

async function confirmKick(): Promise<void> {
  const member = pendingKick.value
  if (!props.account || !props.groupId || !member || busyUserId.value) return
  busyUserId.value = member.userId
  try {
    await store.kickMember(props.account.id, props.groupId, member.userId)
    pendingKick.value = undefined
  } catch (cause) {
    emit('notify', cause instanceof Error ? cause.message : '移出群成员失败')
  } finally {
    busyUserId.value = ''
  }
}

async function quitGroup(): Promise<void> {
  if (!props.account || !props.groupId || busyAction.value) return
  busyAction.value = 'quit'
  try {
    await store.quitGroup(props.account.id, props.groupId)
    pendingQuit.value = false
    emit('quit')
    emit('close')
  } catch (cause) {
    emit('notify', cause instanceof Error ? cause.message : '退出群聊失败')
  } finally {
    busyAction.value = ''
  }
}

watch(
  () => [props.open, props.account?.id, props.groupId] as const,
  ([open, accountId, groupId]) => {
    if (!open || !accountId || !groupId) return
    tab.value = 'overview'
    query.value = ''
    prompt.value = ''
    pendingKick.value = undefined
    pendingQuit.value = false
    void Promise.all([store.loadDirectory(accountId), store.loadMembers(accountId, groupId, true)])
  },
  { immediate: true },
)
</script>

<template>
  <Teleport to="body">
    <div v-if="open && account && groupId" class="dialog-overlay" @mousedown.self="emit('close')">
      <section class="group-dialog" role="dialog" aria-modal="true" aria-label="群聊管理">
        <header>
          <AppAvatar :src="group?.avatar || `/api/media/avatar/group/${groupId}`" :name="group?.groupName || groupId" size="md" />
          <span class="group-header-copy"><small>{{ account.name }} · {{ groupId }}</small><h2>{{ group?.remark || group?.groupName || groupId }}</h2></span>
          <button class="icon-button" type="button" title="关闭群聊管理" @click="emit('close')"><X :size="19" /></button>
        </header>
        <nav class="dialog-tabs" aria-label="群聊管理视图">
          <button :class="{ active: tab === 'overview' }" type="button" @click="tab = 'overview'"><Settings2 :size="15" />设置</button>
          <button :class="{ active: tab === 'members' }" type="button" @click="tab = 'members'"><Users :size="15" />成员</button>
          <button :class="{ active: tab === 'resources' }" type="button" @click="tab = 'resources'"><Folder :size="15" />资源</button>
        </nav>

        <div v-if="tab === 'overview'" class="dialog-body overview-body">
          <article><span><strong>群名称</strong><small>{{ group?.groupName || groupId }}</small></span><button type="button" :title="memberDirectory?.permissions.rename.allowed ? '修改群名称' : memberDirectory?.permissions.rename.reason || '正在确认群管理权限'" :disabled="!memberDirectory?.permissions.rename.allowed" @click="openPrompt('name')"><Pencil :size="16" />修改</button></article>
          <article><span><strong>我的群名片</strong><small>{{ selfMember ? displayName(selfMember) : account.name }}</small></span><button type="button" :title="memberDirectory?.permissions.editOwnCard.allowed ? '修改我的群名片' : memberDirectory?.permissions.editOwnCard.reason || '正在确认群成员身份'" :disabled="!memberDirectory?.permissions.editOwnCard.allowed" @click="openPrompt('card')"><Pencil :size="16" />修改</button></article>
          <article><span><strong>全员禁言</strong><small>{{ group?.wholeMuted ? '已开启' : '已关闭' }}</small></span><button type="button" :title="memberDirectory?.permissions.muteAll.allowed ? '切换全员禁言' : memberDirectory?.permissions.muteAll.reason || '正在确认群管理权限'" :disabled="!memberDirectory?.permissions.muteAll.allowed || busyAction === 'mute'" @click="toggleMute"><Volume2 v-if="group?.wholeMuted" :size="16" /><VolumeX v-else :size="16" />{{ group?.wholeMuted ? '关闭' : '开启' }}</button></article>
          <article class="danger-row"><span><strong>退出群聊</strong><small>操作由 {{ account.name }} 执行</small></span><button class="danger" type="button" :title="memberDirectory?.permissions.quit.allowed ? '退出群聊' : memberDirectory?.permissions.quit.reason || '正在确认群成员身份'" :disabled="!memberDirectory?.permissions.quit.allowed" @click="pendingQuit = true"><LogOut :size="16" />退出</button></article>
          <div v-if="prompt" class="inline-prompt" role="dialog" aria-label="修改群设置"><label>{{ prompt === 'name' ? '群名称' : '群名片' }}<input v-model="promptValue" :maxlength="prompt === 'name' ? 60 : 60" /></label><button type="button" @click="prompt = ''">取消</button><button class="primary" type="button" :disabled="!promptValue.trim() || Boolean(busyAction)" @click="submitPrompt"><Check :size="15" />保存</button></div>
          <div v-if="pendingQuit" class="inline-prompt danger-prompt" role="alertdialog" aria-label="确认退出群聊"><span>确定让 {{ account.name }} 退出该群聊吗？</span><button type="button" @click="pendingQuit = false">取消</button><button class="danger" type="button" :disabled="Boolean(busyAction)" @click="quitGroup"><LoaderCircle v-if="busyAction === 'quit'" class="spin" :size="14" />退出</button></div>
        </div>

        <div v-else-if="tab === 'members'" class="dialog-body members-body">
          <div class="member-tools"><input v-model="query" type="search" placeholder="昵称、群名片或 QQ 号" aria-label="搜索群成员" /><select v-model="sort" aria-label="群成员排序"><option value="default">角色与名称</option><option value="join">最近入群</option><option value="last">最近发言</option></select></div>
          <p v-if="membersError" class="member-error">{{ membersError }}</p>
          <div v-if="membersLoading && !memberDirectory" class="member-state"><LoaderCircle class="spin" :size="22" />正在读取群成员</div>
          <div v-else class="member-list">
            <article v-for="member in filteredMembers" :key="member.userId">
              <AppAvatar :src="member.avatar" :name="displayName(member)" size="sm" />
              <span><strong>{{ displayName(member) }}</strong><small>{{ member.userId }} · {{ member.role === 'owner' ? '群主' : member.role === 'admin' ? '管理员' : '成员' }}<template v-if="member.title"> · {{ member.title }}</template><template v-if="member.level"> · 等级 {{ member.level }}</template></small><small>入群 {{ member.joinTime ? new Date(member.joinTime * 1000).toLocaleDateString('zh-CN') : '未知' }} · 最后发言 {{ member.lastSentTime ? new Date(member.lastSentTime * 1000).toLocaleDateString('zh-CN') : '未知' }}</small></span>
              <div>
                <button v-if="canSetAdmin(member)" class="icon-button" type="button" :title="member.role === 'admin' ? '取消管理员' : '设为管理员'" :disabled="Boolean(busyUserId)" @click="toggleAdmin(member)"><ShieldOff v-if="member.role === 'admin'" :size="16" /><ShieldCheck v-else :size="16" /></button>
                <button v-if="canKick(member)" class="icon-button danger" type="button" title="移出群聊" :disabled="Boolean(busyUserId)" @click="pendingKick = member"><UserMinus :size="16" /></button>
              </div>
            </article>
            <div v-if="!filteredMembers.length" class="member-state">没有匹配的群成员</div>
          </div>
          <div v-if="pendingKick" class="inline-prompt danger-prompt" role="alertdialog" aria-label="确认移出群成员"><span>确定将 {{ displayName(pendingKick) }} 移出群聊吗？</span><button type="button" @click="pendingKick = undefined">取消</button><button class="danger" type="button" :disabled="Boolean(busyUserId)" @click="confirmKick"><Trash2 :size="14" />移出</button></div>
        </div>

        <div v-else class="dialog-body resources-body">
          <p v-if="membersError && !memberDirectory" class="member-error">群成员列表不可用，群资源已按只读能力打开。</p>
          <GroupResourcesPanel :account="account" :group-id="groupId" :permissions="resourcePermissions" :members="memberDirectory?.members" @notify="emit('notify', $event)" />
        </div>
      </section>
    </div>
  </Teleport>
</template>

<style scoped>
.dialog-overlay { position: fixed; z-index: 90; inset: 0; display: grid; justify-items: end; background: rgb(7 18 21 / 45%); }
.group-dialog { display: flex; width: min(680px, 92vw); height: 100%; min-height: 0; flex-direction: column; background: var(--surface); box-shadow: -18px 0 48px rgb(8 25 30 / 20%); }
.group-dialog > header { display: flex; min-height: 68px; flex: 0 0 auto; align-items: center; gap: 11px; border-bottom: 1px solid var(--border); padding: 10px 14px; }
.group-header-copy { display: grid; min-width: 0; flex: 1; gap: 3px; }
.group-dialog h2 { margin: 0; overflow: hidden; color: var(--text); font-size: 15px; letter-spacing: 0; text-overflow: ellipsis; white-space: nowrap; }
.group-dialog header small { color: var(--text-muted); font-size: 9px; }
.dialog-tabs { display: grid; flex: 0 0 auto; grid-template-columns: repeat(3, 1fr); border-bottom: 1px solid var(--border); }
.dialog-tabs button { display: flex; height: 40px; cursor: pointer; align-items: center; justify-content: center; gap: 6px; border: 0; border-bottom: 2px solid transparent; color: var(--text-muted); background: transparent; font-size: 10px; }
.dialog-tabs button.active { border-bottom-color: var(--brand); color: var(--brand-strong); }
.dialog-body { min-height: 0; flex: 1; overflow-y: auto; }
.overview-body > article { display: flex; min-height: 68px; align-items: center; gap: 12px; border-bottom: 1px solid var(--border); padding: 11px 16px; }
.overview-body article > span { display: grid; min-width: 0; flex: 1; gap: 4px; }
.overview-body strong { color: var(--text); font-size: 11px; }
.overview-body small { color: var(--text-muted); font-size: 9px; }
.overview-body article > button, .inline-prompt button { display: flex; height: 32px; cursor: pointer; align-items: center; gap: 5px; border: 1px solid var(--border); border-radius: 5px; color: var(--text-secondary); background: var(--surface); padding: 0 9px; font-size: 9px; }
.danger-row { margin-top: 12px; border-top: 1px solid var(--border); }
button.danger, .icon-button.danger { color: var(--danger); }
button.primary { border-color: var(--brand); color: #fff; background: var(--brand); }
button:disabled { cursor: not-allowed; opacity: .4; }
.inline-prompt { display: flex; align-items: end; gap: 7px; border-bottom: 1px solid var(--border); background: var(--surface-muted); padding: 10px 14px; }
.inline-prompt label { display: grid; min-width: 0; flex: 1; gap: 4px; color: var(--text-muted); font-size: 9px; }
.inline-prompt input, .member-tools input, .member-tools select { height: 33px; min-width: 0; border: 1px solid var(--border); border-radius: 5px; color: var(--text); background: var(--surface); padding: 0 9px; font: inherit; font-size: 10px; }
.inline-prompt > span { min-width: 0; flex: 1; color: var(--text-secondary); font-size: 10px; }
.danger-prompt { border-left: 3px solid var(--danger); background: var(--danger-soft); }
.member-tools { display: grid; grid-template-columns: minmax(0, 1fr) 150px; gap: 8px; border-bottom: 1px solid var(--border); padding: 10px 12px; }
.member-list article { display: grid; min-height: 66px; grid-template-columns: auto minmax(0, 1fr) auto; align-items: center; gap: 10px; border-bottom: 1px solid var(--border); padding: 8px 12px; }
.member-list article > span { display: grid; min-width: 0; gap: 3px; }
.member-list strong, .member-list small { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.member-list strong { color: var(--text); font-size: 11px; }
.member-list small { color: var(--text-muted); font-size: 8px; }
.member-list article > div { display: flex; gap: 3px; }
.member-state { display: grid; min-height: 180px; place-content: center; place-items: center; gap: 8px; color: var(--text-muted); font-size: 10px; }
.member-error { color: var(--danger); background: var(--danger-soft); padding: 8px 10px; font-size: 9px; }
.resources-body { overflow: auto; }
.spin { animation: spin 850ms linear infinite; }
@keyframes spin { to { transform: rotate(360deg); } }
@media (max-width: 700px) {
  .dialog-overlay { justify-items: stretch; }
  .group-dialog { width: 100%; max-width: none; }
  .member-tools { grid-template-columns: minmax(0, 1fr); }
}
</style>

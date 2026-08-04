<script setup lang="ts">
import {
  ArrowLeft,
  Download,
  FilePen,
  FileText,
  Folder,
  FolderPen,
  FolderPlus,
  LoaderCircle,
  Megaphone,
  Move,
  Sparkles,
  Trash2,
  Upload,
} from '@lucide/vue'
import { computed, onBeforeUnmount, ref, watch } from 'vue'

import { workspaceAdapter } from '../../services/workspace-adapter'
import {
  clearUncertainGroupUpload,
  groupUploadFingerprint,
  markUncertainGroupUpload,
  uncertainGroupUploadBlocked,
} from '../../services/upload-guard'
import { useQqDirectoryStore } from '../../stores/qq-directory'
import type {
  Account,
  ChatMessage,
  Conversation,
  EssenceMessage,
  EssencePage,
  GroupAnnouncement,
  GroupFile,
  GroupFilePage,
  GroupFolder,
  GroupMember,
  GroupPermissions,
} from '../../types/workspace'
import MessageBubble from '../chat/MessageBubble.vue'

const props = defineProps<{
  account: Account
  groupId: string
  permissions: GroupPermissions
  members?: GroupMember[]
}>()
const emit = defineEmits<{ notify: [message: string] }>()
const store = useQqDirectoryStore()
const mode = ref<'essence' | 'announcements' | 'files'>('essence')
const loading = ref(false)
const busy = ref(false)
const error = ref('')
const essence = ref<EssencePage>()
const visibleEssence = ref(30)
const announcements = ref<GroupAnnouncement[]>([])
const filePage = ref<GroupFilePage>()
const path = ref<Array<{ id: string; name: string }>>([])
const rootFolders = ref<GroupFolder[]>([])
const selectedFileIds = ref<string[]>([])
const promptMode = ref<'create-folder' | 'rename-file' | 'move-file' | ''>('')
const promptValue = ref('')
const moveTarget = ref('/')
const pendingDelete = ref<{
  type: 'files' | 'folder' | 'announcement'
  ids: string[]
  name: string
}>()
const fileInput = ref<HTMLInputElement>()
let requestVersion = 0

const currentParent = computed(() => path.value.at(-1)?.id ?? '/')
const resourceConversation = computed<Conversation>(() => ({
  id: `${props.account.id}:group:${props.groupId}`,
  accountId: props.account.id,
  type: 'group',
  peerId: props.groupId,
  name: props.groupId,
  avatar: `/api/media/avatar/group/${props.groupId}`,
  lastMessage: '',
  lastMessageAt: '',
  unread: 0,
  pinned: false,
  muted: false,
}))
const selectedFiles = computed(() => filePage.value?.files.filter((file) => selectedFileIds.value.includes(file.id)) ?? [])
const selectedFile = computed(() => selectedFiles.value.length === 1 ? selectedFiles.value[0] : undefined)
const allFilesSelected = computed(() =>
  Boolean(filePage.value?.files.length) && selectedFileIds.value.length === filePage.value?.files.length,
)
const filePermissions = computed(() => filePage.value?.permissions ?? props.permissions)
const canPacketManage = computed(() => filePermissions.value.manageFiles.allowed && filePermissions.value.packetFiles.allowed)
const moveTargets = computed(() =>
  [{ id: '/', name: '群文件' }, ...rootFolders.value.map((folder) => ({ id: folder.id, name: folder.name }))].filter(
    (target) => target.id !== currentParent.value,
  ),
)
const memberNames = computed(() => new Map(
  (props.members ?? []).map((member) => [member.userId, member.card.trim() || member.nickname.trim() || member.userId]),
))

function memberName(userId: string | undefined): string {
  if (!userId) return '未知成员'
  return memberNames.value.get(userId) || userId
}

async function load(): Promise<void> {
  const version = ++requestVersion
  const accountId = props.account.id
  const groupId = props.groupId
  const requestedMode = mode.value
  const parentId = currentParent.value
  loading.value = true
  error.value = ''
  try {
    if (requestedMode === 'essence') {
      const result = await workspaceAdapter.loadEssence(accountId, groupId)
      if (version === requestVersion && props.account.id === accountId && props.groupId === groupId && mode.value === requestedMode) {
        essence.value = result
      }
    }
    if (requestedMode === 'announcements') {
      const result = await workspaceAdapter.loadAnnouncements(accountId, groupId)
      if (version === requestVersion && props.account.id === accountId && props.groupId === groupId && mode.value === requestedMode) {
        announcements.value = result
      }
    }
    if (requestedMode === 'files') {
      const page = await workspaceAdapter.loadGroupFiles(accountId, groupId, parentId)
      if (
        version !== requestVersion ||
        props.account.id !== accountId ||
        props.groupId !== groupId ||
        mode.value !== requestedMode ||
        currentParent.value !== parentId
      ) return
      filePage.value = page
      if (!path.value.length) rootFolders.value = page.folders
      selectedFileIds.value = []
    }
  } catch (cause) {
    if (version === requestVersion) error.value = cause instanceof Error ? cause.message : '群资源加载失败'
  } finally {
    if (version === requestVersion) loading.value = false
  }
}

function essenceChatMessage(item: EssenceMessage): ChatMessage {
  return {
    id: item.id,
    accountId: item.accountId,
    conversationId: resourceConversation.value.id,
    messageId: item.messageId,
    senderId: item.senderId,
    senderName: item.senderName,
    senderAvatar: `/api/media/avatar/user/${item.senderId}`,
    timestamp: item.operatorTime ? new Date(item.operatorTime * 1_000).toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' }) : '',
    timestampMs: item.operatorTime ? item.operatorTime * 1_000 : 0,
    content: item.content,
    segments: item.segments,
    mine: false,
  }
}

function enterFolder(folder: GroupFolder): void {
  path.value.push({ id: folder.id, name: folder.name })
  void load()
}

function goBack(): void {
  path.value.pop()
  void load()
}

function setFileSelected(fileId: string, selected: boolean): void {
  selectedFileIds.value = selected
    ? [...new Set([...selectedFileIds.value, fileId])]
    : selectedFileIds.value.filter((id) => id !== fileId)
}

function toggleFile(fileId: string): void {
  setFileSelected(fileId, !selectedFileIds.value.includes(fileId))
}

function setAllFilesSelected(selected: boolean): void {
  selectedFileIds.value = selected ? filePage.value?.files.map((file) => file.id) ?? [] : []
}

async function downloadFiles(targets: GroupFile[]): Promise<void> {
  if (!filePermissions.value.packetFiles.allowed) {
    emit('notify', filePermissions.value.packetFiles.reason || '群文件下载当前不可用')
    return
  }
  if (busy.value || !targets.length) return
  busy.value = true
  const failed: string[] = []
  try {
    for (const file of targets) {
      try {
        const url = await workspaceAdapter.loadGroupFileUrl(props.account.id, props.groupId, file.id, file.name)
        const anchor = document.createElement('a')
        anchor.href = url
        anchor.download = file.name
        document.body.append(anchor)
        anchor.click()
        anchor.remove()
      } catch {
        failed.push(file.name)
      }
    }
    if (failed.length) emit('notify', `${failed.length} 个群文件下载失败：${failed.join('、')}`)
  } finally {
    busy.value = false
  }
}

async function runFileMutation(
  targets: GroupFile[],
  operation: (file: GroupFile) => Promise<void>,
): Promise<string[]> {
  const failedIds: string[] = []
  for (let index = 0; index < targets.length; index += 4) {
    const batch = targets.slice(index, index + 4)
    const results = await Promise.allSettled(batch.map(operation))
    results.forEach((result, resultIndex) => {
      if (result.status === 'rejected' && batch[resultIndex]) failedIds.push(batch[resultIndex]!.id)
    })
  }
  return failedIds
}

async function uploadFiles(event: Event): Promise<void> {
  const input = event.target as HTMLInputElement
  const files = [...(input.files ?? [])]
  input.value = ''
  if (!filePermissions.value.uploadFiles.allowed || !files.length) return
  busy.value = true
  try {
    for (const file of files) {
      const fingerprint = await groupUploadFingerprint(props.account.id, props.groupId, currentParent.value, file)
      if (uncertainGroupUploadBlocked(fingerprint)) {
        throw new Error('相同群文件的上次上传结果未知；为避免重复上传，请等待 10 分钟并先刷新群文件列表')
      }
      if (!markUncertainGroupUpload(fingerprint)) {
        throw new Error('无法写入群文件防重状态；为避免重复上传，本次请求未发送到 NapCat')
      }
      try {
        await workspaceAdapter.uploadGroupFile(props.account.id, props.groupId, currentParent.value, file)
        clearUncertainGroupUpload(fingerprint)
      } catch (cause) {
        throw cause
      }
    }
    await load()
  } catch (cause) {
    emit('notify', cause instanceof Error ? cause.message : '群文件上传失败，结果未知时请先刷新列表')
  } finally {
    busy.value = false
  }
}

function openPrompt(modeValue: 'create-folder' | 'rename-file' | 'move-file'): void {
  promptMode.value = modeValue
  promptValue.value = modeValue === 'rename-file' ? selectedFile.value?.name ?? '' : ''
  moveTarget.value = moveTargets.value[0]?.id ?? '/'
}

function requestDeleteFiles(): void {
  if (!selectedFiles.value.length) return
  pendingDelete.value = {
    type: 'files',
    ids: selectedFiles.value.map((file) => file.id),
    name: selectedFiles.value.length === 1 ? selectedFiles.value[0]!.name : `选中的 ${selectedFiles.value.length} 个文件`,
  }
}

async function submitPrompt(): Promise<void> {
  if (busy.value || !promptMode.value) return
  busy.value = true
  try {
    if (promptMode.value === 'create-folder') {
      await workspaceAdapter.createGroupFolder(props.account.id, props.groupId, promptValue.value.trim())
    } else if (promptMode.value === 'rename-file' && selectedFile.value) {
      await workspaceAdapter.renameGroupFile(
        props.account.id,
        props.groupId,
        selectedFile.value.id,
        currentParent.value,
        promptValue.value.trim(),
      )
    } else if (promptMode.value === 'move-file' && selectedFiles.value.length) {
      const targets = [...selectedFiles.value]
      const failedIds = await runFileMutation(targets, (file) =>
        workspaceAdapter.moveGroupFile(
          props.account.id,
          props.groupId,
          file.id,
          currentParent.value,
          moveTarget.value,
        ),
      )
      promptMode.value = ''
      await load()
      selectedFileIds.value = failedIds
      if (failedIds.length) emit('notify', `${failedIds.length} 个群文件移动失败，失败项已保留选择`)
      return
    }
    promptMode.value = ''
    await load()
  } catch (cause) {
    emit('notify', cause instanceof Error ? cause.message : '群文件操作失败')
  } finally {
    busy.value = false
  }
}

async function confirmDelete(): Promise<void> {
  const target = pendingDelete.value
  if (!target || busy.value) return
  busy.value = true
  try {
    if (target.type === 'files') {
      const files = (filePage.value?.files ?? []).filter((file) => target.ids.includes(file.id))
      const failedIds = await runFileMutation(files, (file) =>
        workspaceAdapter.deleteGroupFile(props.account.id, props.groupId, file.id),
      )
      pendingDelete.value = undefined
      await load()
      selectedFileIds.value = failedIds
      if (failedIds.length) emit('notify', `${failedIds.length} 个群文件删除失败，失败项已保留选择`)
      return
    }
    if (target.type === 'folder') await workspaceAdapter.deleteGroupFolder(props.account.id, props.groupId, target.ids[0]!)
    if (target.type === 'announcement') {
      await workspaceAdapter.deleteAnnouncement(props.account.id, props.groupId, target.ids[0]!)
    }
    pendingDelete.value = undefined
    await load()
  } catch (cause) {
    emit('notify', cause instanceof Error ? cause.message : '删除失败')
  } finally {
    busy.value = false
  }
}

watch([mode, () => props.account.id, () => props.groupId], () => {
  requestVersion += 1
  path.value = []
  visibleEssence.value = 30
  essence.value = undefined
  announcements.value = []
  filePage.value = undefined
  rootFolders.value = []
  selectedFileIds.value = []
  void load()
}, { immediate: true })
watch(
  () => store.resourceVersions[`${props.account.id}:${props.groupId}:${mode.value}`] ?? 0,
  () => void load(),
)
onBeforeUnmount(() => {
  requestVersion += 1
})
</script>

<template>
  <section class="group-resources">
    <div class="resource-tabs" role="tablist" aria-label="群资源">
      <button :class="{ active: mode === 'essence' }" type="button" @click="mode = 'essence'"><Sparkles :size="15" />精华</button>
      <button :class="{ active: mode === 'announcements' }" type="button" @click="mode = 'announcements'"><Megaphone :size="15" />公告</button>
      <button :class="{ active: mode === 'files' }" type="button" @click="mode = 'files'"><Folder :size="15" />文件</button>
    </div>

    <p v-if="error" class="resource-error" role="alert">{{ error }}</p>
    <div v-if="loading" class="resource-state"><LoaderCircle class="spin" :size="22" />正在读取群资源</div>

    <div v-else-if="mode === 'essence'" class="resource-list">
      <article v-for="item in essence?.items.slice(0, visibleEssence)" :key="item.id" class="essence-item">
        <MessageBubble :message="essenceChatMessage(item)" :conversation="resourceConversation" readonly />
        <small>由 {{ item.operatorName }}{{ item.operatorTime ? `于 ${new Date(item.operatorTime * 1000).toLocaleString('zh-CN')}` : '' }}设为精华</small>
      </article>
      <button v-if="(essence?.items.length || 0) > visibleEssence" class="load-more" type="button" @click="visibleEssence += 30">显示更多</button>
      <p v-if="essence?.truncated" class="resource-limit">NapCat 返回的精华消息超过 500 条，当前仅显示本次有界结果。</p>
      <div v-if="!essence?.items.length" class="resource-state">暂无群精华消息</div>
    </div>

    <div v-else-if="mode === 'announcements'" class="resource-list">
      <article v-for="item in announcements" :key="item.id">
        <Megaphone :size="16" />
        <span><strong>{{ memberName(item.senderId) }}</strong><p>{{ item.content || '[图片公告]' }}</p><small>{{ item.senderId }} · {{ item.publishTime ? new Date(item.publishTime * 1000).toLocaleString('zh-CN') : '时间未知' }}<template v-if="item.readCount !== undefined"> · {{ item.readCount }} 次阅读</template></small></span>
        <button class="icon-button danger" type="button" :disabled="!permissions.deleteAnnouncements.allowed" :title="permissions.deleteAnnouncements.allowed ? '删除群公告' : permissions.deleteAnnouncements.reason || '当前 QQ 无权删除群公告'" @click="pendingDelete = { type: 'announcement', ids: [item.id], name: '该公告' }"><Trash2 :size="15" /></button>
        <img v-for="url in item.imageUrls" :key="url" :src="url" alt="群公告图片" />
      </article>
      <div v-if="!announcements.length" class="resource-state">暂无群公告</div>
    </div>

    <div v-else class="file-browser">
      <div class="file-toolbar">
        <button v-if="path.length" class="icon-button" type="button" title="返回上级文件夹" :disabled="busy" @click="goBack"><ArrowLeft :size="16" /></button>
        <strong>{{ path.at(-1)?.name || '群文件' }}</strong>
        <span />
        <button type="button" :title="filePermissions.uploadFiles.allowed ? '上传群文件' : filePermissions.uploadFiles.reason || '当前 QQ 无权上传群文件'" :disabled="busy || !filePermissions.uploadFiles.allowed" @click="fileInput?.click()"><Upload :size="15" />上传</button>
        <button v-if="!path.length" type="button" :title="filePermissions.manageFiles.allowed ? '新建文件夹' : filePermissions.manageFiles.reason || '当前 QQ 无权新建文件夹'" :disabled="busy || !filePermissions.manageFiles.allowed" @click="openPrompt('create-folder')"><FolderPlus :size="15" />新建文件夹</button>
        <input ref="fileInput" hidden type="file" multiple @change="uploadFiles" />
      </div>
      <p v-if="!filePermissions.renameFolders.allowed" class="protocol-gap" :title="filePermissions.renameFolders.reason">
        <FolderPen :size="14" />{{ filePermissions.renameFolders.reason || '当前 NapCat 不支持重命名群文件夹' }}
      </p>
      <p v-if="filePage?.truncated" class="resource-limit">当前文件夹达到 500 项读取上限，NapCat 可能仍有未显示的群文件。</p>
      <div v-if="filePage?.files.length" class="selection-toolbar">
        <input
          type="checkbox"
          aria-label="选择当前文件夹中的全部文件"
          :checked="allFilesSelected"
          :disabled="busy"
          @change="setAllFilesSelected(!allFilesSelected)"
        />
        <strong>{{ selectedFiles.length ? `已选择 ${selectedFiles.length} 个文件` : `${filePage.files.length} 个文件` }}</strong>
        <button type="button" :title="filePermissions.packetFiles.allowed ? '下载所选文件' : filePermissions.packetFiles.reason || '当前 NapCat 无法下载群文件'" :disabled="busy || !selectedFiles.length || !filePermissions.packetFiles.allowed" @click="downloadFiles(selectedFiles)"><Download :size="15" />下载</button>
        <button type="button" :title="canPacketManage ? '重命名所选文件' : filePermissions.manageFiles.reason || filePermissions.packetFiles.reason || '当前 QQ 无法管理群文件'" :disabled="busy || selectedFiles.length !== 1 || !canPacketManage" @click="openPrompt('rename-file')"><FilePen :size="15" />重命名</button>
        <button type="button" :title="canPacketManage ? '移动所选文件' : filePermissions.manageFiles.reason || filePermissions.packetFiles.reason || '当前 QQ 无法管理群文件'" :disabled="busy || !selectedFiles.length || !canPacketManage || !moveTargets.length" @click="openPrompt('move-file')"><Move :size="15" />移动</button>
        <button class="danger" type="button" :title="filePermissions.manageFiles.allowed ? '删除所选文件' : filePermissions.manageFiles.reason || '当前 QQ 无权删除群文件'" :disabled="busy || !selectedFiles.length || !filePermissions.manageFiles.allowed" @click="requestDeleteFiles"><Trash2 :size="15" />删除</button>
      </div>
      <div class="file-list">
        <article v-for="folder in filePage?.folders" :key="folder.id" class="folder-row">
          <button class="file-main" type="button" @click="enterFolder(folder)"><Folder :size="19" /><span><strong>{{ folder.name }}</strong><small>{{ folder.fileCount }} 个文件</small></span></button>
          <button class="icon-button danger" type="button" :disabled="!filePermissions.manageFiles.allowed" :title="filePermissions.manageFiles.allowed ? '删除文件夹' : filePermissions.manageFiles.reason || '当前 QQ 无权删除文件夹'" @click="pendingDelete = { type: 'folder', ids: [folder.id], name: folder.name }"><Trash2 :size="15" /></button>
        </article>
        <article v-for="file in filePage?.files" :key="file.id" :class="{ selected: selectedFileIds.includes(file.id) }">
          <input type="checkbox" :aria-label="`选择 ${file.name}`" :checked="selectedFileIds.includes(file.id)" :disabled="busy" @change="toggleFile(file.id)" />
          <button class="file-main" type="button" @click="toggleFile(file.id)"><FileText :size="19" /><span><strong>{{ file.name }}</strong><small>{{ Math.ceil(file.size / 1024).toLocaleString() }} KB · {{ file.downloadCount ?? 0 }} 次下载<template v-if="file.uploaderId"> · {{ memberName(file.uploaderId) }} 上传</template><template v-if="file.uploadedAt"> · {{ new Date(file.uploadedAt * 1000).toLocaleDateString('zh-CN') }}</template></small></span></button>
          <button class="icon-button" type="button" :title="filePermissions.packetFiles.allowed ? '下载文件' : filePermissions.packetFiles.reason || '当前 NapCat 无法下载群文件'" :disabled="busy || !filePermissions.packetFiles.allowed" @click="downloadFiles([file])"><Download :size="15" /></button>
        </article>
        <div v-if="!filePage?.files.length && !filePage?.folders.length" class="resource-state">此文件夹为空</div>
      </div>
    </div>

    <div v-if="promptMode" class="resource-prompt" role="dialog" aria-label="群文件操作">
      <label v-if="promptMode === 'move-file'">目标文件夹<select v-model="moveTarget"><option v-for="target in moveTargets" :key="target.id" :value="target.id">{{ target.name }}</option></select></label>
      <label v-else>{{ promptMode === 'create-folder' ? '文件夹名称' : '新文件名' }}<input v-model="promptValue" :maxlength="promptMode === 'create-folder' ? 36 : 255" /></label>
      <button type="button" @click="promptMode = ''">取消</button><button class="primary" type="button" :disabled="busy || (promptMode !== 'move-file' && !promptValue.trim())" @click="submitPrompt">确认</button>
    </div>
    <div v-if="pendingDelete" class="resource-prompt danger-prompt" role="alertdialog" aria-label="确认删除群资源">
      <span>确定删除“{{ pendingDelete.name }}”吗？</span><button type="button" @click="pendingDelete = undefined">取消</button><button class="danger" type="button" :disabled="busy" @click="confirmDelete">删除</button>
    </div>
  </section>
</template>

<style scoped>
.group-resources { min-height: 0; }
.resource-tabs { display: grid; grid-template-columns: repeat(3, 1fr); border-bottom: 1px solid var(--border); }
.resource-tabs button { display: flex; height: 38px; cursor: pointer; align-items: center; justify-content: center; gap: 6px; border: 0; border-bottom: 2px solid transparent; color: var(--text-muted); background: transparent; font-size: 10px; }
.resource-tabs button.active { border-bottom-color: var(--brand); color: var(--brand-strong); }
.resource-list article, .file-list article { display: grid; min-height: 62px; grid-template-columns: auto minmax(0, 1fr) auto; align-items: center; gap: 10px; border-bottom: 1px solid var(--border); padding: 9px 11px; }
.resource-list article > span { min-width: 0; }
.resource-list article.essence-item { display: block; padding: 11px 6px; }
.essence-item > small { display: block; margin: 3px 0 0 42px; color: var(--text-muted); font-size: 9px; }
.essence-item :deep(.message-row) { padding: 0; }
.resource-list strong, .file-list strong { color: var(--text); font-size: 11px; }
.resource-list p { margin: 3px 0; color: var(--text-secondary); font-size: 10px; line-height: 1.5; white-space: pre-wrap; }
.resource-list small, .file-list small { color: var(--text-muted); font-size: 9px; }
.resource-list img { width: min(240px, 100%); max-height: 180px; grid-column: 2; object-fit: contain; }
.resource-state { display: grid; min-height: 150px; place-content: center; place-items: center; gap: 8px; color: var(--text-muted); font-size: 10px; }
.resource-error { color: var(--danger); background: var(--danger-soft); padding: 8px 10px; font-size: 10px; }
.load-more { display: block; height: 34px; margin: 10px auto; border: 1px solid var(--border); border-radius: 5px; color: var(--text-secondary); background: var(--surface); padding: 0 15px; }
.resource-limit { margin: 9px 11px; border-left: 3px solid var(--warning); color: var(--text-secondary); background: var(--warning-soft); padding: 8px 10px; font-size: 9px; }
.file-toolbar { display: grid; min-height: 46px; grid-template-columns: auto auto 1fr auto auto; align-items: center; gap: 7px; border-bottom: 1px solid var(--border); padding: 6px 9px; }
.file-toolbar > button, .selection-toolbar button, .resource-prompt button { display: flex; height: 32px; cursor: pointer; align-items: center; gap: 5px; border: 1px solid var(--border); border-radius: 5px; color: var(--text-secondary); background: var(--surface); padding: 0 9px; font-size: 9px; }
.file-main { display: flex; min-width: 0; cursor: pointer; align-items: center; gap: 9px; border: 0; color: var(--brand-strong); background: transparent; padding: 0; text-align: left; }
.file-main span { display: grid; min-width: 0; gap: 3px; }
.file-main strong, .file-main small { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.file-list article.selected { background: var(--brand-soft); }
.file-list article.folder-row { grid-template-columns: minmax(0, 1fr) auto; }
.file-list article > input[type='checkbox'], .selection-toolbar > input[type='checkbox'] { width: 16px; height: 16px; margin: 0; accent-color: var(--brand); }
.selection-toolbar { display: flex; align-items: center; gap: 6px; border-top: 1px solid var(--border); background: var(--surface-muted); padding: 8px 10px; }
.selection-toolbar strong { min-width: 0; flex: 1; overflow: hidden; color: var(--text); font-size: 10px; text-overflow: ellipsis; white-space: nowrap; }
.resource-prompt { display: flex; align-items: end; gap: 7px; border-top: 1px solid var(--border); background: var(--surface-muted); padding: 9px 10px; }
.resource-prompt label { display: grid; min-width: 0; flex: 1; gap: 4px; color: var(--text-muted); font-size: 9px; }
.resource-prompt input, .resource-prompt select { height: 32px; min-width: 0; border: 1px solid var(--border); border-radius: 5px; color: var(--text); background: var(--surface); padding: 0 8px; font: inherit; font-size: 10px; }
.resource-prompt span { min-width: 0; flex: 1; color: var(--text-secondary); font-size: 10px; }
.protocol-gap { display: flex; align-items: center; gap: 6px; margin: 0; border-bottom: 1px solid var(--border); color: var(--text-muted); background: var(--surface-muted); padding: 6px 10px; font-size: 9px; }
button.primary { border-color: var(--brand); color: #fff; background: var(--brand); }
button.danger, .icon-button.danger { color: var(--danger); }
button:disabled { cursor: not-allowed; opacity: .4; }
.spin { animation: spin 850ms linear infinite; }
@keyframes spin { to { transform: rotate(360deg); } }
@media (max-width: 560px) {
  .file-toolbar { grid-template-columns: auto minmax(0, 1fr) auto; }
  .file-toolbar > span { display: none; }
  .file-toolbar > button:last-of-type { grid-column: 2 / -1; justify-content: center; }
  .selection-toolbar { flex-wrap: wrap; }
  .selection-toolbar strong { flex-basis: 100%; }
}
</style>

<script setup lang="ts">
import { FileText, LoaderCircle, X } from '@lucide/vue'

defineProps<{ open: boolean; files: File[]; conversationName: string; busy: boolean; status?: string }>()
const emit = defineEmits<{ confirm: []; cancel: [] }>()

function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${Math.round(bytes / 102.4) / 10} KB`
  return `${Math.round(bytes / 1024 / 102.4) / 10} MB`
}
</script>

<template>
  <Teleport to="body">
    <div v-if="open" class="dialog-backdrop" @mousedown.self="!busy && emit('cancel')">
      <section class="file-dialog" role="dialog" aria-modal="true" aria-label="发送文件">
        <header>
          <span><FileText :size="21" /></span>
          <div><strong>发送文件</strong><small>发送到 {{ conversationName }}</small></div>
          <button type="button" title="取消发送" :disabled="busy" @click="emit('cancel')"><X :size="18" /></button>
        </header>
        <div class="files">
          <div v-for="(file, index) in files" :key="`${file.name}:${file.size}:${file.lastModified}:${index}`">
            <FileText :size="19" />
            <span><strong>{{ file.name || '未命名文件' }}</strong><small>{{ formatSize(file.size) }}</small></span>
          </div>
        </div>
        <p v-if="status" class="status"><LoaderCircle class="spin" :size="14" />{{ status }}</p>
        <footer>
          <button type="button" :disabled="busy" @click="emit('cancel')">取消</button>
          <button class="primary" type="button" :disabled="busy || !files.length" @click="emit('confirm')">
            <LoaderCircle v-if="busy" class="spin" :size="15" />
            {{ busy ? '发送中' : files.length > 1 ? `发送 ${files.length} 个文件` : '发送' }}
          </button>
        </footer>
      </section>
    </div>
  </Teleport>
</template>

<style scoped>
.dialog-backdrop { position: fixed; z-index: 220; inset: 0; display: grid; place-items: center; background: #0007; padding: 16px; }
.file-dialog { width: min(460px, 100%); max-height: min(680px, calc(100dvh - 32px)); border: 1px solid var(--border); border-radius: 8px; background: var(--surface); box-shadow: var(--floating-shadow); }
header { display: flex; align-items: center; gap: 10px; border-bottom: 1px solid var(--border); padding: 12px 14px; }
header > span { display: grid; width: 36px; height: 36px; place-items: center; border-radius: 6px; color: var(--brand-strong); background: var(--brand-soft); }
header div { min-width: 0; flex: 1; } header strong, header small { display: block; } header strong { color: var(--text); font-size: 13px; } header small { overflow: hidden; color: var(--text-muted); font-size: 9px; text-overflow: ellipsis; white-space: nowrap; }
header button { display: grid; width: 32px; height: 32px; cursor: pointer; place-items: center; border: 0; color: var(--text-muted); background: transparent; }
.files { max-height: 280px; overflow-y: auto; padding: 5px 14px; }.files > div { display: flex; min-height: 54px; align-items: center; gap: 10px; border-bottom: 1px solid var(--border); }.files > div:last-child { border-bottom: 0; }.files svg { flex: 0 0 auto; color: var(--text-muted); }.files span { min-width: 0; }.files strong, .files small { display: block; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }.files strong { color: var(--text); font-size: 11px; }.files small { color: var(--text-muted); font-size: 9px; }
.status { display: flex; align-items: center; gap: 6px; margin: 0 14px; border-radius: 5px; color: var(--brand-strong); background: var(--brand-soft); padding: 7px 9px; font-size: 10px; }
footer { display: flex; justify-content: flex-end; gap: 7px; border-top: 1px solid var(--border); padding: 10px 14px; }footer button { display: flex; min-height: 34px; cursor: pointer; align-items: center; gap: 5px; border: 1px solid var(--border); border-radius: 5px; color: var(--text); background: var(--surface); padding: 0 12px; font-size: 10px; }footer .primary { border-color: var(--brand); color: #fff; background: var(--brand); }button:disabled { cursor: not-allowed; opacity: .48; }
.spin { animation: spin 800ms linear infinite; }@keyframes spin { to { transform: rotate(360deg); } }
</style>

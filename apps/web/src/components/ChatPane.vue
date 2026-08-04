<script setup lang="ts">
import {
  ArrowLeft,
  BellOff,
  FileText,
  ImagePlus,
  Info,
  LoaderCircle,
  MessageSquareReply,
  MoreHorizontal,
  Paperclip,
  PanelRight,
  Search,
  SendHorizontal,
  SmilePlus,
  Sparkles,
  Users,
} from '@lucide/vue'
import { nextTick, ref, watch } from 'vue'

import type { Account, ChatMessage, Conversation } from '../types/workspace'
import AppAvatar from './AppAvatar.vue'

const props = defineProps<{
  conversation?: Conversation
  account?: Account
  messages: ChatMessage[]
  selectedMessageId: string
  agentCollapsed: boolean
  loading: boolean
  error: string
  sending: boolean
}>()

const emit = defineEmits<{
  send: [content: string]
  sendToAgent: [message: ChatMessage]
  openAgent: []
  back: []
  notify: [message: string]
}>()

const composer = ref('')
const messageList = ref<HTMLElement>()

function scrollToBottom(): void {
  void nextTick(() => {
    if (messageList.value) messageList.value.scrollTop = messageList.value.scrollHeight
  })
}

function send(): void {
  const value = composer.value.trim()
  if (!value) return
  emit('send', value)
  composer.value = ''
  scrollToBottom()
}

function handleKeydown(event: KeyboardEvent): void {
  if (event.key !== 'Enter' || event.shiftKey || event.isComposing) return
  event.preventDefault()
  send()
}

function quickAction(label: string): void {
  emit('notify', label)
}

watch(() => props.messages.length, scrollToBottom)
watch(() => props.conversation?.id, scrollToBottom, { immediate: true })
</script>

<template>
  <main class="chat-pane">
    <template v-if="conversation">
      <header class="chat-header">
        <button class="icon-button mobile-back" type="button" title="返回会话" aria-label="返回会话" @click="emit('back')">
          <ArrowLeft :size="20" />
        </button>
        <AppAvatar class="chat-header__avatar" :src="conversation.avatar" :name="conversation.name" size="sm" />
        <div class="chat-heading">
          <div class="chat-heading__title">
            <h2>{{ conversation.name }}</h2>
            <span v-if="conversation.type === 'group'" class="type-chip">群</span>
            <BellOff v-if="conversation.muted" :size="13" class="muted" />
          </div>
          <p v-if="conversation.type === 'group'">
            {{ conversation.onlineMembers }} 人在线 · {{ conversation.members }} 位成员 · {{ conversation.topic }}
          </p>
          <p v-else>来自 {{ account?.name }}</p>
        </div>
        <div class="chat-actions">
          <button class="icon-button" type="button" title="搜索聊天记录" aria-label="搜索聊天记录" @click="quickAction('消息搜索已打开')">
            <Search :size="18" />
          </button>
          <button
            v-if="conversation.type === 'group'"
            class="icon-button secondary-action"
            type="button"
            title="群成员"
            aria-label="群成员"
            @click="quickAction(`${conversation.members} 位群成员`)"
          >
            <Users :size="18" />
          </button>
          <button class="icon-button secondary-action" type="button" title="会话详情" aria-label="会话详情" @click="quickAction('会话详情已打开')">
            <Info :size="18" />
          </button>
          <button
            class="icon-button agent-toggle"
            :class="{ active: !agentCollapsed }"
            type="button"
            title="Agent Console"
            aria-label="打开 Agent Console"
            @click="emit('openAgent')"
          >
            <PanelRight :size="18" />
          </button>
        </div>
      </header>

      <section ref="messageList" class="message-list" aria-label="聊天消息">
        <div v-if="messages.length" class="date-divider"><span>最近消息</span></div>
        <div v-if="loading && !messages.length" class="chat-empty">
          <LoaderCircle class="spin" :size="27" />
          <strong>正在从 NapCat 读取消息</strong>
        </div>
        <div v-else-if="error && !messages.length" class="chat-empty error-state">
          <Info :size="27" />
          <strong>{{ error }}</strong>
        </div>
        <article
          v-for="message in messages"
          :key="message.id"
          class="message-row"
          :class="{ mine: message.mine, selected: message.id === selectedMessageId }"
        >
          <AppAvatar :src="message.senderAvatar" :name="message.senderName" size="sm" />
          <div class="message-column">
            <div class="message-meta">
              <span>{{ message.senderName }}</span>
              <span v-if="message.role === 'admin'" class="role-tag">管理员</span>
              <time>{{ message.timestamp }}</time>
            </div>
            <div class="message-and-actions">
              <div class="message-bubble" :class="{ bot: message.bot }">
                <div v-if="message.reply" class="message-reply">
                  <strong>{{ message.reply.sender }}</strong>
                  <span>{{ message.reply.content }}</span>
                </div>
                <p>{{ message.content }}</p>
                <template v-for="(attachment, index) in message.attachments" :key="`${message.id}-${index}`">
                  <img
                    v-if="attachment.kind === 'image' && attachment.url"
                    class="message-image"
                    :src="attachment.url"
                    :alt="attachment.name || '聊天图片'"
                  />
                  <button v-else-if="attachment.kind === 'file'" class="file-attachment" type="button">
                    <span class="file-icon"><FileText :size="20" /></span>
                    <span><strong>{{ attachment.name }}</strong><small>{{ attachment.size }}</small></span>
                  </button>
                </template>
                <button
                  v-if="message.runId"
                  class="run-link"
                  type="button"
                  title="定位到 Agent Run"
                  @click="emit('openAgent')"
                >
                  <Sparkles :size="12" />由 Agent {{ message.runId }} 生成
                </button>
              </div>
              <div v-if="!message.mine" class="message-actions">
                <button type="button" title="交给 Agent" aria-label="交给 Agent" @click="emit('sendToAgent', message)">
                  <Sparkles :size="14" />
                </button>
                <button type="button" title="回复" aria-label="回复" @click="composer = `@${message.senderName} `">
                  <MessageSquareReply :size="14" />
                </button>
                <button type="button" title="更多" aria-label="更多" @click="quickAction('消息操作已打开')">
                  <MoreHorizontal :size="14" />
                </button>
              </div>
            </div>
            <div v-if="message.reactions?.length" class="reaction-row">
              <button v-for="reaction in message.reactions" :key="reaction.emoji" type="button">
                {{ reaction.emoji }} {{ reaction.count }}
              </button>
            </div>
          </div>
        </article>

        <div v-if="!loading && !error && !messages.length" class="chat-empty">
          <MessageSquareReply :size="30" />
          <strong>还没有消息</strong>
        </div>
      </section>

      <footer class="chat-composer">
        <div class="composer-toolbar">
          <div>
            <button class="icon-button" type="button" title="表情" aria-label="表情" @click="quickAction('表情面板已打开')">
              <SmilePlus :size="18" />
            </button>
            <button class="icon-button" type="button" title="图片" aria-label="图片" @click="quickAction('请选择图片')">
              <ImagePlus :size="18" />
            </button>
            <button class="icon-button" type="button" title="文件" aria-label="文件" @click="quickAction('请选择文件')">
              <Paperclip :size="18" />
            </button>
          </div>
          <button class="agent-command" type="button" title="在 Agent Console 中处理" @click="emit('openAgent')">
            <Sparkles :size="15" />
            <span>交给 Agent</span>
          </button>
        </div>
        <textarea
          v-model="composer"
          :placeholder="`发送给 ${conversation.name}`"
          rows="3"
          aria-label="QQ 消息输入"
          :disabled="sending"
          @keydown="handleKeydown"
        />
        <div class="composer-footer">
          <span v-if="account" class="send-identity">
            <AppAvatar :src="account.avatar" :name="account.name" size="xs" :status="account.status" />
            {{ account.shortName }}
          </span>
          <span v-else />
          <button class="send-button" type="button" title="发送消息" aria-label="发送消息" :disabled="!composer.trim() || sending" @click="send">
            <LoaderCircle v-if="sending" class="spin" :size="17" />
            <SendHorizontal v-else :size="17" />
          </button>
        </div>
      </footer>
    </template>

    <div v-else class="chat-placeholder">
      <Sparkles :size="34" />
      <strong>选择一个会话</strong>
    </div>
  </main>
</template>

<style scoped>
.chat-pane {
  display: flex;
  min-width: 0;
  min-height: 0;
  flex-direction: column;
  background: var(--chat-background);
}

.chat-header {
  display: flex;
  height: 64px;
  min-width: 0;
  flex: 0 0 auto;
  align-items: center;
  gap: 10px;
  border-bottom: 1px solid var(--border);
  background: var(--surface-glass);
  padding: 0 14px 0 18px;
  backdrop-filter: blur(12px);
}

.mobile-back,
.chat-header__avatar {
  display: none;
}

.chat-heading {
  min-width: 0;
  flex: 1;
}

.chat-heading__title {
  display: flex;
  min-width: 0;
  align-items: center;
  gap: 7px;
}

.chat-heading h2 {
  min-width: 0;
  overflow: hidden;
  margin: 0;
  color: var(--text);
  font-size: 15px;
  font-weight: 700;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.chat-heading p {
  overflow: hidden;
  margin: 3px 0 0;
  color: var(--text-muted);
  font-size: 10px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.type-chip,
.role-tag {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  border-radius: 4px;
  color: var(--brand-strong);
  background: var(--brand-soft-strong);
  font-size: 9px;
  font-weight: 700;
}

.type-chip {
  width: 19px;
  height: 17px;
}

.role-tag {
  height: 15px;
  padding: 0 4px;
}

.muted {
  color: var(--text-muted);
}

.chat-actions,
.composer-toolbar > div {
  display: flex;
  align-items: center;
  gap: 2px;
}

.agent-toggle.active {
  color: var(--brand-strong);
  background: var(--brand-soft);
}

.message-list {
  min-height: 0;
  flex: 1;
  overflow-y: auto;
  overscroll-behavior: contain;
  padding: 16px clamp(14px, 3vw, 34px) 26px;
}

.date-divider {
  display: flex;
  align-items: center;
  justify-content: center;
  margin: 2px 0 20px;
}

.date-divider span {
  border: 1px solid var(--border);
  border-radius: 4px;
  color: var(--text-muted);
  background: var(--surface-glass);
  padding: 3px 8px;
  font-size: 9px;
}

.message-row {
  display: flex;
  max-width: 100%;
  align-items: flex-start;
  gap: 9px;
  margin-bottom: 17px;
  border-radius: 7px;
  outline: 4px solid transparent;
  transition: background 160ms ease, outline-color 160ms ease;
}

.message-row.selected {
  background: var(--warning-soft);
  outline-color: var(--warning-soft);
}

.message-row.mine {
  flex-direction: row-reverse;
}

.message-column {
  display: flex;
  min-width: 0;
  max-width: min(600px, 78%);
  flex-direction: column;
  align-items: flex-start;
}

.message-row.mine .message-column {
  align-items: flex-end;
}

.message-meta {
  display: flex;
  align-items: center;
  gap: 6px;
  margin: 0 3px 5px;
  color: var(--text-secondary);
  font-size: 10px;
}

.message-row.mine .message-meta {
  flex-direction: row-reverse;
}

.message-meta time {
  color: var(--text-muted);
  font-size: 9px;
  font-variant-numeric: tabular-nums;
}

.message-and-actions {
  display: flex;
  align-items: center;
  gap: 7px;
}

.message-row.mine .message-and-actions {
  flex-direction: row-reverse;
}

.message-bubble {
  overflow: hidden;
  border: 1px solid var(--bubble-border);
  border-radius: 3px 8px 8px;
  color: var(--text);
  background: var(--message-incoming);
  box-shadow: var(--bubble-shadow);
  padding: 9px 12px;
  font-size: 12px;
  line-height: 1.65;
}

.message-row.mine .message-bubble {
  border-color: var(--message-outgoing-border);
  border-radius: 8px 3px 8px 8px;
  background: var(--message-outgoing);
}

.message-bubble.bot {
  border-color: var(--brand-border);
}

.message-bubble p {
  margin: 0;
  white-space: pre-wrap;
  overflow-wrap: anywhere;
}

.message-reply {
  display: flex;
  min-width: 0;
  flex-direction: column;
  margin: -2px 0 7px;
  border-left: 2px solid var(--brand);
  color: var(--text-secondary);
  padding-left: 8px;
  font-size: 10px;
  line-height: 1.45;
}

.message-reply strong {
  color: var(--brand-strong);
}

.message-reply span {
  overflow: hidden;
  max-width: 330px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.message-image {
  display: block;
  width: min(360px, 100%);
  max-height: 300px;
  margin-top: 8px;
  border-radius: 6px;
  object-fit: cover;
}

.file-attachment {
  display: grid;
  width: min(280px, 100%);
  cursor: pointer;
  grid-template-columns: 38px minmax(0, 1fr);
  align-items: center;
  gap: 9px;
  margin-top: 8px;
  border: 1px solid var(--border);
  border-radius: 6px;
  color: var(--text);
  background: var(--surface);
  padding: 8px;
  text-align: left;
}

.file-icon {
  display: grid;
  width: 36px;
  height: 36px;
  place-items: center;
  border-radius: 6px;
  color: var(--accent-strong);
  background: var(--accent-soft);
}

.file-attachment strong,
.file-attachment small {
  display: block;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.file-attachment strong {
  font-size: 11px;
}

.file-attachment small {
  margin-top: 2px;
  color: var(--text-muted);
  font-size: 9px;
}

.run-link {
  display: flex;
  cursor: pointer;
  align-items: center;
  gap: 4px;
  margin-top: 7px;
  border: 0;
  color: var(--brand-strong);
  background: transparent;
  padding: 0;
  font-size: 9px;
}

.message-actions {
  display: flex;
  visibility: hidden;
  align-items: center;
  gap: 2px;
  opacity: 0;
  transition: opacity 130ms ease;
}

.message-row:hover .message-actions,
.message-row.selected .message-actions {
  visibility: visible;
  opacity: 1;
}

.message-actions button {
  display: grid;
  width: 26px;
  height: 26px;
  cursor: pointer;
  place-items: center;
  border: 1px solid var(--border);
  border-radius: 5px;
  color: var(--text-muted);
  background: var(--surface);
}

.message-actions button:hover {
  color: var(--brand-strong);
  border-color: var(--brand-border);
}

.reaction-row {
  display: flex;
  gap: 4px;
  margin-top: 5px;
}

.reaction-row button {
  cursor: pointer;
  border: 1px solid var(--brand-border);
  border-radius: 8px;
  color: var(--text-secondary);
  background: var(--brand-soft);
  padding: 2px 6px;
  font-size: 9px;
}

.chat-composer {
  min-height: 145px;
  flex: 0 0 auto;
  border-top: 1px solid var(--border);
  background: var(--surface);
  padding: 7px 13px 9px;
}

.composer-toolbar,
.composer-footer {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.composer-toolbar {
  height: 30px;
}

.agent-command {
  display: inline-flex;
  height: 27px;
  cursor: pointer;
  align-items: center;
  gap: 5px;
  border: 1px solid var(--brand-border);
  border-radius: 6px;
  color: var(--brand-strong);
  background: var(--brand-soft);
  padding: 0 8px;
  font-size: 10px;
  font-weight: 650;
}

.chat-composer textarea {
  display: block;
  width: 100%;
  height: 64px;
  resize: none;
  border: 0;
  color: var(--text);
  background: transparent;
  padding: 7px 5px;
  font: inherit;
  font-size: 12px;
  line-height: 1.55;
  outline: none;
}

.chat-composer textarea::placeholder {
  color: var(--text-muted);
}

.composer-footer {
  height: 31px;
}

.send-identity {
  display: flex;
  align-items: center;
  gap: 6px;
  color: var(--text-muted);
  font-size: 9px;
}

.send-button {
  display: grid;
  width: 38px;
  height: 30px;
  cursor: pointer;
  place-items: center;
  border: 0;
  border-radius: 6px;
  color: #ffffff;
  background: var(--brand);
}

.send-button:hover:not(:disabled) {
  background: var(--brand-strong);
}

.send-button:disabled {
  cursor: not-allowed;
  opacity: 0.42;
}

.chat-empty,
.chat-placeholder {
  display: flex;
  flex: 1;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 10px;
  color: var(--text-muted);
}

.chat-empty strong,
.chat-placeholder strong {
  color: var(--text-secondary);
  font-size: 12px;
}

.error-state {
  color: var(--danger);
}

.spin {
  animation: spin 800ms linear infinite;
}

@keyframes spin {
  to {
    transform: rotate(360deg);
  }
}

@media (max-width: 1120px) {
  .chat-header__avatar {
    display: inline-grid;
  }

  .secondary-action {
    display: none;
  }

  .message-column {
    max-width: 82%;
  }
}

@media (max-width: 860px) {
  .chat-header {
    height: 60px;
    padding: 0 10px;
  }

  .mobile-back,
  .chat-header__avatar {
    display: grid;
  }

  .chat-heading p {
    max-width: 54vw;
  }

  .message-list {
    padding: 14px 12px 20px;
  }

  .message-column {
    max-width: 84%;
  }

  .message-actions {
    display: none;
  }

  .chat-composer {
    min-height: 132px;
    padding-bottom: max(8px, env(safe-area-inset-bottom));
  }

  .agent-command span {
    display: none;
  }
}

@media (max-width: 480px) {
  .chat-header__avatar {
    display: none;
  }

  .chat-heading p {
    max-width: 48vw;
  }

  .message-row {
    gap: 7px;
  }

  .message-column {
    max-width: calc(100% - 42px);
  }

  .message-bubble {
    padding: 8px 10px;
    font-size: 12px;
  }
}
</style>

<script setup lang="ts">
import { Bot, Check, Inbox, Pin, Search, SlidersHorizontal, VolumeX } from '@lucide/vue'
import { computed } from 'vue'

import { hasComposerDraft } from '../services/composer-content'
import type { Account, Conversation } from '../types/workspace'
import AppAvatar from './AppAvatar.vue'

const props = defineProps<{
  accounts: Account[]
  conversations: Conversation[]
  drafts: Record<string, string>
  selectedConversationId: string
  selectedAccountId: string
  searchQuery: string
  unreadOnly: boolean
  onlineCount: number
}>()

const emit = defineEmits<{
  selectConversation: [id: string]
  selectAccount: [id: string]
  updateSearch: [value: string]
  toggleUnread: []
}>()

const selectedLabel = computed(() => {
  if (props.selectedAccountId === 'all') return '全部账号'
  return props.accounts.find((item) => item.id === props.selectedAccountId)?.name ?? '全部账号'
})

function accountFor(conversation: Conversation): Account | undefined {
  return props.accounts.find((item) => item.id === conversation.accountId)
}
</script>

<template>
  <aside class="conversation-sidebar" aria-label="会话列表">
    <header class="sidebar-header">
      <div class="product-heading">
        <span class="product-heading__eyebrow">DUDUDA</span>
        <h1>消息工作台</h1>
      </div>
      <button class="icon-button mobile-account" type="button" :title="selectedLabel">
        <Bot :size="19" />
      </button>
    </header>

    <div class="account-filter-wrap">
      <select
        class="account-filter"
        :value="selectedAccountId"
        aria-label="筛选账号"
        @change="emit('selectAccount', ($event.target as HTMLSelectElement).value)"
      >
        <option value="all">全部账号</option>
        <option v-for="account in accounts" :key="account.id" :value="account.id">{{ account.name }}</option>
      </select>
      <span class="account-filter__state">
        <span class="online-dot" />
        {{ onlineCount }}/{{ accounts.length }} 在线
      </span>
    </div>

    <div class="search-row">
      <label class="search-box">
        <Search :size="16" />
        <input
          :value="searchQuery"
          type="search"
          placeholder="搜索会话或消息"
          aria-label="搜索会话或消息"
          @input="emit('updateSearch', ($event.target as HTMLInputElement).value)"
        />
      </label>
      <button
        class="filter-button"
        :class="{ active: unreadOnly }"
        type="button"
        title="只看未读"
        aria-label="只看未读"
        :aria-pressed="unreadOnly"
        @click="emit('toggleUnread')"
      >
        <SlidersHorizontal :size="17" />
      </button>
    </div>

    <div class="list-heading">
      <span>{{ selectedAccountId === 'all' ? '全局收件箱' : '账号会话' }}</span>
      <span>{{ conversations.length }}</span>
    </div>

    <div class="conversation-list">
      <button
        v-for="conversation in conversations"
        :key="conversation.id"
        class="conversation-item"
        :class="{ selected: conversation.id === selectedConversationId, pinned: conversation.pinned }"
        type="button"
        @click="emit('selectConversation', conversation.id)"
      >
        <span v-if="conversation.id === selectedConversationId" class="active-marker" />
        <span class="conversation-avatar">
          <AppAvatar :src="conversation.avatar" :name="conversation.name" size="md" />
          <AppAvatar
            v-if="selectedAccountId === 'all' && accountFor(conversation)"
            class="source-account"
            :src="accountFor(conversation)?.avatar"
            :name="accountFor(conversation)?.name ?? ''"
            size="xs"
          />
        </span>
        <span class="conversation-copy">
          <span class="conversation-title-row">
            <strong>{{ conversation.name }}</strong>
            <Pin v-if="conversation.pinned" :size="11" class="pin-icon" />
            <time>{{ conversation.lastMessageAt }}</time>
          </span>
          <span class="conversation-preview-row">
            <span v-if="hasComposerDraft(drafts[conversation.id] ?? '')" class="draft-label">草稿</span>
            <span class="conversation-preview">{{ conversation.lastMessage }}</span>
            <VolumeX v-if="conversation.muted" :size="13" class="muted-icon" />
            <span v-if="conversation.unread" class="unread-badge">{{ conversation.unread > 99 ? '99+' : conversation.unread }}</span>
          </span>
          <span v-if="selectedAccountId === 'all'" class="source-label">
            <span :class="`source-label__dot source-label__dot--${accountFor(conversation)?.accent ?? 'cyan'}`" />
            {{ accountFor(conversation)?.shortName }}
          </span>
        </span>
      </button>

      <div v-if="!conversations.length" class="empty-state">
        <Inbox :size="26" />
        <strong>没有匹配的会话</strong>
        <span>调整账号或未读筛选</span>
      </div>
    </div>

    <footer class="sidebar-footer">
      <span><span class="online-dot" />NapCat 实时连接</span>
      <span><Check :size="13" />{{ onlineCount }} 个账号</span>
    </footer>
  </aside>
</template>

<style scoped>
.conversation-sidebar {
  display: flex;
  min-width: 0;
  min-height: 0;
  flex-direction: column;
  border-right: 1px solid var(--border);
  background: var(--surface);
}

.sidebar-header {
  display: flex;
  height: 72px;
  flex: 0 0 auto;
  align-items: center;
  justify-content: space-between;
  padding: 0 18px 0 20px;
}

.product-heading__eyebrow {
  display: block;
  color: var(--brand-strong);
  font-size: 9px;
  font-weight: 800;
  letter-spacing: 0.12em;
  line-height: 1;
}

.product-heading h1 {
  margin: 5px 0 0;
  color: var(--text);
  font-size: 19px;
  font-weight: 730;
  letter-spacing: 0;
}

.mobile-account {
  display: none;
}

.account-filter-wrap {
  display: flex;
  height: 33px;
  flex: 0 0 auto;
  align-items: center;
  justify-content: space-between;
  margin: 0 12px 10px;
  border-bottom: 1px solid var(--border);
  padding: 0 7px 8px;
}

.account-filter {
  max-width: 170px;
  cursor: pointer;
  border: 0;
  color: var(--text-secondary);
  background: transparent;
  font: inherit;
  font-size: 12px;
  font-weight: 650;
  outline: none;
}

.account-filter__state {
  display: flex;
  align-items: center;
  gap: 5px;
  color: var(--text-muted);
  font-size: 10px;
  white-space: nowrap;
}

.online-dot {
  display: inline-block;
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: var(--success);
  box-shadow: 0 0 0 2px var(--success-soft);
}

.search-row {
  display: grid;
  height: 40px;
  flex: 0 0 auto;
  grid-template-columns: minmax(0, 1fr) 36px;
  gap: 7px;
  margin: 0 12px 10px;
}

.search-box {
  display: flex;
  min-width: 0;
  align-items: center;
  gap: 8px;
  border: 1px solid transparent;
  border-radius: 7px;
  color: var(--text-muted);
  background: var(--surface-muted);
  padding: 0 11px;
}

.search-box:focus-within {
  border-color: var(--brand-border);
  background: var(--surface);
  box-shadow: 0 0 0 2px var(--brand-soft);
}

.search-box input {
  width: 100%;
  min-width: 0;
  border: 0;
  color: var(--text);
  background: transparent;
  font: inherit;
  font-size: 12px;
  outline: 0;
}

.search-box input::placeholder {
  color: var(--text-muted);
}

.filter-button {
  display: grid;
  cursor: pointer;
  place-items: center;
  border: 1px solid var(--border);
  border-radius: 7px;
  color: var(--text-muted);
  background: var(--surface);
}

.filter-button:hover,
.filter-button.active {
  color: var(--brand-strong);
  border-color: var(--brand-border);
  background: var(--brand-soft);
}

.list-heading {
  display: flex;
  flex: 0 0 auto;
  align-items: center;
  justify-content: space-between;
  padding: 0 17px 7px 18px;
  color: var(--text-muted);
  font-size: 10px;
  font-weight: 680;
}

.conversation-list {
  min-height: 0;
  flex: 1;
  overflow-y: auto;
  padding: 0 7px 14px;
}

.conversation-item {
  position: relative;
  display: grid;
  width: 100%;
  min-height: 67px;
  cursor: pointer;
  grid-template-columns: 44px minmax(0, 1fr);
  align-items: center;
  gap: 11px;
  border: 0;
  border-radius: 7px;
  color: inherit;
  background: transparent;
  padding: 9px 10px;
  text-align: left;
  transition: background 130ms ease;
}

.conversation-item:hover {
  background: var(--surface-hover);
}

.conversation-item.pinned:not(.selected) {
  background: var(--surface-pinned);
}

.conversation-item.selected {
  background: var(--brand-soft);
}

.active-marker {
  position: absolute;
  top: 9px;
  bottom: 9px;
  left: -7px;
  width: 3px;
  border-radius: 0 3px 3px 0;
  background: var(--brand);
}

.conversation-avatar {
  position: relative;
  display: block;
  width: 44px;
  height: 44px;
}

.source-account {
  position: absolute;
  right: -4px;
  bottom: -4px;
  padding: 2px;
  border-radius: 50%;
  background: var(--surface);
}

.conversation-copy {
  display: block;
  min-width: 0;
}

.conversation-title-row,
.conversation-preview-row {
  display: flex;
  min-width: 0;
  align-items: center;
}

.conversation-title-row {
  gap: 5px;
}

.conversation-title-row strong {
  min-width: 0;
  overflow: hidden;
  flex: 1;
  color: var(--text);
  font-size: 13px;
  font-weight: 680;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.conversation-title-row time {
  flex: 0 0 auto;
  color: var(--text-muted);
  font-size: 9px;
  font-variant-numeric: tabular-nums;
}

.pin-icon {
  flex: 0 0 auto;
  color: var(--brand);
}

.conversation-preview-row {
  gap: 5px;
  margin-top: 4px;
}

.conversation-preview {
  min-width: 0;
  overflow: hidden;
  flex: 1;
  color: var(--text-secondary);
  font-size: 11px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.draft-label {
  flex: 0 0 auto;
  color: var(--danger);
  font-size: 11px;
  font-weight: 700;
}

.muted-icon {
  flex: 0 0 auto;
  color: var(--text-muted);
}

.unread-badge {
  display: grid;
  min-width: 18px;
  height: 18px;
  flex: 0 0 auto;
  place-items: center;
  border-radius: 9px;
  color: #ffffff;
  background: var(--danger);
  padding: 0 5px;
  font-size: 9px;
  font-weight: 750;
}

.source-label {
  display: flex;
  align-items: center;
  gap: 4px;
  margin-top: 3px;
  color: var(--text-muted);
  font-size: 9px;
}

.source-label__dot {
  width: 5px;
  height: 5px;
  border-radius: 50%;
}

.source-label__dot--cyan {
  background: var(--brand);
}

.source-label__dot--green {
  background: var(--success);
}

.source-label__dot--coral {
  background: var(--accent);
}

.empty-state {
  display: flex;
  height: 180px;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 7px;
  color: var(--text-muted);
}

.empty-state strong {
  color: var(--text-secondary);
  font-size: 12px;
}

.empty-state span {
  font-size: 10px;
}

.sidebar-footer {
  display: flex;
  height: 35px;
  flex: 0 0 auto;
  align-items: center;
  justify-content: space-between;
  border-top: 1px solid var(--border);
  color: var(--text-muted);
  background: var(--surface-subtle);
  padding: 0 14px;
  font-size: 9px;
}

.sidebar-footer span {
  display: flex;
  align-items: center;
  gap: 5px;
}

@media (max-width: 860px) {
  .conversation-sidebar {
    border-right: 0;
  }

  .sidebar-header {
    height: 66px;
    padding-right: 14px;
  }

  .mobile-account {
    display: grid;
  }

  .conversation-item {
    min-height: 72px;
    grid-template-columns: 48px minmax(0, 1fr);
    padding-right: 12px;
    padding-left: 12px;
  }

  .conversation-avatar {
    width: 48px;
    height: 48px;
  }

  .conversation-avatar :deep(.avatar--md) {
    width: 48px;
    height: 48px;
  }
}
</style>

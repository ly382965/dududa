<script setup lang="ts">
import { Bot, LoaderCircle, RefreshCw, Search, Settings2, UserRound, UsersRound } from '@lucide/vue'
import { computed, ref, watch } from 'vue'

import AppAvatar from '../components/AppAvatar.vue'
import { createSearchMatcher } from '../services/search'
import { useQqDirectoryStore } from '../stores/qq-directory'
import type { Account } from '../types/workspace'

const props = defineProps<{ account?: Account }>()
const emit = defineEmits<{
  openConversation: [type: 'group' | 'private', peerId: string]
  openGroup: [groupId: string]
}>()

const store = useQqDirectoryStore()
const mode = ref<'friends' | 'groups'>('friends')
const query = ref('')
const directory = computed(() => (props.account ? store.directories[props.account.id] : undefined))
const requestKey = computed(() => `directory:${props.account?.id ?? ''}`)
const busy = computed(() => Boolean(store.loading[requestKey.value]))
const error = computed(() => store.errors[requestKey.value] || '')

const contacts = computed(() => {
  const matches = createSearchMatcher(query.value)
  if (mode.value === 'friends') {
    return (directory.value?.friends ?? [])
      .map((friend) => ({
        id: friend.userId,
        name: friend.remark.trim() || friend.nickname.trim() || friend.userId,
        detail: friend.categoryName || '好友',
        avatar: friend.avatar,
        type: 'private' as const,
      }))
      .filter((item) => matches(`${item.name}\n${item.id}\n${item.detail}`))
  }
  return (directory.value?.groups ?? [])
    .map((group) => ({
      id: group.groupId,
      name: group.remark.trim() || group.groupName.trim() || group.groupId,
      detail: `${group.memberCount} 位成员`,
      avatar: group.avatar,
      type: 'group' as const,
    }))
    .filter((item) => matches(`${item.name}\n${item.id}`))
})

watch(
  () => props.account?.id,
  (accountId) => {
    query.value = ''
    if (accountId) void store.loadDirectory(accountId)
  },
  { immediate: true },
)
</script>

<template>
  <main class="directory-view">
    <header class="view-header">
      <div>
        <small>QQ DIRECTORY</small>
        <h1>联系人</h1>
      </div>
      <button
        class="icon-button"
        type="button"
        title="刷新联系人"
        :disabled="busy || !account"
        @click="account && store.loadDirectory(account.id, true)"
      >
        <RefreshCw :class="{ spin: busy }" :size="17" />
      </button>
    </header>

    <div class="directory-tools">
      <div class="segmented-control" role="tablist" aria-label="联系人类型">
        <button :class="{ active: mode === 'friends' }" type="button" @click="mode = 'friends'">
          <UserRound :size="15" />好友 <span>{{ directory?.friends.length || 0 }}</span>
        </button>
        <button :class="{ active: mode === 'groups' }" type="button" @click="mode = 'groups'">
          <UsersRound :size="15" />群聊 <span>{{ directory?.groups.length || 0 }}</span>
        </button>
      </div>
      <label class="directory-search">
        <Search :size="16" />
        <input v-model="query" type="search" placeholder="昵称、群名或 QQ 号" aria-label="搜索联系人" />
      </label>
    </div>

    <p v-if="error" class="inline-error" role="alert">{{ error }}</p>
    <div v-if="busy && !directory" class="directory-state"><LoaderCircle class="spin" :size="24" />正在读取 NapCat 联系人</div>
    <section v-else class="contact-grid" :aria-label="mode === 'friends' ? '好友列表' : '群聊列表'">
      <article v-for="item in contacts" :key="item.id" class="contact-item">
        <button class="contact-main" type="button" @click="emit('openConversation', item.type, item.id)">
          <AppAvatar :src="item.avatar" :name="item.name" size="md" />
          <span class="contact-copy">
            <strong>{{ item.name }}</strong>
            <small>{{ item.detail }} · {{ item.id }}</small>
          </span>
          <Bot v-if="item.type === 'private' && /bot/i.test(item.name)" class="bot-mark" :size="15" />
        </button>
        <button
          v-if="item.type === 'group'"
          class="icon-button group-settings"
          type="button"
          title="群聊管理"
          @click="emit('openGroup', item.id)"
        >
          <Settings2 :size="17" />
        </button>
      </article>
      <div v-if="!contacts.length" class="directory-state">
        <component :is="mode === 'friends' ? UserRound : UsersRound" :size="26" />
        {{ query ? '没有匹配的联系人' : '当前账号暂无联系人' }}
      </div>
    </section>
  </main>
</template>

<style scoped>
.directory-view {
  min-height: 0;
  overflow-y: auto;
  background: var(--app-background);
  padding: 24px clamp(16px, 3vw, 38px) 40px;
}

.view-header,
.directory-tools {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 18px;
}

.view-header {
  border-bottom: 1px solid var(--border);
  padding-bottom: 17px;
}

.view-header small {
  color: var(--brand-strong);
  font-size: 9px;
  font-weight: 800;
}

h1 {
  margin: 4px 0 0;
  color: var(--text);
  font-size: 22px;
  letter-spacing: 0;
}

.directory-tools {
  margin: 18px 0;
}

.segmented-control {
  display: grid;
  grid-template-columns: repeat(2, minmax(110px, 1fr));
  border-radius: 6px;
  background: var(--surface-muted);
  padding: 3px;
}

.segmented-control button {
  display: flex;
  height: 34px;
  cursor: pointer;
  align-items: center;
  justify-content: center;
  gap: 6px;
  border: 0;
  border-radius: 4px;
  color: var(--text-muted);
  background: transparent;
  font-size: 11px;
  font-weight: 650;
}

.segmented-control button.active {
  color: var(--text);
  background: var(--surface);
  box-shadow: 0 1px 4px rgb(19 37 41 / 8%);
}

.segmented-control span {
  color: var(--text-muted);
  font-size: 9px;
}

.directory-search {
  display: flex;
  width: min(340px, 48vw);
  height: 38px;
  align-items: center;
  gap: 8px;
  border: 1px solid var(--border);
  border-radius: 6px;
  color: var(--text-muted);
  background: var(--surface);
  padding: 0 11px;
}

.directory-search input {
  width: 100%;
  min-width: 0;
  border: 0;
  color: var(--text);
  background: transparent;
  font: inherit;
  font-size: 11px;
  outline: 0;
}

.contact-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(260px, 1fr));
  gap: 8px;
}

.contact-item {
  display: grid;
  min-width: 0;
  min-height: 68px;
  grid-template-columns: minmax(0, 1fr) auto;
  align-items: center;
  border: 1px solid var(--border);
  border-radius: 7px;
  background: var(--surface);
}

.contact-item:hover {
  border-color: var(--brand-border);
}

.contact-main {
  display: flex;
  min-width: 0;
  height: 100%;
  cursor: pointer;
  align-items: center;
  gap: 11px;
  border: 0;
  color: inherit;
  background: transparent;
  padding: 10px 12px;
  text-align: left;
}

.contact-copy {
  display: grid;
  min-width: 0;
  flex: 1;
  gap: 4px;
}

.contact-main strong,
.contact-main small {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.contact-main strong {
  color: var(--text);
  font-size: 12px;
}

.contact-main small {
  color: var(--text-muted);
  font-size: 9px;
}

.group-settings {
  margin-right: 8px;
}

.bot-mark {
  color: var(--accent-strong);
}

.directory-state {
  display: grid;
  min-height: 210px;
  grid-column: 1 / -1;
  place-content: center;
  place-items: center;
  gap: 9px;
  color: var(--text-muted);
  font-size: 11px;
}

.inline-error {
  border-left: 3px solid var(--danger);
  color: var(--danger);
  background: var(--danger-soft);
  padding: 8px 10px;
  font-size: 10px;
}

.spin {
  animation: spin 850ms linear infinite;
}

@keyframes spin {
  to { transform: rotate(360deg); }
}

@media (max-width: 620px) {
  .directory-view {
    padding: 18px 13px 28px;
  }

  .directory-tools {
    align-items: stretch;
    flex-direction: column;
  }

  .directory-search {
    width: 100%;
  }

  .contact-grid {
    grid-template-columns: minmax(0, 1fr);
  }
}
</style>

<script setup lang="ts">
import {
  Bell,
  Bot,
  Contact,
  Inbox,
  MessageCircle,
  Moon,
  Plus,
  Settings,
  Sparkles,
  Sun,
  UsersRound,
} from '@lucide/vue'

import type { Account, MobilePanel, ThemeMode } from '../types/workspace'
import AppAvatar from './AppAvatar.vue'

defineProps<{
  accounts: Account[]
  selectedAccountId: string
  totalUnread: number
  mobilePanel: MobilePanel
  theme: ThemeMode
  agentActive: boolean
  activeRoute: 'chat' | 'contacts' | 'notifications' | 'settings'
  notificationCount: number
}>()

const emit = defineEmits<{
  selectAccount: [id: string]
  setMobilePanel: [panel: MobilePanel]
  toggleTheme: []
  openAgent: []
  openSettings: []
  addAccount: []
  navigate: [route: 'chat' | 'contacts' | 'notifications' | 'settings']
}>()
</script>

<template>
  <aside class="account-rail" aria-label="账号与工作台导航">
    <div class="brand-mark" title="嘟嘟哒">
      <Bot :size="22" stroke-width="2.1" />
      <span class="brand-mark__dot" />
    </div>

    <nav class="route-nav" aria-label="QQ 工作区">
      <button class="rail-button" :class="{ active: activeRoute === 'chat' }" type="button" title="消息" aria-label="消息" @click="emit('navigate', 'chat')"><MessageCircle :size="19" /></button>
      <button class="rail-button" :class="{ active: activeRoute === 'contacts' }" type="button" title="联系人" aria-label="联系人" @click="emit('navigate', 'contacts')"><Contact :size="19" /></button>
      <button class="rail-button" :class="{ active: activeRoute === 'notifications' }" type="button" title="通知" aria-label="通知" @click="emit('navigate', 'notifications')"><Bell :size="19" /><span v-if="notificationCount" class="rail-badge">{{ notificationCount > 99 ? '99+' : notificationCount }}</span></button>
      <button class="rail-button" :class="{ active: activeRoute === 'settings' }" type="button" title="设置" aria-label="设置" @click="emit('navigate', 'settings')"><Settings :size="19" /></button>
    </nav>

    <nav class="account-list" aria-label="QQ 账号">
      <button
        class="rail-button all-accounts"
        :class="{ active: selectedAccountId === 'all' }"
        type="button"
        title="全部账号"
        aria-label="全部账号"
        @click="emit('selectAccount', 'all')"
      >
        <UsersRound :size="20" />
        <span v-if="totalUnread" class="rail-badge">{{ totalUnread > 99 ? '99+' : totalUnread }}</span>
      </button>
      <button
        v-for="account in accounts"
        :key="account.id"
        class="account-button"
        :class="{ active: selectedAccountId === account.id }"
        type="button"
        :title="account.name"
        :aria-label="account.name"
        @click="emit('selectAccount', account.id)"
      >
        <AppAvatar :src="account.avatar" :name="account.name" size="sm" :status="account.status" />
        <span v-if="account.unread" class="account-badge">{{ account.unread > 9 ? '9+' : account.unread }}</span>
      </button>
      <button class="rail-button add-account" type="button" title="添加账号" aria-label="添加账号" @click="emit('addAccount')">
        <Plus :size="19" />
      </button>
    </nav>

    <div class="rail-tools">
      <button
        class="rail-button"
        :class="{ active: agentActive }"
        type="button"
        title="Agent Console"
        aria-label="打开 Agent Console"
        @click="emit('openAgent')"
      >
        <Sparkles :size="19" />
      </button>
      <button class="rail-button" type="button" title="切换主题" aria-label="切换主题" @click="emit('toggleTheme')">
        <Moon v-if="theme === 'light'" :size="19" />
        <Sun v-else :size="19" />
      </button>
    </div>

    <nav class="mobile-nav" aria-label="移动端工作区导航">
      <button :class="{ active: activeRoute === 'chat' }" type="button" @click="emit('navigate', 'chat'); emit('setMobilePanel', 'inbox')">
        <Inbox :size="21" />
        <span>消息</span>
        <b v-if="totalUnread">{{ totalUnread }}</b>
      </button>
      <button :class="{ active: activeRoute === 'contacts' }" type="button" @click="emit('navigate', 'contacts')">
        <Contact :size="21" />
        <span>联系人</span>
      </button>
      <button :class="{ active: activeRoute === 'notifications' }" type="button" @click="emit('navigate', 'notifications')">
        <Bell :size="21" />
        <span>通知</span>
        <b v-if="notificationCount">{{ notificationCount }}</b>
      </button>
      <button :class="{ active: mobilePanel === 'agent' }" type="button" @click="emit('setMobilePanel', 'agent')">
        <Sparkles :size="21" />
        <span>Agent</span>
      </button>
      <button :class="{ active: activeRoute === 'settings' }" type="button" @click="emit('navigate', 'settings')">
        <Settings :size="21" />
        <span>设置</span>
      </button>
    </nav>
  </aside>
</template>

<style scoped>
.account-rail {
  position: relative;
  z-index: 30;
  display: flex;
  min-height: 0;
  flex-direction: column;
  align-items: center;
  border-right: 1px solid var(--border);
  background: var(--surface);
  padding: 14px 10px 12px;
}

.brand-mark {
  position: relative;
  display: grid;
  width: 38px;
  height: 38px;
  flex: 0 0 auto;
  place-items: center;
  border-radius: 8px;
  color: #ffffff;
  background: var(--brand);
  box-shadow: 0 6px 18px rgb(24 109 123 / 18%);
}

.brand-mark__dot {
  position: absolute;
  right: 5px;
  bottom: 5px;
  width: 5px;
  height: 5px;
  border: 1px solid #ffffff;
  border-radius: 50%;
  background: var(--accent);
}

.account-list,
.route-nav,
.rail-tools {
  display: flex;
  width: 100%;
  flex-direction: column;
  align-items: center;
  gap: 8px;
}

.account-list {
  margin-top: 12px;
  overflow-y: auto;
  padding: 3px 0;
  scrollbar-width: none;
}

.route-nav {
  margin-top: 15px;
  padding-bottom: 10px;
  border-bottom: 1px solid var(--border);
}

.account-list::-webkit-scrollbar {
  display: none;
}

.rail-tools {
  margin-top: auto;
}

.rail-button,
.account-button {
  position: relative;
  display: grid;
  width: 42px;
  height: 42px;
  flex: 0 0 auto;
  cursor: pointer;
  place-items: center;
  border: 0;
  border-radius: 7px;
  color: var(--text-secondary);
  background: transparent;
  transition: color 150ms ease, background 150ms ease, transform 150ms ease;
}

.rail-button:hover,
.account-button:hover {
  color: var(--text);
  background: var(--surface-hover);
}

.account-button:hover {
  transform: translateY(-1px);
}

.rail-button.active,
.all-accounts.active {
  color: var(--brand-strong);
  background: var(--brand-soft);
}

.account-button::before {
  position: absolute;
  top: 10px;
  left: -10px;
  width: 3px;
  height: 22px;
  border-radius: 0 3px 3px 0;
  background: transparent;
  content: '';
}

.account-button.active::before {
  background: var(--brand);
}

.account-button.active :deep(img),
.account-button.active :deep(.avatar__fallback) {
  box-shadow: 0 0 0 2px var(--surface), 0 0 0 4px var(--brand);
}

.rail-badge,
.account-badge {
  position: absolute;
  display: grid;
  min-width: 17px;
  height: 17px;
  place-items: center;
  border: 2px solid var(--surface);
  border-radius: 9px;
  color: #ffffff;
  background: var(--danger);
  font-size: 9px;
  font-weight: 700;
  line-height: 1;
}

.rail-badge {
  top: -3px;
  right: -3px;
}

.account-badge {
  top: 0;
  right: 0;
}

.add-account {
  border: 1px dashed var(--border-strong);
  border-radius: 50%;
}

.mobile-nav {
  display: none;
}

@media (max-width: 860px) {
  .account-rail {
    grid-row: 2;
    width: 100%;
    height: 64px;
    flex-direction: row;
    border-top: 1px solid var(--border);
    border-right: 0;
    padding: 0 max(10px, env(safe-area-inset-right)) env(safe-area-inset-bottom)
      max(10px, env(safe-area-inset-left));
  }

  .brand-mark,
  .route-nav,
  .account-list,
  .rail-tools {
    display: none;
  }

  .mobile-nav {
    display: grid;
    width: 100%;
    height: 100%;
    grid-template-columns: repeat(5, minmax(0, 1fr));
  }

  .mobile-nav button {
    position: relative;
    display: flex;
    min-width: 0;
    cursor: pointer;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    gap: 3px;
    border: 0;
    color: var(--text-muted);
    background: transparent;
    font-size: 10px;
  }

  .mobile-nav button.active {
    color: var(--brand-strong);
  }

  .mobile-nav b {
    position: absolute;
    top: 7px;
    left: calc(50% + 8px);
    min-width: 16px;
    height: 16px;
    border: 2px solid var(--surface);
    border-radius: 8px;
    color: #ffffff;
    background: var(--danger);
    font-size: 8px;
    line-height: 12px;
  }
}
</style>

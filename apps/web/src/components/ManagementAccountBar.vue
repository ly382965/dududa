<script setup lang="ts">
import { Radio, ShieldCheck } from '@lucide/vue'

import type { Account } from '../types/workspace'
import AppAvatar from './AppAvatar.vue'

const props = defineProps<{
  accounts: Account[]
  accountId: string
}>()

const emit = defineEmits<{ select: [accountId: string] }>()
</script>

<template>
  <header class="management-account-bar">
    <div class="acting-account">
      <AppAvatar
        v-if="accounts.find((account) => account.id === accountId)"
        :src="accounts.find((account) => account.id === accountId)?.avatar"
        :name="accounts.find((account) => account.id === accountId)?.name || ''"
        :status="accounts.find((account) => account.id === accountId)?.status"
        size="sm"
      />
      <span class="acting-account-copy">
        <small><ShieldCheck :size="12" />操作账号</small>
        <strong>{{ accounts.find((account) => account.id === accountId)?.name || '未选择账号' }}</strong>
      </span>
    </div>
    <label>
      <Radio :size="15" />
      <select
        :value="props.accountId"
        aria-label="管理操作账号"
        @change="emit('select', ($event.target as HTMLSelectElement).value)"
      >
        <option v-for="account in accounts" :key="account.id" :value="account.id">
          {{ account.name }} · {{ account.botId }}
        </option>
      </select>
    </label>
  </header>
</template>

<style scoped>
.management-account-bar {
  display: flex;
  min-height: 62px;
  flex: 0 0 auto;
  align-items: center;
  justify-content: space-between;
  gap: 18px;
  border-bottom: 1px solid var(--border);
  background: var(--surface);
  padding: 9px 22px;
}

.acting-account {
  display: flex;
  min-width: 0;
  align-items: center;
  gap: 10px;
}

.acting-account-copy {
  display: grid;
  min-width: 0;
  gap: 2px;
}

.acting-account small {
  display: flex;
  align-items: center;
  gap: 4px;
  color: var(--brand-strong);
  font-size: 9px;
  font-weight: 750;
}

.acting-account strong {
  overflow: hidden;
  color: var(--text);
  font-size: 13px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

label {
  display: flex;
  min-width: 220px;
  height: 36px;
  align-items: center;
  gap: 7px;
  border: 1px solid var(--border);
  border-radius: 6px;
  color: var(--text-muted);
  background: var(--surface-muted);
  padding: 0 9px;
}

select {
  width: 100%;
  min-width: 0;
  border: 0;
  color: var(--text);
  background: transparent;
  font: inherit;
  font-size: 11px;
  outline: 0;
}

@media (max-width: 620px) {
  .management-account-bar {
    align-items: stretch;
    flex-direction: column;
    gap: 8px;
    padding: 9px 14px;
  }

  label {
    width: 100%;
    min-width: 0;
  }
}
</style>

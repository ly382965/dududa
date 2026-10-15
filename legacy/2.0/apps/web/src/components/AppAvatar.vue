<script setup lang="ts">
import { computed, ref } from 'vue'

const props = withDefaults(
  defineProps<{
    src?: string
    name: string
    size?: 'xs' | 'sm' | 'md' | 'lg'
    status?: 'online' | 'degraded' | 'offline'
  }>(),
  { src: '', size: 'md', status: undefined },
)

const failed = ref(false)
const initial = computed(() => props.name.trim().slice(0, 1).toLocaleUpperCase('zh-CN') || 'D')
</script>

<template>
  <span class="avatar" :class="`avatar--${size}`">
    <img v-if="src && !failed" :src="src" :alt="name" draggable="false" @error="failed = true" />
    <span v-else class="avatar__fallback" aria-hidden="true">{{ initial }}</span>
    <span v-if="status" class="avatar__status" :class="`avatar__status--${status}`" :title="status" />
  </span>
</template>

<style scoped>
.avatar {
  position: relative;
  display: inline-grid;
  flex: 0 0 auto;
  place-items: center;
}

.avatar--xs {
  width: 24px;
  height: 24px;
}

.avatar--sm {
  width: 32px;
  height: 32px;
}

.avatar--md {
  width: 42px;
  height: 42px;
}

.avatar--lg {
  width: 48px;
  height: 48px;
}

img,
.avatar__fallback {
  width: 100%;
  height: 100%;
  border-radius: 50%;
}

img {
  display: block;
  object-fit: cover;
  background: var(--surface-muted);
}

.avatar__fallback {
  display: grid;
  place-items: center;
  color: #ffffff;
  background: #3b6d75;
  font-size: 0.8rem;
  font-weight: 700;
}

.avatar__status {
  position: absolute;
  right: -1px;
  bottom: -1px;
  width: 11px;
  height: 11px;
  border: 2px solid var(--surface);
  border-radius: 50%;
}

.avatar__status--online {
  background: var(--success);
}

.avatar__status--degraded {
  background: var(--warning);
}

.avatar__status--offline {
  background: var(--text-muted);
}
</style>

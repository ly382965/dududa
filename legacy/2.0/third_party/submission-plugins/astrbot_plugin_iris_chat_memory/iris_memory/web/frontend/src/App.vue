<template>
  <v-app>
    <v-navigation-drawer v-model="drawer" :rail="rail" permanent>
      <v-list-item
        prepend-icon="mdi-brain"
        title="Iris Memory"
        nav
        @click="rail = !rail"
      >
        <template #append>
          <v-btn
            :icon="rail ? 'mdi-chevron-right' : 'mdi-chevron-left'"
            variant="text"
            size="small"
          />
        </template>
      </v-list-item>

      <v-divider />

      <v-list density="compact" nav>
        <v-list-item
          v-for="item in navItems"
          :key="item.to"
          :to="item.to"
          :prepend-icon="item.icon"
          :title="item.title"
          :value="item.to"
          color="primary"
        />
      </v-list>
    </v-navigation-drawer>

    <v-app-bar color="surface" elevation="0" border="b">
      <v-app-bar-title class="text-h6">
        {{ currentTitle }}
      </v-app-bar-title>

      <template #append>
        <v-btn
          icon="mdi-refresh"
          variant="text"
          :loading="loading"
          @click="handleRefresh"
        />

        <v-btn
          :icon="darkMode ? 'mdi-weather-sunny' : 'mdi-weather-night'"
          variant="text"
          @click="toggleTheme"
        />
      </template>
    </v-app-bar>

    <v-main>
      <v-container fluid class="pa-4">
        <router-view v-slot="{ Component }">
          <keep-alive>
            <component :is="Component" />
          </keep-alive>
        </router-view>
      </v-container>
    </v-main>

    <v-snackbar
      v-model="showError"
      color="error"
      :timeout="3000"
      location="top"
    >
      {{ error }}
    </v-snackbar>
  </v-app>
</template>

<script setup lang="ts">
import { ref, computed, watch, onMounted } from 'vue'
import { useRoute } from 'vue-router'
import { useTheme } from 'vuetify'
import { storeToRefs } from 'pinia'
import { useAppStore } from '@/stores'

const route = useRoute()
const appStore = useAppStore()
const theme = useTheme()

const { loading, error, darkMode } = storeToRefs(appStore)

const drawer = ref(true)
const rail = ref(false)
const showError = ref(false)

watch(darkMode, (val) => {
  theme.global.name.value = val ? 'dark' : 'light'
}, { immediate: true })

onMounted(() => {
  appStore.initTheme()
})

const navItems = [
  { to: '/dashboard', title: '仪表盘', icon: 'mdi-view-dashboard' },
  { to: '/l1-buffer', title: 'L1 缓冲', icon: 'mdi-lightning-bolt' },
  { to: '/l2-memory', title: 'L2 记忆', icon: 'mdi-database-search' },
  { to: '/l3-graph', title: 'L3 图谱', icon: 'mdi-graph' },
  { to: '/profile', title: '画像管理', icon: 'mdi-account-group' },
  { to: '/data-manage', title: '数据管理', icon: 'mdi-swap-vertical' },
  { to: '/hidden-config', title: '隐藏参数', icon: 'mdi-cog-outline' }
]

const currentTitle = computed(() => {
  const item = navItems.find(i => i.to === route.path)
  return item?.title || 'Iris Memory'
})

const handleRefresh = () => {
  window.dispatchEvent(new CustomEvent('iris:refresh'))
}

const toggleTheme = () => {
  appStore.toggleTheme()
}

watch(error, (val) => {
  showError.value = !!val
})
</script>

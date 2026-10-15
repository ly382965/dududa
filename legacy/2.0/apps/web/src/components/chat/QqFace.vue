<script setup lang="ts">
import type { AnimationItem } from 'lottie-web'
import { computed, nextTick, onBeforeUnmount, ref, watch } from 'vue'

import { qqFaceUrl } from '../../services/qq-faces'

const props = withDefaults(
  defineProps<{ faceId: string; large?: boolean; url?: string; name?: string; market?: boolean }>(),
  { large: false, url: '', name: '', market: false },
)
const emit = defineEmits<{ failed: [] }>()
const animationContainer = ref<HTMLElement | null>(null)
const animationState = ref<'loading' | 'ready' | 'failed'>('loading')
const fallbackFailed = ref(false)
const lottieUrl = computed(() => (props.large && !props.market && !props.url ? qqFaceUrl(props.faceId, 'lottie') : ''))
const fallbackUrl = computed(() => props.url || qqFaceUrl(props.faceId, props.large ? 'large' : 'apng'))
const failed = computed(() => fallbackFailed.value && (!lottieUrl.value || animationState.value === 'failed'))
let animation: AnimationItem | null = null
let generation = 0

function stopAnimation(): void {
  generation += 1
  animation?.destroy()
  animation = null
}

function handleFallbackError(): void {
  fallbackFailed.value = true
  emit('failed')
}

async function renderAnimation(): Promise<void> {
  stopAnimation()
  animationState.value = 'loading'
  fallbackFailed.value = false
  if (!props.large || !lottieUrl.value) return
  const expected = generation
  await nextTick()
  if (!animationContainer.value || expected !== generation) return
  try {
    const { default: lottie } = await import('lottie-web/build/player/lottie_light')
    if (!animationContainer.value || expected !== generation) return
    const item = lottie.loadAnimation({
      container: animationContainer.value,
      renderer: 'svg',
      loop: true,
      autoplay: true,
      path: lottieUrl.value,
      rendererSettings: { preserveAspectRatio: 'xMidYMid meet' },
    })
    animation = item
    item.addEventListener('DOMLoaded', () => {
      if (expected === generation) animationState.value = 'ready'
    })
    item.addEventListener('data_failed', () => {
      if (expected === generation) animationState.value = 'failed'
    })
  } catch {
    if (expected === generation) animationState.value = 'failed'
  }
}

watch([() => props.faceId, () => props.large, () => props.url, lottieUrl], () => void renderAnimation(), { immediate: true })
onBeforeUnmount(stopAnimation)
</script>

<template>
  <span v-if="failed" class="qq-face-fallback">表情 {{ faceId }}</span>
  <span v-else class="qq-face" :class="{ large }" role="img" :aria-label="name || `QQ 表情 ${faceId}`">
    <img
      v-if="!fallbackFailed && (!large || !lottieUrl || animationState !== 'ready')"
      :src="fallbackUrl"
      alt=""
      loading="lazy"
      decoding="async"
      @error="handleFallbackError"
    />
    <span
      v-if="large && lottieUrl"
      ref="animationContainer"
      class="qq-face-animation"
      :class="{ visible: animationState === 'ready' }"
      aria-hidden="true"
    />
  </span>
</template>

<style scoped>
.qq-face {
  position: relative;
  display: inline-block;
  width: 22px;
  height: 22px;
  vertical-align: middle;
}

.qq-face.large {
  width: 96px;
  height: 96px;
}

.qq-face img,
.qq-face-animation {
  position: absolute;
  inset: 0;
  width: 100%;
  height: 100%;
  object-fit: contain;
}

.qq-face-animation {
  visibility: hidden;
}

.qq-face-animation.visible {
  visibility: visible;
}

.qq-face-fallback {
  border-radius: 4px;
  color: var(--text-muted);
  background: var(--surface-muted);
  padding: 2px 6px;
  font-size: 10px;
}
</style>

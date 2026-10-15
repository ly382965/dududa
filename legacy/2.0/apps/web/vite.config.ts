import vue from '@vitejs/plugin-vue'
import { defineConfig } from 'vitest/config'

const defaultApiTarget = `http://127.0.0.1:${process.env.DUDUDA_WEB_INTERNAL_PORT || 8000}`
const apiTarget = process.env.DUDUDA_API_TARGET || defaultApiTarget
const internalTestApiTarget = process.env.DUDUDA_INTERNAL_TEST_API_TARGET || apiTarget

export default defineConfig({
  plugins: [vue()],
  server: {
    host: '0.0.0.0',
    port: Number(process.env.VITE_PORT || 5173),
    proxy: {
      '/api/internal-test': {
        target: internalTestApiTarget,
      },
      '/api': {
        target: apiTarget,
      },
    },
  },
  preview: {
    host: '0.0.0.0',
    port: 4173,
  },
  test: {
    environment: 'jsdom',
    include: ['src/**/*.spec.ts'],
  },
})

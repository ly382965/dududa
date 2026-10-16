import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import vuetify from 'vite-plugin-vuetify'
import { viteSingleFile } from 'vite-plugin-singlefile'
import { resolve } from 'path'

export default defineConfig({
  plugins: [
    vue(),
    vuetify({ autoImport: true }),
    viteSingleFile()
  ],
  resolve: {
    alias: {
      '@': resolve(__dirname, 'src')
    }
  },
  base: './',
  build: {
    outDir: resolve(__dirname, '../../../pages/iris'),
    emptyOutDir: true,
    sourcemap: false,
    chunkSizeWarningLimit: 2000
  }
})

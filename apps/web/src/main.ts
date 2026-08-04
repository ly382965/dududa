import { createPinia } from 'pinia'
import { createApp } from 'vue'

import App from './App.vue'
import { loadQqFaceCatalog } from './services/qq-faces'
import './styles.css'

void loadQqFaceCatalog().catch(() => undefined)

createApp(App).use(createPinia()).mount('#app')

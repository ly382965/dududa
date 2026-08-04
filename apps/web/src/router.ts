import { defineComponent, h } from 'vue'
import { createRouter, createWebHashHistory } from 'vue-router'

const RouteMarker = defineComponent({ render: () => h('span', { hidden: true }) })

export const router = createRouter({
  history: createWebHashHistory(),
  routes: [
    { path: '/', redirect: '/chat' },
    { path: '/chat', name: 'chat', component: RouteMarker, meta: { section: 'chat' } },
    {
      path: '/chat/:accountId(qq-\\d+)/:scene(group|private)/:peerId(\\d+)',
      name: 'chat-conversation',
      component: RouteMarker,
      meta: { section: 'chat' },
    },
    { path: '/contacts', name: 'contacts', component: RouteMarker, meta: { section: 'contacts' } },
    { path: '/notifications', name: 'notifications', component: RouteMarker, meta: { section: 'notifications' } },
    { path: '/settings', name: 'settings', component: RouteMarker, meta: { section: 'settings' } },
    { path: '/:pathMatch(.*)*', redirect: '/chat' },
  ],
})

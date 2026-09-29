import { createRouter, createWebHashHistory } from 'vue-router'

export type AppRouteName =
  | 'work'
  | 'plugins'
  | 'logs'
  | 'about'

export const router = createRouter({
  history: createWebHashHistory(),
  routes: [
    { path: '/', redirect: '/work' },
    {
      path: '/work',
      name: 'work',
      component: () => import('../components/ServiceView.vue'),
    },
    {
      path: '/plugins',
      name: 'plugins',
      component: () => import('../components/PluginHomeView.vue'),
    },
    {
      path: '/logs',
      name: 'logs',
      component: () => import('../components/LogView.vue'),
    },
    {
      path: '/about',
      name: 'about',
      component: () => import('../components/AboutRouteView.vue'),
    },
    { path: '/:pathMatch(.*)*', redirect: '/work' },
  ],
})

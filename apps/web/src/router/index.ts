import { createRouter, createWebHashHistory } from 'vue-router'

export type AppRouteName =
  | 'runtime'
  | 'plugins'
  | 'logs'
  | 'about'

export const router = createRouter({
  history: createWebHashHistory(),
  routes: [
    { path: '/', redirect: '/runtime' },
    {
      path: '/runtime',
      name: 'runtime',
      component: () => import('../components/RuntimeView.vue'),
    },
    { path: '/work', redirect: '/runtime' },
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
    { path: '/:pathMatch(.*)*', redirect: '/runtime' },
  ],
})

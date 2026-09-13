import { createRouter, createWebHashHistory } from 'vue-router'

export type AppRouteName =
  | 'work'
  | 'plugins'
  | 'plugins-installed'
  | 'plugins-mcp-detail'
  | 'plugins-skills-manage'
  | 'plugins-mcp-manage'
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
      path: '/plugins/installed',
      name: 'plugins-installed',
      component: () => import('../components/PluginInstalledView.vue'),
    },
    {
      path: '/plugins/mcp/:connectionId',
      name: 'plugins-mcp-detail',
      component: () => import('../components/PluginMCPDetailView.vue'),
    },
    {
      path: '/plugins/skills/manage',
      name: 'plugins-skills-manage',
      component: () => import('../components/SkillManagerView.vue'),
    },
    {
      path: '/plugins/mcp/manage',
      name: 'plugins-mcp-manage',
      component: () => import('../components/MCPConnectionManagerView.vue'),
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

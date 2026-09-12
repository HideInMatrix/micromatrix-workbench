import { createRouter, createWebHashHistory } from 'vue-router'

export type AppRouteName =
  | 'work'
  | 'workbench'
  | 'workbench-workflows'
  | 'workbench-skills'
  | 'workbench-mcp-connections'
  | 'resource-authorizations'
  | 'logs'
  | 'about'

export const router = createRouter({
  history: createWebHashHistory(),
  routes: [
    {
      path: '/',
      redirect: '/work',
    },
    {
      path: '/work',
      name: 'work',
      component: () => import('../components/ServiceView.vue'),
    },
    {
      path: '/workbench',
      name: 'workbench',
      component: () => import('../components/CapabilityWorkbenchView.vue'),
    },
    {
      path: '/workbench/workflows',
      name: 'workbench-workflows',
      component: () => import('../components/WorkflowWorkbenchView.vue'),
    },
    {
      path: '/workbench/skills',
      name: 'workbench-skills',
      component: () => import('../components/SkillManagerView.vue'),
    },
    {
      path: '/workbench/mcp-connections',
      name: 'workbench-mcp-connections',
      component: () => import('../components/MCPConnectionManagerView.vue'),
    },
    {
      path: '/resource-authorizations',
      name: 'resource-authorizations',
      component: () => import('../components/ResourceAuthorizationView.vue'),
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
    {
      path: '/:pathMatch(.*)*',
      redirect: '/work',
    },
  ],
})

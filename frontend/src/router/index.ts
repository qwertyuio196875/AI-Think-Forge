import { createRouter, createWebHistory, type RouteRecordRaw } from 'vue-router'

import WorkbenchLayout from '../layouts/WorkbenchLayout.vue'

const routes: RouteRecordRaw[] = [
  {
    path: '/',
    component: WorkbenchLayout,
    redirect: '/creation',
    children: [
      {
        path: 'creation',
        name: 'creation',
        component: () => import('../views/CreationView.vue'),
        meta: { title: '主题创作' }
      },
      {
        path: 'analysis',
        name: 'analysis',
        component: () => import('../views/AnalysisView.vue'),
        meta: { title: '资料分析' }
      },
      {
        path: 'history',
        name: 'history',
        component: () => import('../views/HistoryView.vue'),
        meta: { title: '任务历史' }
      },
      {
        path: 'settings',
        name: 'settings',
        component: () => import('../views/SettingsView.vue'),
        meta: { title: '设置' }
      }
    ]
  },
  {
    path: '/:pathMatch(.*)*',
    redirect: '/creation'
  }
]

const router = createRouter({
  history: createWebHistory(),
  routes
})

export default router
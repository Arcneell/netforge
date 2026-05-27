import { createRouter, createWebHistory, type RouteRecordRaw } from 'vue-router'
import { useAuthStore } from '@/stores/auth'
import type { UserRole } from '@/api'

// Each protected route declares the minimum role it needs. The global guard:
//   1. Lazily fetches /api/auth/me on first navigation.
//   2. Redirects anonymous users to /login with ?next=<original path>.
//   3. Sends authenticated users without the required role to /403.
declare module 'vue-router' {
  interface RouteMeta {
    requiresAuth?: boolean
    minRole?: UserRole
    titleKey?: string
  }
}

const routes: RouteRecordRaw[] = [
  {
    path: '/login',
    name: 'login',
    component: () => import('@/views/LoginView.vue'),
    meta: { requiresAuth: false, titleKey: 'auth.signIn' },
  },
  {
    path: '/',
    component: () => import('@/components/AppShell.vue'),
    meta: { requiresAuth: true, minRole: 'viewer' },
    children: [
      {
        path: '',
        name: 'dashboard',
        component: () => import('@/views/DashboardView.vue'),
        meta: { titleKey: 'nav.dashboard' },
      },
      {
        path: 'subnets',
        name: 'subnets',
        component: () => import('@/views/SubnetsListView.vue'),
        meta: { titleKey: 'nav.subnets' },
      },
      {
        path: 'subnets/:id',
        name: 'subnet-detail',
        component: () => import('@/views/SubnetDetailView.vue'),
        meta: { titleKey: 'subnet.label' },
      },
      {
        path: 'vlans',
        name: 'vlans',
        component: () => import('@/views/VlansListView.vue'),
        meta: { titleKey: 'nav.vlans' },
      },
      {
        path: 'switches',
        name: 'switches',
        component: () => import('@/views/SwitchesListView.vue'),
        meta: { titleKey: 'nav.switches' },
      },
      {
        path: 'switches/:id',
        name: 'switch-detail',
        component: () => import('@/views/SwitchDetailView.vue'),
        meta: { titleKey: 'switch.label' },
      },
      {
        path: 'devices',
        name: 'devices',
        component: () => import('@/views/DevicesListView.vue'),
        meta: { titleKey: 'nav.devices' },
      },
      {
        path: 'topology',
        name: 'topology',
        component: () => import('@/views/TopologyView.vue'),
        meta: { titleKey: 'nav.topology' },
      },
      {
        path: 'import',
        name: 'import',
        component: () => import('@/views/ImportView.vue'),
        meta: { minRole: 'admin', titleKey: 'nav.import' },
      },
      {
        path: 'audit',
        name: 'audit',
        component: () => import('@/views/AuditView.vue'),
        meta: { minRole: 'admin', titleKey: 'nav.audit' },
      },
      {
        path: 'snapshots/compare',
        name: 'snapshots-compare',
        component: () => import('@/views/SnapshotCompareView.vue'),
        meta: { minRole: 'admin', titleKey: 'nav.snapshots' },
      },
      {
        path: 'insights',
        name: 'insights',
        component: () => import('@/views/InsightsView.vue'),
        meta: { minRole: 'admin', titleKey: 'nav.insights' },
      },
      {
        path: 'ask',
        name: 'ask',
        component: () => import('@/views/AskAiView.vue'),
        meta: { minRole: 'admin', titleKey: 'nav.ask' },
      },
      {
        path: 'drafts',
        name: 'drafts',
        component: () => import('@/views/DraftsView.vue'),
        meta: { minRole: 'admin', titleKey: 'nav.drafts' },
      },
      {
        path: 'settings',
        name: 'settings',
        component: () => import('@/views/SettingsView.vue'),
        meta: { minRole: 'admin', titleKey: 'nav.settings' },
      },
      {
        path: '403',
        name: 'forbidden',
        component: () => import('@/views/ForbiddenView.vue'),
        meta: { titleKey: 'errors.forbiddenTitle' },
      },
      {
        path: ':pathMatch(.*)*',
        name: 'not-found',
        component: () => import('@/views/NotFoundView.vue'),
        meta: { titleKey: 'errors.notFoundTitle' },
      },
    ],
  },
]

export const router = createRouter({
  history: createWebHistory(),
  routes,
  scrollBehavior(_to, _from, saved) {
    return saved || { top: 0 }
  },
})

function roleSatisfies(actual: UserRole | null | undefined, required: UserRole): boolean {
  if (!actual) return false
  if (required === 'viewer') return actual === 'viewer' || actual === 'admin'
  return actual === required
}

router.beforeEach(async (to) => {
  const auth = useAuthStore()

  if (auth.status === 'idle') {
    await auth.fetchMe()
  }

  // Closest matched record that declares requiresAuth wins.
  const requiresAuth = to.matched.some((r) => r.meta.requiresAuth)
  const minRole = [...to.matched].reverse().find((r) => r.meta.minRole)?.meta.minRole

  if (!requiresAuth) {
    return true
  }

  if (!auth.isAuthenticated) {
    return {
      path: '/login',
      query: to.fullPath && to.fullPath !== '/' ? { next: to.fullPath } : undefined,
    }
  }

  if (minRole && !roleSatisfies(auth.role, minRole)) {
    return { path: '/403' }
  }

  return true
})

// Note: document.title is fully owned by App.vue's watch on
// `route.meta.titleKey` + the i18n locale (immediate: true so direct
// navigations are covered too). The previous `afterEach` here unconditionally
// reset the title to the bare app name AFTER App.vue's watch had set the
// real "Section · App" form — every navigation lost the page name from the
// browser tab and history entry. Leave the title to the single source of
// truth in App.vue.

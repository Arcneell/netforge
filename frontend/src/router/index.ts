import { createRouter, createWebHistory, type RouteRecordRaw } from 'vue-router'
import { useAuthStore } from '@/stores/auth'
import type { UserRole } from '@/api'
import { roleSatisfies } from '@/utils/roles'

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
      // Declared BEFORE `subnets/:id` — otherwise the detail route matches
      // `/subnets/new` first and tries to load a subnet with id "new".
      {
        path: 'subnets/new',
        name: 'subnet-new',
        component: () => import('@/views/forms/SubnetFormView.vue'),
        meta: { minRole: 'admin', titleKey: 'subnet.new' },
      },
      {
        path: 'subnets/:id',
        name: 'subnet-detail',
        component: () => import('@/views/SubnetDetailView.vue'),
        meta: { titleKey: 'subnet.label' },
      },
      {
        path: 'subnets/:id/edit',
        name: 'subnet-edit',
        component: () => import('@/views/forms/SubnetFormView.vue'),
        meta: { minRole: 'admin', titleKey: 'subnet.edit' },
      },
      // An IP is created inside a subnet, so the parent is part of the path.
      // The optional `?address=` query pre-fills the form (clicking a free
      // cell in the grid, or accepting the "next free" suggestion).
      {
        path: 'subnets/:subnetId/ips/new',
        name: 'ip-new',
        component: () => import('@/views/forms/IpFormView.vue'),
        meta: { minRole: 'admin', titleKey: 'ip.new' },
      },
      {
        path: 'ips/:id/edit',
        name: 'ip-edit',
        component: () => import('@/views/forms/IpFormView.vue'),
        meta: { minRole: 'admin', titleKey: 'ip.edit' },
      },
      {
        path: 'vlans',
        name: 'vlans',
        component: () => import('@/views/VlansListView.vue'),
        meta: { titleKey: 'nav.vlans' },
      },
      // Create and edit are full pages, not modals — see components/FormPage.vue.
      {
        path: 'vlans/new',
        name: 'vlan-new',
        component: () => import('@/views/forms/VlanFormView.vue'),
        meta: { minRole: 'admin', titleKey: 'vlan.new' },
      },
      {
        path: 'vlans/:id/edit',
        name: 'vlan-edit',
        component: () => import('@/views/forms/VlanFormView.vue'),
        meta: { minRole: 'admin', titleKey: 'vlan.edit' },
      },
      {
        path: 'switches',
        name: 'switches',
        component: () => import('@/views/SwitchesListView.vue'),
        meta: { titleKey: 'nav.switches' },
      },
      // `switches/new` must stay ABOVE `switches/:id`, otherwise the detail
      // route matches first and swallows the literal segment.
      {
        path: 'switches/new',
        name: 'switch-new',
        component: () => import('@/views/forms/SwitchFormView.vue'),
        meta: { minRole: 'admin', titleKey: 'switch.new' },
      },
      {
        path: 'switches/:id',
        name: 'switch-detail',
        component: () => import('@/views/SwitchDetailView.vue'),
        meta: { titleKey: 'switch.label' },
      },
      {
        path: 'switches/:id/edit',
        name: 'switch-edit',
        component: () => import('@/views/forms/SwitchFormView.vue'),
        meta: { minRole: 'admin', titleKey: 'switch.edit' },
      },
      // A port only exists inside a switch, so its route is nested under one.
      {
        path: 'switches/:switchId/ports/:id/edit',
        name: 'port-edit',
        component: () => import('@/views/forms/PortFormView.vue'),
        meta: { minRole: 'admin', titleKey: 'port.edit' },
      },
      {
        path: 'devices',
        name: 'devices',
        component: () => import('@/views/DevicesListView.vue'),
        meta: { titleKey: 'nav.devices' },
      },
      {
        path: 'devices/new',
        name: 'device-new',
        component: () => import('@/views/forms/DeviceFormView.vue'),
        meta: { minRole: 'admin', titleKey: 'device.new' },
      },
      {
        path: 'devices/:id/edit',
        name: 'device-edit',
        component: () => import('@/views/forms/DeviceFormView.vue'),
        meta: { minRole: 'admin', titleKey: 'device.edit' },
      },
      {
        path: 'topology',
        name: 'topology',
        // The graph view is paused pending a redesign. `TopologyView.vue`
        // stays on disk and comes back once the new one is ready.
        component: () => import('@/views/TopologyWipView.vue'),
        meta: { titleKey: 'nav.topology' },
      },
      // The AI surfaces and the data-management surfaces used to be six
      // separate sidebar entries. They are grouped into two workspaces, each
      // with its own tab bar — same pages, a third of the top-level choices.
      {
        path: 'assistant',
        component: () => import('@/views/AssistantWorkspace.vue'),
        meta: { minRole: 'admin', titleKey: 'nav.assistant' },
        children: [
          { path: '', redirect: { name: 'insights' } },
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
        ],
      },
      {
        path: 'data',
        component: () => import('@/views/DataWorkspace.vue'),
        meta: { minRole: 'admin', titleKey: 'nav.data' },
        children: [
          { path: '', redirect: { name: 'import' } },
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
            path: 'snapshots',
            name: 'snapshots-compare',
            component: () => import('@/views/SnapshotCompareView.vue'),
            meta: { minRole: 'admin', titleKey: 'nav.snapshots' },
          },
        ],
      },
      // Bookmarks and any link still pointing at the pre-grouping paths.
      { path: 'insights', redirect: { name: 'insights' } },
      { path: 'ask', redirect: { name: 'ask' } },
      { path: 'drafts', redirect: { name: 'drafts' } },
      { path: 'import', redirect: { name: 'import' } },
      { path: 'audit', redirect: { name: 'audit' } },
      { path: 'snapshots/compare', redirect: { name: 'snapshots-compare' } },
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

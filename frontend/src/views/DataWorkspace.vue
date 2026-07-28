<script setup lang="ts">
import { computed } from 'vue'
import { RouterView } from 'vue-router'
import { useI18n } from 'vue-i18n'
import WorkspaceTabs, { type WorkspaceTab } from '@/components/WorkspaceTabs.vue'

/**
 * Groups everything that moves data in or explains how it changed: bulk
 * import, the audit trail, and the point-in-time comparison. Three former
 * sidebar entries that are only ever used by the same person for the same
 * reason.
 */
const { t } = useI18n()

const tabs = computed<WorkspaceTab[]>(() => [
  { to: '/data/import', label: t('nav.import') },
  { to: '/data/audit', label: t('nav.audit') },
  { to: '/data/snapshots', label: t('nav.snapshots') },
])
</script>

<template>
  <div>
    <WorkspaceTabs :tabs="tabs" />
    <RouterView />
  </div>
</template>

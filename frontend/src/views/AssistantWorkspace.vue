<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { RouterView } from 'vue-router'
import { useI18n } from 'vue-i18n'
import WorkspaceTabs, { type WorkspaceTab } from '@/components/WorkspaceTabs.vue'
import { aiApi, type AIStatus } from '@/api'

/**
 * Groups the three AI surfaces — advice, questions, drafted actions — that
 * used to sit as three separate sidebar entries. They operate on the same
 * inventory and are used in sequence, so they belong in one place.
 */
const { t } = useI18n()

// "Drafted actions" only exists when the operator has opted into NL-to-action.
// Falls back to hiding the tab if the status call fails, matching how the
// sidebar has always gated it.
const aiStatus = ref<AIStatus | null>(null)
onMounted(async () => {
  try {
    aiStatus.value = await aiApi.status()
  } catch {
    aiStatus.value = null
  }
})

const tabs = computed<WorkspaceTab[]>(() => {
  const out: WorkspaceTab[] = [
    { to: '/assistant/insights', label: t('nav.insights') },
    { to: '/assistant/ask', label: t('nav.ask') },
  ]
  if (aiStatus.value?.drafts_enabled) {
    out.push({ to: '/assistant/drafts', label: t('nav.drafts') })
  }
  return out
})
</script>

<template>
  <div>
    <WorkspaceTabs :tabs="tabs" />
    <RouterView />
  </div>
</template>

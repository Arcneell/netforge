<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { Languages } from 'lucide-vue-next'
import { useUiStore } from '@/stores/ui'
import { SUPPORTED_LOCALES, type Locale } from '@/i18n'

const { locale } = useI18n()
const ui = useUiStore()

const current = computed(() => locale.value as Locale)

function next() {
  const i = SUPPORTED_LOCALES.indexOf(current.value)
  const n = SUPPORTED_LOCALES[(i + 1) % SUPPORTED_LOCALES.length]
  ui.changeLocale(n)
}
</script>

<template>
  <button
    type="button"
    :aria-label="$t('locale.label')"
    :title="$t('locale.label')"
    class="inline-flex items-center gap-2 px-2.5 h-8 rounded-md border border-border bg-surface text-sm text-fg-muted hover:text-fg hover:bg-surface-hover transition"
    @click="next"
  >
    <Languages class="w-4 h-4" aria-hidden="true" />
    <span class="font-medium uppercase tracking-wide text-xs">{{ current }}</span>
  </button>
</template>

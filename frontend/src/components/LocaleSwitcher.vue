<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { Languages } from '@lucide/vue'
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
    class="inline-flex items-center gap-1.5 px-2 h-8 rounded-md text-fg-muted hover:text-fg hover:bg-surface-hover transition-colors duration-150 ease-soft"
    @click="next"
  >
    <Languages class="w-4 h-4" :stroke-width="1.9" aria-hidden="true" />
    <span class="text-xs font-medium uppercase">{{ current }}</span>
  </button>
</template>

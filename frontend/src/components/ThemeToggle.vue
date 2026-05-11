<script setup lang="ts">
import { Sun, Moon, Monitor } from 'lucide-vue-next'
import { useUiStore } from '@/stores/ui'
import { storeToRefs } from 'pinia'

const ui = useUiStore()
const { theme } = storeToRefs(ui)

const options = [
  { value: 'light' as const, icon: Sun, key: 'theme.light' },
  { value: 'dark' as const, icon: Moon, key: 'theme.dark' },
  { value: 'system' as const, icon: Monitor, key: 'theme.system' },
]
</script>

<template>
  <div
    class="inline-flex items-center gap-0.5 p-0.5 rounded-md border border-border bg-surface"
    role="group"
    :aria-label="$t('theme.label')"
  >
    <button
      v-for="opt in options"
      :key="opt.value"
      type="button"
      :aria-pressed="theme === opt.value"
      :aria-label="$t(opt.key)"
      :title="$t(opt.key)"
      :class="[
        'flex items-center justify-center w-7 h-7 rounded transition',
        theme === opt.value
          ? 'bg-primary-100 text-primary-700 dark:bg-primary-100/30 dark:text-primary-50'
          : 'text-fg-muted hover:bg-surface-hover hover:text-fg',
      ]"
      @click="ui.setTheme(opt.value)"
    >
      <component :is="opt.icon" class="w-4 h-4" aria-hidden="true" />
    </button>
  </div>
</template>

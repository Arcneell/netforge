<script setup lang="ts">
import { Sun, Moon, Monitor } from '@lucide/vue'
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
  <div class="nf-segmented" role="group" :aria-label="$t('theme.label')">
    <button
      v-for="opt in options"
      :key="opt.value"
      type="button"
      :aria-pressed="theme === opt.value"
      :aria-label="$t(opt.key)"
      :title="$t(opt.key)"
      :class="[
        'nf-segmented-item w-7 justify-center px-0',
        theme === opt.value ? 'nf-segmented-item-active' : '',
      ]"
      @click="ui.setTheme(opt.value)"
    >
      <component :is="opt.icon" class="w-4 h-4" :stroke-width="1.9" aria-hidden="true" />
    </button>
  </div>
</template>

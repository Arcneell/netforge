<script setup lang="ts">
import { useI18n } from 'vue-i18n'
import Modal from '@/components/ui/Modal.vue'
import { SHORTCUTS } from '@/composables/useShortcuts'

defineProps<{ open: boolean }>()
defineEmits<{ (e: 'close'): void }>()
const { t } = useI18n()
</script>

<template>
  <Modal :open="open" :title="t('shortcuts.title')" size="md" @close="$emit('close')">
    <p class="text-base text-fg-muted mb-4">{{ t('shortcuts.subtitle') }}</p>
    <ul class="-mx-2">
      <li
        v-for="s in SHORTCUTS"
        :key="s.display"
        class="flex items-center justify-between gap-4 py-2 px-2 rounded-md hover:bg-surface-hover transition-colors duration-150 ease-soft"
      >
        <span class="text-base text-fg">{{ t(s.descriptionKey) }}</span>
        <span class="flex items-center gap-1 flex-shrink-0">
          <template v-for="(part, i) in s.display.split(' ')" :key="i">
            <span v-if="part === '/'" class="text-xs text-fg-subtle">/</span>
            <kbd
              v-else
              class="text-2xs font-medium px-1.5 py-1 rounded bg-muted text-fg-muted whitespace-nowrap"
            >
              {{ part }}
            </kbd>
          </template>
        </span>
      </li>
    </ul>
  </Modal>
</template>

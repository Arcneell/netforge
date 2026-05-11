<script setup lang="ts">
import { useI18n } from 'vue-i18n'
import Modal from '@/components/ui/Modal.vue'
import Button from '@/components/ui/Button.vue'

withDefaults(
  defineProps<{
    open: boolean
    title: string
    message?: string
    confirmLabel?: string
    cancelLabel?: string
    variant?: 'primary' | 'danger'
    loading?: boolean
  }>(),
  { variant: 'primary', loading: false },
)

const emit = defineEmits<{
  (e: 'confirm'): void
  (e: 'cancel'): void
}>()

const { t } = useI18n()
</script>

<template>
  <Modal :open="open" :title="title" size="sm" @close="emit('cancel')">
    <p v-if="message" class="text-sm text-fg-muted whitespace-pre-line">{{ message }}</p>
    <slot />
    <template #footer>
      <div class="flex justify-end gap-2">
        <Button variant="secondary" :disabled="loading" @click="emit('cancel')">
          {{ cancelLabel ?? t('common.cancel') }}
        </Button>
        <Button :variant="variant" :loading="loading" @click="emit('confirm')">
          {{ confirmLabel ?? t('common.confirm') }}
        </Button>
      </div>
    </template>
  </Modal>
</template>

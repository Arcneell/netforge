<script setup lang="ts">
import { ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { Upload, FileText, X } from 'lucide-vue-next'
import Button from '@/components/ui/Button.vue'
import { formatBytes } from '@/utils/formatters'

const props = defineProps<{
  modelValue: File | null
  /** Set by the parent to reject files that aren't .csv (or csv-like MIME). */
  accept?: string
  /** UI lock during an in-flight upload. */
  disabled?: boolean
}>()

const emit = defineEmits<{
  (e: 'update:modelValue', file: File | null): void
  (e: 'reject', reason: 'notCsv' | 'tooLarge'): void
}>()

const { t } = useI18n()
const inputRef = ref<HTMLInputElement | null>(null)
const dragOver = ref(false)

// 10 MiB — must stay in sync with backend `_MAX_BYTES` in routers/imports.py.
const MAX_BYTES = 10 * 1024 * 1024

function pickOne(files: FileList | null) {
  if (!files || files.length === 0) return
  const f = files[0]
  if (!/\.csv$/i.test(f.name)) {
    emit('reject', 'notCsv')
    return
  }
  if (f.size > MAX_BYTES) {
    emit('reject', 'tooLarge')
    return
  }
  emit('update:modelValue', f)
}

function onClickPicker() {
  if (props.disabled) return
  inputRef.value?.click()
}

function onKeyActivate(ev: KeyboardEvent) {
  if (props.disabled) return
  if (ev.key === 'Enter' || ev.key === ' ') {
    ev.preventDefault()
    inputRef.value?.click()
  }
}

function onDrop(ev: DragEvent) {
  ev.preventDefault()
  dragOver.value = false
  if (props.disabled) return
  pickOne(ev.dataTransfer?.files ?? null)
}

function onChange(ev: Event) {
  pickOne((ev.target as HTMLInputElement).files)
  // Reset the input so picking the same file again still fires `change`.
  if (inputRef.value) inputRef.value.value = ''
}

function clear() {
  emit('update:modelValue', null)
}
</script>

<template>
  <div>
    <div
      v-if="!modelValue"
      role="button"
      tabindex="0"
      :aria-disabled="disabled"
      class="flex flex-col items-center justify-center gap-2 px-4 py-10 border-2 border-dashed rounded-md text-center transition cursor-pointer focus:outline-none focus-visible:ring-2 focus-visible:ring-primary-500/60 focus-visible:ring-offset-2 focus-visible:ring-offset-bg"
      :class="[
        dragOver
          ? 'border-primary-500 bg-primary-50/60 dark:bg-primary-900/20'
          : 'border-border hover:border-primary-400 hover:bg-surface-hover',
        disabled ? 'opacity-50 pointer-events-none' : '',
      ]"
      @click="onClickPicker"
      @keydown="onKeyActivate"
      @dragenter.prevent="dragOver = true"
      @dragover.prevent="dragOver = true"
      @dragleave.prevent="dragOver = false"
      @drop="onDrop"
    >
      <Upload class="w-7 h-7 text-fg-muted" aria-hidden="true" />
      <p class="text-sm text-fg">{{ t('import.filePrompt') }}</p>
      <input
        ref="inputRef"
        type="file"
        class="sr-only"
        :accept="accept ?? '.csv,text/csv'"
        @change="onChange"
      />
    </div>

    <div
      v-else
      class="flex items-center gap-3 px-3 py-2.5 border border-border rounded-md bg-surface"
    >
      <FileText
        class="w-5 h-5 text-primary-600 dark:text-primary-400 flex-shrink-0"
        aria-hidden="true"
      />
      <div class="min-w-0 flex-1">
        <p class="text-sm text-fg truncate font-medium">{{ modelValue.name }}</p>
        <p class="text-xs text-fg-muted font-mono">{{ formatBytes(modelValue.size) }}</p>
      </div>
      <Button
        variant="ghost"
        size="sm"
        :aria-label="t('import.fileReset')"
        :disabled="disabled"
        @click="clear"
      >
        <X class="w-4 h-4" aria-hidden="true" />
      </Button>
    </div>
  </div>
</template>

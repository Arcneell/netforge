<script setup lang="ts">
import { ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { UploadCloud, FileSpreadsheet, X } from '@lucide/vue'
import Button from '@/components/ui/Button.vue'
import Badge from '@/components/ui/Badge.vue'
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
    <!-- The <input> lives outside both branches so the "change file" button in
         the selected state can re-open the picker without re-mounting it. -->
    <input
      ref="inputRef"
      type="file"
      class="sr-only"
      :accept="accept ?? '.csv,text/csv'"
      @change="onChange"
    />

    <!-- Empty state: an unmistakable drop target. Dashed hairline, a tinted
         glyph tile, and one line telling the operator what lands here. -->
    <div
      v-if="!modelValue"
      role="button"
      tabindex="0"
      :aria-disabled="disabled"
      class="flex flex-col items-center justify-center gap-3 px-6 py-10 rounded-lg border-2 border-dashed text-center cursor-pointer focus:outline-none focus-visible:shadow-ring transition-colors duration-150 ease-soft"
      :class="[
        dragOver
          ? 'border-primary-500 bg-primary-500/10'
          : 'border-border-strong bg-muted/40 hover:border-primary-400 hover:bg-surface-hover',
        disabled ? 'opacity-50 pointer-events-none' : '',
      ]"
      @click="onClickPicker"
      @keydown="onKeyActivate"
      @dragenter.prevent="dragOver = true"
      @dragover.prevent="dragOver = true"
      @dragleave.prevent="dragOver = false"
      @drop="onDrop"
    >
      <span
        class="inline-flex items-center justify-center w-11 h-11 rounded-lg border bg-surface transition-colors duration-150 ease-soft"
        :class="
          dragOver
            ? 'border-primary-500 text-primary-600 dark:text-primary-400'
            : 'border-border text-fg-muted'
        "
      >
        <UploadCloud class="w-5 h-5" :stroke-width="1.75" aria-hidden="true" />
      </span>
      <div class="space-y-1">
        <p class="text-base font-medium text-fg">
          {{ dragOver ? t('import.fileDropNow') : t('import.filePrompt') }}
        </p>
        <p class="text-xs text-fg-muted">{{ t('import.fileHint') }}</p>
      </div>
      <span class="nf-link text-sm font-medium">{{ t('import.fileBrowse') }}</span>
    </div>

    <!-- Selected state: the file, its weight, and two ways out of it. -->
    <div v-else class="flex items-center gap-3 p-3 rounded-lg border border-border bg-surface">
      <span
        class="inline-flex items-center justify-center w-9 h-9 rounded-md bg-primary-500/10 text-primary-600 dark:text-primary-400 flex-shrink-0"
      >
        <FileSpreadsheet class="w-[18px] h-[18px]" aria-hidden="true" />
      </span>
      <div class="min-w-0 flex-1">
        <p class="text-base font-medium text-fg truncate">{{ modelValue.name }}</p>
        <p class="text-xs text-fg-muted font-mono tabular-nums">
          {{ formatBytes(modelValue.size) }}
        </p>
      </div>
      <Badge tone="success">{{ t('import.fileReady') }}</Badge>
      <Button variant="secondary" size="sm" :disabled="disabled" @click="onClickPicker">
        {{ t('import.fileReset') }}
      </Button>
      <Button
        variant="ghost"
        size="sm"
        :aria-label="t('common.remove')"
        :disabled="disabled"
        @click="clear"
      >
        <X class="w-4 h-4" aria-hidden="true" />
      </Button>
    </div>
  </div>
</template>

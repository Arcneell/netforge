<script setup lang="ts">
import { ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { UploadCloud, Upload, Info, X, FileText, Archive, HelpCircle } from '@lucide/vue'
import Button from '@/components/ui/Button.vue'
import Badge from '@/components/ui/Badge.vue'
import HelpTooltip from '@/components/ui/HelpTooltip.vue'
import { BULK_MAX_TOTAL_BYTES, type BulkSlot } from '@/composables/useBulkCsvImport'
import { useImportEntityLabels } from '@/composables/useImportEntityLabels'
import { formatBytes } from '@/utils/formatters'

/**
 * Bulk mode: the dropzone, the picked-file list with its per-file detection
 * badges, the dry-run switch and the run controls — plus the help card that
 * explains what the batch does. State lives in `useBulkCsvImport`.
 */
defineProps<{
  files: BulkSlot[]
  submitting: boolean
  totalBytes: number
  overLimit: boolean
  canSubmit: boolean
}>()

const emit = defineEmits<{
  (e: 'add-files', files: FileList | File[]): void
  (e: 'remove', index: number): void
  (e: 'clear'): void
  (e: 'submit'): void
}>()

const dryRun = defineModel<boolean>('dryRun', { required: true })

const { t } = useI18n()
const { entityLabelOrFallback } = useImportEntityLabels()

const dragOver = ref(false)
const inputRef = ref<HTMLInputElement | null>(null)

function onPickerClick() {
  inputRef.value?.click()
}

function onInputChange(ev: Event) {
  const target = ev.target as HTMLInputElement
  if (target.files) emit('add-files', target.files)
  // Reset so the same file can be picked again.
  if (inputRef.value) inputRef.value.value = ''
}

function onDrop(ev: DragEvent) {
  ev.preventDefault()
  dragOver.value = false
  if (ev.dataTransfer?.files) emit('add-files', ev.dataTransfer.files)
}
</script>

<template>
  <div class="grid grid-cols-1 lg:grid-cols-[1fr_340px] gap-6 mb-6">
    <section class="nf-card p-4 sm:p-5 space-y-5">
      <div>
        <h2 class="nf-section-title">{{ t('import.bulk.title') }}</h2>
        <p class="text-sm text-fg-muted mt-0.5">{{ t('import.bulk.subtitle') }}</p>
      </div>

      <!-- Dropzone -->
      <div
        role="button"
        tabindex="0"
        :aria-disabled="submitting"
        class="flex flex-col items-center justify-center gap-3 px-6 py-10 rounded-lg border-2 border-dashed text-center cursor-pointer focus:outline-none focus-visible:shadow-ring transition-colors duration-150 ease-soft"
        :class="[
          dragOver
            ? 'border-primary-500 bg-primary-500/10'
            : 'border-border-strong bg-muted/40 hover:border-primary-400 hover:bg-surface-hover',
          submitting ? 'opacity-50 pointer-events-none' : '',
        ]"
        @click="onPickerClick"
        @keydown.enter.prevent="onPickerClick"
        @keydown.space.prevent="onPickerClick"
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
            {{ dragOver ? t('import.fileDropNow') : t('import.bulk.dropPrompt') }}
          </p>
          <p class="text-xs text-fg-muted">{{ t('import.bulk.dropHint') }}</p>
        </div>
        <span class="nf-link text-sm font-medium">{{ t('import.fileBrowse') }}</span>
        <input
          ref="inputRef"
          type="file"
          class="sr-only"
          accept=".csv,.zip,text/csv,application/zip"
          multiple
          @change="onInputChange"
        />
      </div>

      <!-- File list with detection results -->
      <div v-if="files.length > 0">
        <div class="flex items-center justify-between gap-3 mb-2">
          <p class="nf-label">{{ t('import.bulk.filesTitle') }}</p>
          <p class="text-xs tabular-nums" :class="overLimit ? 'text-danger' : 'text-fg-muted'">
            {{
              t('import.bulk.totalSize', {
                size: formatBytes(totalBytes),
                files: files.length,
              })
            }}
            <span v-if="overLimit">
              · {{ t('import.bulk.totalOverLimit', { max: formatBytes(BULK_MAX_TOTAL_BYTES) }) }}
            </span>
          </p>
        </div>
        <ul class="rounded-lg border border-border overflow-hidden divide-y divide-border">
          <li
            v-for="(slot, i) in files"
            :key="i"
            class="flex items-center gap-3 px-3 py-2.5 bg-surface transition-colors duration-150 ease-soft hover:bg-surface-hover"
          >
            <span
              class="inline-flex items-center justify-center w-8 h-8 rounded-md bg-primary-500/10 text-primary-600 dark:text-primary-400 flex-shrink-0"
            >
              <Archive
                v-if="slot.file.name.toLowerCase().endsWith('.zip')"
                class="w-4 h-4"
                aria-hidden="true"
              />
              <FileText v-else class="w-4 h-4" aria-hidden="true" />
            </span>
            <div class="min-w-0 flex-1">
              <p class="text-base text-fg truncate font-medium">{{ slot.file.name }}</p>
              <p class="text-xs text-fg-muted font-mono tabular-nums">
                {{ formatBytes(slot.file.size) }}
              </p>
            </div>

            <!-- Detection badge -->
            <span v-if="slot.detecting" class="text-xs text-fg-muted">
              {{ t('import.bulk.detected.detecting') }}
            </span>
            <Badge
              v-else-if="slot.file.name.toLowerCase().endsWith('.zip')"
              tone="primary"
              size="sm"
            >
              {{ t('import.bulk.detected.zip') }}
            </Badge>
            <Badge v-else-if="slot.detection?.entity" tone="success" size="sm">
              → {{ entityLabelOrFallback(slot.detection.entity) }}
            </Badge>
            <Badge
              v-else-if="slot.detection && slot.detection.entity === null"
              tone="danger"
              size="sm"
            >
              <HelpCircle class="w-3 h-3" aria-hidden="true" />
              {{ t('import.bulk.detected.unknown') }}
            </Badge>
            <Badge v-else-if="slot.detectError" tone="danger" size="sm">
              {{ t('import.bulk.detected.error') }}
            </Badge>

            <Button
              variant="ghost"
              size="sm"
              :disabled="submitting"
              :aria-label="t('import.bulk.removeFile')"
              @click="emit('remove', i)"
            >
              <X class="w-4 h-4" aria-hidden="true" />
            </Button>
          </li>
        </ul>
      </div>

      <!-- HelpTooltip lives OUTSIDE the <label> so clicking `?` doesn't also
           toggle the checkbox via the label's default activation behaviour
           (which would silently flip a validation-only run into a write
           run, or vice versa). Codex P1 on #71. -->
      <div class="flex items-start gap-3 p-3 rounded-lg border border-border bg-muted/40">
        <label class="flex items-start gap-2.5 cursor-pointer flex-1">
          <input
            v-model="dryRun"
            type="checkbox"
            class="mt-0.5 h-4 w-4 rounded border-border-strong accent-primary-600"
          />
          <span>
            <span class="block text-base text-fg font-medium">{{ t('import.dryRun') }}</span>
            <span class="block text-xs text-fg-muted mt-0.5">
              {{ t('import.bulk.dryRunHint') }}
            </span>
          </span>
        </label>
        <HelpTooltip :text="t('import.helpDryRun')" class="mt-0.5" />
      </div>

      <div class="flex flex-wrap items-center gap-2 pt-1">
        <Button
          variant="primary"
          :loading="submitting"
          :disabled="!canSubmit"
          @click="emit('submit')"
        >
          <Upload class="w-4 h-4" aria-hidden="true" />
          {{ dryRun ? t('import.bulk.submitDryRun') : t('import.bulk.submit') }}
        </Button>
        <Button
          v-if="files.length > 0"
          variant="secondary"
          :disabled="submitting"
          @click="emit('clear')"
        >
          {{ t('import.bulk.clearAll') }}
        </Button>
      </div>
    </section>

    <!-- Help -->
    <aside class="nf-card p-4 sm:p-5 h-fit">
      <h2 class="nf-section-title flex items-center gap-2">
        <Info class="w-4 h-4 text-primary-600 dark:text-primary-400" aria-hidden="true" />
        {{ t('import.bulk.helpTitle') }}
      </h2>
      <ul class="mt-3 space-y-2 text-sm text-fg-muted">
        <li
          v-for="key in ['helpDetect', 'helpOrder', 'helpTransaction', 'helpZip']"
          :key="key"
          class="flex items-start gap-2"
        >
          <span class="mt-1.5 w-1 h-1 rounded-full bg-fg-subtle flex-shrink-0" aria-hidden="true" />
          <span>{{ t(`import.bulk.${key}`) }}</span>
        </li>
      </ul>
    </aside>
  </div>
</template>

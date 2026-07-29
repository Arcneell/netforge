<script setup lang="ts">
import { useI18n } from 'vue-i18n'
import { Download, Upload, Info } from 'lucide-vue-next'
import Button from '@/components/ui/Button.vue'
import Select from '@/components/ui/Select.vue'
import HelpTooltip from '@/components/ui/HelpTooltip.vue'
import CsvDropzone from '@/components/CsvDropzone.vue'
import type { ImportEntity } from '@/api'
import { ORDERED_IMPORT_ENTITIES, useImportEntityLabels } from '@/composables/useImportEntityLabels'
import { useToast } from '@/composables/useToast'

/**
 * Single-file mode (legacy flow): one entity, one CSV, plus the sidebar that
 * spells out the recommended import order.
 */
defineProps<{
  submitting: boolean
}>()

const emit = defineEmits<{ (e: 'submit'): void }>()

const entity = defineModel<ImportEntity>('entity', { required: true })
const file = defineModel<File | null>('file', { required: true })
const dryRun = defineModel<boolean>('dryRun', { required: true })

const { t } = useI18n()
const { error: toastError } = useToast()
const { entityOptions, entityLabel } = useImportEntityLabels()

function onReject(reason: 'notCsv' | 'tooLarge') {
  toastError(t(`import.errors.${reason}`))
}

function downloadTemplate() {
  window.open(`/api/exports/${entity.value}`, '_blank', 'noopener')
}
</script>

<template>
  <div class="grid grid-cols-1 lg:grid-cols-[1fr_340px] gap-6 mb-6">
    <section class="nf-card p-4 sm:p-5 space-y-5">
      <div>
        <div class="nf-label mb-1.5 flex items-center gap-1.5">
          <label for="import-entity">{{ t('import.entity') }}</label>
          <HelpTooltip :text="t('import.helpEntity')" />
        </div>
        <Select
          id="import-entity"
          :model-value="entity"
          :options="entityOptions"
          @update:model-value="(v) => (entity = v as ImportEntity)"
        />
        <p class="text-xs text-fg-muted mt-1.5">{{ t('import.entityHint') }}</p>
      </div>

      <div>
        <p class="nf-label mb-1.5">{{ t('import.file') }}</p>
        <CsvDropzone
          :model-value="file"
          :disabled="submitting"
          @update:model-value="(f) => (file = f)"
          @reject="onReject"
        />
      </div>

      <div class="flex items-start gap-3 p-3 rounded-lg border border-border bg-muted/40">
        <label class="flex items-start gap-2.5 cursor-pointer flex-1">
          <input
            v-model="dryRun"
            type="checkbox"
            class="mt-0.5 h-4 w-4 rounded border-border-strong accent-primary-600"
          />
          <span>
            <span class="block text-base text-fg font-medium">{{ t('import.dryRun') }}</span>
            <span class="block text-xs text-fg-muted mt-0.5">{{ t('import.dryRunHint') }}</span>
          </span>
        </label>
        <HelpTooltip :text="t('import.helpDryRun')" class="mt-0.5" />
      </div>

      <div class="pt-1 space-y-2">
        <div class="flex flex-wrap items-center gap-2">
          <Button variant="primary" :loading="submitting" :disabled="!file" @click="emit('submit')">
            <Upload class="w-4 h-4" aria-hidden="true" />
            {{ dryRun ? t('import.submitDryRun') : t('import.submit') }}
          </Button>
          <div class="inline-flex items-center gap-1">
            <Button variant="secondary" :disabled="submitting" @click="downloadTemplate">
              <Download class="w-4 h-4" aria-hidden="true" />
              {{ t('import.exportTemplate') }}
            </Button>
            <HelpTooltip :text="t('import.helpExportTemplate')" />
          </div>
        </div>
        <p class="text-xs text-fg-muted">{{ t('import.exportTemplateHint') }}</p>
      </div>
    </section>

    <aside class="nf-card p-4 sm:p-5 h-fit">
      <h2 class="nf-section-title flex items-center gap-2">
        <Info class="w-4 h-4 text-primary-600 dark:text-primary-400" aria-hidden="true" />
        {{ t('import.orderTitle') }}
      </h2>
      <p class="text-xs text-fg-muted mt-1.5 mb-3">{{ t('import.orderHint') }}</p>
      <ol class="space-y-0.5">
        <li v-for="(e, i) in ORDERED_IMPORT_ENTITIES" :key="e">
          <button
            type="button"
            class="w-full flex items-center gap-2.5 px-2 py-1.5 rounded-md text-left transition-colors duration-150 ease-soft"
            :class="
              entity === e
                ? 'bg-primary-500/10 text-primary-700 dark:text-primary-300'
                : 'text-fg hover:bg-surface-hover'
            "
            :aria-pressed="entity === e"
            @click="entity = e"
          >
            <span class="font-mono text-xs text-fg-subtle w-5 text-right tabular-nums">
              {{ i + 1 }}.
            </span>
            <span class="text-base font-medium">{{ entityLabel(e) }}</span>
          </button>
        </li>
      </ol>
    </aside>
  </div>
</template>

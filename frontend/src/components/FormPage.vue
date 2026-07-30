<script setup lang="ts">
import { useI18n } from 'vue-i18n'
import { AlertTriangle } from '@lucide/vue'
import Breadcrumb, { type BreadcrumbItem } from '@/components/Breadcrumb.vue'
import PageHeader from '@/components/PageHeader.vue'
import Button from '@/components/ui/Button.vue'

/**
 * Full-page create / edit shell.
 *
 * Creating and editing used to happen in modals, which squeezed long forms
 * into a small scrolling box. Every entity now gets its own route and the
 * whole viewport, in the register of Portainer or GLPI: breadcrumb, page
 * title, the form as titled panels laid out across the full width, and an
 * action bar pinned to the bottom of the viewport.
 *
 * The page uses the same 1400px measure as the list views, and fields inside
 * a `<FormSection>` flow into up to three columns — so a form only scrolls
 * when it genuinely has more content than one screen, not because the layout
 * squeezed it into a single narrow lane.
 *
 * Pass a `#aside` slot for context that belongs beside the form rather than
 * inside it (what the record is used for, what saving will affect). With an
 * aside the page splits into a form column and a sticky side column.
 */
withDefaults(
  defineProps<{
    title: string
    subtitle?: string
    breadcrumb: BreadcrumbItem[]
    /** Server-side failure, rendered just above the action bar. */
    error?: string | null
    saving?: boolean
    /** Label for the primary action — defaults to "Save". */
    submitLabel?: string
  }>(),
  { subtitle: undefined, error: null, saving: false, submitLabel: undefined },
)

const emit = defineEmits<{ (e: 'submit'): void; (e: 'cancel'): void }>()

const { t } = useI18n()
</script>

<template>
  <div class="px-4 py-8 sm:px-8 max-w-[1400px] mx-auto nf-stagger">
    <Breadcrumb :items="breadcrumb" />
    <PageHeader :title="title" :subtitle="subtitle" />

    <form novalidate @submit.prevent="emit('submit')">
      <div
        :class="[
          'grid gap-6 items-start',
          $slots.aside ? 'grid-cols-1 xl:grid-cols-[minmax(0,1fr)_22rem]' : 'grid-cols-1',
        ]"
      >
        <div class="space-y-6 min-w-0">
          <slot />
        </div>
        <aside v-if="$slots.aside" class="space-y-6 xl:sticky xl:top-6 min-w-0">
          <slot name="aside" />
        </aside>
      </div>

      <p
        v-if="error"
        class="mt-6 flex items-start gap-2 rounded-md border border-danger/30 bg-danger/10 px-3 py-2.5 text-base text-danger"
        role="alert"
      >
        <AlertTriangle class="w-4 h-4 shrink-0 mt-0.5" aria-hidden="true" />
        <span>{{ error }}</span>
      </p>

      <!-- Pinned to the bottom of the scroll container: on a long form the
           primary action must never be somewhere you have to go looking for.
           The negative margins let the bar span the page gutters. -->
      <div
        class="sticky bottom-0 z-10 -mx-4 sm:-mx-8 mt-8 px-4 sm:px-8 py-4 border-t border-border bg-bg/90 backdrop-blur-sm flex items-center gap-2"
      >
        <div v-if="$slots['actions-start']" class="mr-auto flex items-center gap-2">
          <slot name="actions-start" />
        </div>
        <Button
          type="button"
          variant="secondary"
          :disabled="saving"
          :class="$slots['actions-start'] ? '' : 'ml-auto'"
          @click="emit('cancel')"
        >
          {{ t('common.cancel') }}
        </Button>
        <Button type="submit" variant="primary" :loading="saving">
          {{ submitLabel ?? t('common.save') }}
        </Button>
      </div>
    </form>
  </div>
</template>

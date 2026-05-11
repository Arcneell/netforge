<script setup lang="ts">
import { onMounted, onUnmounted, ref, watch } from 'vue'
import { X } from 'lucide-vue-next'

const props = withDefaults(
  defineProps<{
    open: boolean
    title?: string
    closable?: boolean
    size?: 'sm' | 'md' | 'lg' | 'xl'
  }>(),
  {
    closable: true,
    size: 'md',
  },
)

const emit = defineEmits<{ (e: 'close'): void }>()
const dialogRef = ref<HTMLDivElement | null>(null)

const sizeClass = {
  sm: 'max-w-sm',
  md: 'max-w-md',
  lg: 'max-w-2xl',
  xl: 'max-w-4xl',
} as const

function onKey(e: KeyboardEvent) {
  if (props.open && e.key === 'Escape' && props.closable) emit('close')
}

onMounted(() => window.addEventListener('keydown', onKey))
onUnmounted(() => window.removeEventListener('keydown', onKey))

watch(
  () => props.open,
  (open) => {
    // Trap focus inside the dialog when it opens; restore body scroll when it closes.
    document.body.style.overflow = open ? 'hidden' : ''
    if (open) {
      requestAnimationFrame(() => {
        dialogRef.value?.focus()
      })
    }
  },
)
</script>

<template>
  <Teleport to="body">
    <Transition
      enter-active-class="transition duration-150 ease-out"
      enter-from-class="opacity-0"
      enter-to-class="opacity-100"
      leave-active-class="transition duration-100 ease-in"
      leave-from-class="opacity-100"
      leave-to-class="opacity-0"
    >
      <div
        v-if="open"
        class="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/40 backdrop-blur-sm"
        role="dialog"
        aria-modal="true"
        :aria-label="title"
        @click.self="closable && $emit('close')"
      >
        <Transition
          enter-active-class="transition duration-150 ease-out"
          enter-from-class="opacity-0 translate-y-1 scale-[0.98]"
          enter-to-class="opacity-100 translate-y-0 scale-100"
          leave-active-class="transition duration-100 ease-in"
          leave-from-class="opacity-100 translate-y-0"
          leave-to-class="opacity-0 translate-y-1"
        >
          <div
            v-if="open"
            ref="dialogRef"
            tabindex="-1"
            :class="['nf-card shadow-pop w-full focus:outline-none', sizeClass[size]]"
          >
            <header
              v-if="title || closable"
              class="flex items-center justify-between px-5 py-3 border-b border-border"
            >
              <h2 class="text-sm font-semibold text-fg">{{ title }}</h2>
              <button
                v-if="closable"
                type="button"
                class="p-1 rounded hover:bg-surface-hover text-fg-muted"
                :aria-label="$t('common.close')"
                @click="$emit('close')"
              >
                <X class="w-4 h-4" />
              </button>
            </header>
            <div class="p-5">
              <slot />
            </div>
            <footer v-if="$slots.footer" class="px-5 py-3 border-t border-border bg-muted/40">
              <slot name="footer" />
            </footer>
          </div>
        </Transition>
      </div>
    </Transition>
  </Teleport>
</template>

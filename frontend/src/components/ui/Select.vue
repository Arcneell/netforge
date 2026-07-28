<script setup lang="ts" generic="T extends string | number | boolean">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, useId, watch } from 'vue'
import { Check, ChevronDown } from 'lucide-vue-next'

/**
 * Dropdown with a listbox we render ourselves.
 *
 * A native `<select>` popup is painted by the OS, and Chromium on Windows
 * keeps the light palette for it regardless of `color-scheme: dark` or any
 * `background-color` set on `<option>` — the author `color` is honoured but
 * the background is not, so a dark theme produced light-on-light text. There
 * is no CSS fix for that. Owning the popup is the only way to guarantee the
 * list is readable in both themes.
 *
 * Behaves like a select: click or Enter/Space/Arrow opens it, arrows move,
 * Enter picks, Escape closes and returns focus, typing jumps to a label.
 */
export interface SelectOption<V> {
  value: V
  label: string
  disabled?: boolean
}

const props = withDefaults(
  defineProps<{
    modelValue: T
    options: SelectOption<T>[]
    disabled?: boolean
    id?: string
    ariaLabel?: string
    /** Shown when the current value matches no option. */
    placeholder?: string
    invalid?: boolean
  }>(),
  { disabled: false, id: undefined, ariaLabel: undefined, placeholder: undefined, invalid: false },
)

const emit = defineEmits<{ (e: 'update:modelValue', v: T): void }>()

const autoId = useId()
const listId = computed(() => `${props.id ?? autoId}-listbox`)

const open = ref(false)
const activeIndex = ref(-1)
const triggerRef = ref<HTMLButtonElement | null>(null)
const listRef = ref<HTMLUListElement | null>(null)
// Resolved viewport coordinates for the teleported list. `top` and `bottom`
// are mutually exclusive — whichever edge we anchor to.
const pos = ref<{ top?: number; bottom?: number; left: number; width: number }>({
  left: 0,
  width: 0,
})

const selectedIndex = computed(() => props.options.findIndex((o) => o.value === props.modelValue))
const selectedLabel = computed(() => props.options[selectedIndex.value]?.label ?? null)

const MAX_H = 288 // matches max-h-72 on the list
const GAP = 4

function place() {
  const el = triggerRef.value
  if (!el) return
  const r = el.getBoundingClientRect()
  const below = window.innerHeight - r.bottom
  // Flip above only when there genuinely isn't room below and there is above.
  const openUp = below < Math.min(MAX_H, 180) && r.top > below
  pos.value = openUp
    ? { bottom: window.innerHeight - r.top + GAP, left: r.left, width: r.width }
    : { top: r.bottom + GAP, left: r.left, width: r.width }
}

async function openList() {
  if (props.disabled) return
  open.value = true
  activeIndex.value = selectedIndex.value >= 0 ? selectedIndex.value : firstEnabled()
  await nextTick()
  place()
  scrollActiveIntoView()
}

function toggle() {
  if (open.value) closeList()
  else openList()
}

function closeList(refocus = true) {
  if (!open.value) return
  open.value = false
  if (refocus) triggerRef.value?.focus()
}

function firstEnabled(): number {
  return props.options.findIndex((o) => !o.disabled)
}

function step(delta: number) {
  const n = props.options.length
  if (!n) return
  let i = activeIndex.value
  for (let k = 0; k < n; k++) {
    i = (i + delta + n) % n
    if (!props.options[i].disabled) break
  }
  activeIndex.value = i
  scrollActiveIntoView()
}

function scrollActiveIntoView() {
  nextTick(() => {
    const list = listRef.value
    if (!list) return
    const item = list.children[activeIndex.value] as HTMLElement | undefined
    item?.scrollIntoView({ block: 'nearest' })
  })
}

function pick(i: number) {
  const opt = props.options[i]
  if (!opt || opt.disabled) return
  emit('update:modelValue', opt.value)
  closeList()
}

// Type-ahead: jump to the first option starting with what was typed.
let typed = ''
let typedTimer: ReturnType<typeof setTimeout> | null = null
function typeAhead(char: string) {
  typed += char.toLowerCase()
  if (typedTimer) clearTimeout(typedTimer)
  typedTimer = setTimeout(() => (typed = ''), 600)
  const i = props.options.findIndex((o) => !o.disabled && o.label.toLowerCase().startsWith(typed))
  if (i !== -1) {
    activeIndex.value = i
    if (!open.value) pick(i)
    else scrollActiveIntoView()
  }
}

function onKeydown(e: KeyboardEvent) {
  if (props.disabled) return
  switch (e.key) {
    case 'ArrowDown':
      e.preventDefault()
      if (open.value) step(1)
      else openList()
      return
    case 'ArrowUp':
      e.preventDefault()
      if (open.value) step(-1)
      else openList()
      return
    case 'Home':
      if (open.value) {
        e.preventDefault()
        activeIndex.value = firstEnabled()
        scrollActiveIntoView()
      }
      return
    case 'End':
      if (open.value) {
        e.preventDefault()
        activeIndex.value = props.options.length - 1
        scrollActiveIntoView()
      }
      return
    case 'Enter':
    case ' ':
      e.preventDefault()
      if (open.value) pick(activeIndex.value)
      else openList()
      return
    case 'Escape':
      if (open.value) {
        e.preventDefault()
        e.stopPropagation()
        closeList()
      }
      return
    case 'Tab':
      closeList(false)
      return
    default:
      if (e.key.length === 1 && !e.metaKey && !e.ctrlKey && !e.altKey) typeAhead(e.key)
  }
}

function onDocPointer(e: PointerEvent) {
  if (!open.value) return
  const t = e.target as Node
  if (triggerRef.value?.contains(t) || listRef.value?.contains(t)) return
  closeList(false)
}
function onReflow() {
  if (open.value) place()
}

onMounted(() => {
  window.addEventListener('pointerdown', onDocPointer, true)
  window.addEventListener('resize', onReflow)
  window.addEventListener('scroll', onReflow, true)
})
onBeforeUnmount(() => {
  window.removeEventListener('pointerdown', onDocPointer, true)
  window.removeEventListener('resize', onReflow)
  window.removeEventListener('scroll', onReflow, true)
  if (typedTimer) clearTimeout(typedTimer)
})

// A shrinking option list must not leave the highlight past the end.
watch(
  () => props.options.length,
  (n) => {
    if (activeIndex.value >= n) activeIndex.value = n - 1
  },
)
</script>

<template>
  <div class="relative w-full">
    <button
      :id="id"
      ref="triggerRef"
      type="button"
      role="combobox"
      :aria-expanded="open"
      :aria-controls="listId"
      aria-haspopup="listbox"
      :aria-label="ariaLabel"
      :disabled="disabled"
      :class="[
        'nf-input nf-input-control flex items-center gap-2 text-left cursor-pointer',
        invalid ? 'nf-input-invalid' : '',
        open ? 'border-primary-500 shadow-ring' : '',
      ]"
      @click="toggle"
      @keydown="onKeydown"
    >
      <span :class="['flex-1 truncate', selectedLabel === null ? 'text-fg-subtle' : '']">
        {{ selectedLabel ?? placeholder ?? '' }}
      </span>
      <ChevronDown
        :class="[
          'w-4 h-4 flex-shrink-0 text-fg-subtle transition-transform duration-150 ease-soft',
          open ? 'rotate-180' : '',
        ]"
        aria-hidden="true"
      />
    </button>

    <Teleport to="body">
      <Transition
        enter-active-class="transition duration-100 ease-soft"
        enter-from-class="opacity-0 scale-[0.98]"
        enter-to-class="opacity-100 scale-100"
        leave-active-class="transition duration-75 ease-soft"
        leave-from-class="opacity-100"
        leave-to-class="opacity-0"
      >
        <ul
          v-if="open"
          :id="listId"
          ref="listRef"
          role="listbox"
          :aria-activedescendant="activeIndex >= 0 ? `${listId}-${activeIndex}` : undefined"
          class="fixed z-[70] max-h-72 overflow-y-auto py-1 rounded-lg border border-border bg-surface shadow-lg"
          :style="{
            top: pos.top !== undefined ? `${pos.top}px` : undefined,
            bottom: pos.bottom !== undefined ? `${pos.bottom}px` : undefined,
            left: `${pos.left}px`,
            minWidth: `${pos.width}px`,
          }"
        >
          <li
            v-for="(opt, i) in options"
            :id="`${listId}-${i}`"
            :key="String(opt.value)"
            role="option"
            :aria-selected="opt.value === modelValue"
            :aria-disabled="opt.disabled || undefined"
            :class="[
              'flex items-center gap-2 mx-1 px-2.5 py-1.5 rounded-md text-base cursor-pointer select-none',
              opt.disabled
                ? 'text-fg-subtle cursor-not-allowed'
                : i === activeIndex
                  ? 'bg-primary-50 text-primary-700 dark:bg-primary-500/15 dark:text-primary-300'
                  : 'text-fg',
            ]"
            @pointerenter="!opt.disabled && (activeIndex = i)"
            @click="pick(i)"
          >
            <span class="flex-1 truncate">{{ opt.label }}</span>
            <Check
              v-if="opt.value === modelValue"
              class="w-3.5 h-3.5 flex-shrink-0"
              aria-hidden="true"
            />
          </li>
        </ul>
      </Transition>
    </Teleport>
  </div>
</template>

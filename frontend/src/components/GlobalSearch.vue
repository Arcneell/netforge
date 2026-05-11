<script setup lang="ts">
import { computed, nextTick, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRouter } from 'vue-router'
import { Search, Network, Server, RouterIcon as RouterIco, Plug, X } from 'lucide-vue-next'
import { searchApi } from '@/api'
import type { SearchResult } from '@/api'
import { useDebounce } from '@/composables/useDebounce'

const props = defineProps<{ open: boolean }>()
const emit = defineEmits<{ (e: 'close'): void }>()

const { t } = useI18n()
const router = useRouter()

const query = ref('')
const debounced = useDebounce(query, 200)
const results = ref<SearchResult[]>([])
const loading = ref(false)
const activeIndex = ref(0)
const inputRef = ref<HTMLInputElement | null>(null)

// Visual mapping per result type — keeps the list scannable.
const iconFor: Record<SearchResult['type'], typeof Search> = {
  ip: Network,
  device: Server,
  switch: RouterIco,
  port: Plug,
}

const groupLabel: Record<SearchResult['type'], string> = {
  ip: 'ip.labelPlural',
  device: 'device.labelPlural',
  switch: 'switch.labelPlural',
  port: 'port.labelPlural',
}

watch(
  () => props.open,
  async (open) => {
    if (open) {
      query.value = ''
      results.value = []
      activeIndex.value = 0
      await nextTick()
      inputRef.value?.focus()
    }
  },
)

watch(debounced, async (q) => {
  const trimmed = q.trim()
  if (trimmed.length < 2) {
    results.value = []
    return
  }
  loading.value = true
  try {
    const res = await searchApi.search(trimmed)
    results.value = res.results
    activeIndex.value = 0
  } catch {
    results.value = []
  } finally {
    loading.value = false
  }
})

function routeFor(r: SearchResult): { name: string; params?: Record<string, string | number> } | null {
  switch (r.type) {
    case 'switch':
      return { name: 'switch-detail', params: { id: r.id } }
    case 'ip':
      // parent_id is the IP's subnet — jump to that subnet's detail page.
      // No per-IP route exists; the SubnetDetailView shows the full grid
      // including the IP we want.
      return r.parent_id != null
        ? { name: 'subnet-detail', params: { id: r.parent_id } }
        : { name: 'subnets' }
    case 'device':
      return { name: 'devices' }
    case 'port':
      // parent_id is the port's switch — the switch detail page lists every
      // port and lets the user click into the one they searched for.
      return r.parent_id != null
        ? { name: 'switch-detail', params: { id: r.parent_id } }
        : { name: 'switches' }
    default:
      return null
  }
}

function selectActive() {
  const r = results.value[activeIndex.value]
  if (!r) return
  const route = routeFor(r)
  if (route) router.push(route)
  emit('close')
}

function onKey(e: KeyboardEvent) {
  if (!props.open) return
  if (e.key === 'ArrowDown') {
    e.preventDefault()
    activeIndex.value = Math.min(activeIndex.value + 1, results.value.length - 1)
  } else if (e.key === 'ArrowUp') {
    e.preventDefault()
    activeIndex.value = Math.max(activeIndex.value - 1, 0)
  } else if (e.key === 'Enter') {
    e.preventDefault()
    selectActive()
  } else if (e.key === 'Escape') {
    e.preventDefault()
    emit('close')
  }
}

// Group consecutive same-type results so we can render a sticky group label
// inside the list — easier to scan than 30 mixed rows.
const grouped = computed(() => {
  const out: { type: SearchResult['type']; items: SearchResult[] }[] = []
  for (const r of results.value) {
    const last = out[out.length - 1]
    if (last && last.type === r.type) last.items.push(r)
    else out.push({ type: r.type, items: [r] })
  }
  return out
})

// Flat index → consult activeIndex without iterating twice.
function flatIndex(groupIdx: number, itemIdx: number): number {
  let n = 0
  for (let g = 0; g < groupIdx; g++) n += grouped.value[g].items.length
  return n + itemIdx
}
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
        class="fixed inset-0 z-50 flex items-start justify-center p-4 pt-[12vh] bg-black/40 backdrop-blur-sm"
        role="dialog"
        aria-modal="true"
        :aria-label="t('common.search')"
        @click.self="emit('close')"
        @keydown="onKey"
      >
        <div
          class="nf-card shadow-pop w-full max-w-xl flex flex-col overflow-hidden"
        >
          <div class="flex items-center gap-2 px-3 border-b border-border">
            <Search class="w-4 h-4 text-fg-muted flex-shrink-0" aria-hidden="true" />
            <input
              ref="inputRef"
              v-model="query"
              type="search"
              class="flex-1 bg-transparent border-0 px-1 py-3 text-sm text-fg placeholder:text-fg-muted focus:outline-none focus:ring-0"
              :placeholder="t('common.search') + '…'"
              autocomplete="off"
              spellcheck="false"
            />
            <button
              v-if="query"
              type="button"
              class="p-1 rounded hover:bg-surface-hover text-fg-muted"
              :aria-label="t('common.reset')"
              @click="query = ''"
            >
              <X class="w-4 h-4" aria-hidden="true" />
            </button>
            <kbd class="hidden sm:inline-block text-[10px] font-mono px-1.5 py-0.5 rounded bg-muted text-fg-muted border border-border">
              Esc
            </kbd>
          </div>

          <div class="max-h-[60vh] overflow-y-auto py-1" role="listbox">
            <p
              v-if="!loading && query.trim().length < 2"
              class="px-4 py-6 text-xs text-fg-muted text-center"
            >
              {{ t('common.searchHint') }}
            </p>
            <p
              v-else-if="loading"
              class="px-4 py-6 text-xs text-fg-muted text-center"
            >
              {{ t('common.loading') }}
            </p>
            <p
              v-else-if="results.length === 0"
              class="px-4 py-6 text-xs text-fg-muted text-center"
            >
              {{ t('common.empty.title') }}
            </p>

            <template v-for="(group, gi) in grouped" :key="group.type">
              <p
                class="px-3 pt-2 pb-1 text-[10px] font-semibold uppercase tracking-wider text-fg-muted"
              >
                {{ t(groupLabel[group.type]) }}
              </p>
              <button
                v-for="(item, ii) in group.items"
                :key="`${item.type}-${item.id}`"
                type="button"
                role="option"
                :aria-selected="flatIndex(gi, ii) === activeIndex"
                class="flex items-center gap-2 w-full px-3 py-2 text-left transition"
                :class="
                  flatIndex(gi, ii) === activeIndex
                    ? 'bg-primary-100 dark:bg-primary-900/40 text-primary-700 dark:text-primary-300'
                    : 'text-fg hover:bg-surface-hover'
                "
                @mouseenter="activeIndex = flatIndex(gi, ii)"
                @click="selectActive"
              >
                <component
                  :is="iconFor[item.type]"
                  class="w-4 h-4 flex-shrink-0"
                  aria-hidden="true"
                />
                <span class="text-sm font-medium truncate">{{ item.label }}</span>
                <span
                  v-if="item.context"
                  class="text-xs text-fg-muted truncate ml-auto pl-2 font-mono"
                >
                  {{ item.context }}
                </span>
              </button>
            </template>
          </div>

          <div
            class="px-3 py-2 border-t border-border bg-muted/40 text-[11px] text-fg-muted flex items-center gap-3"
          >
            <span class="flex items-center gap-1">
              <kbd class="font-mono px-1 rounded bg-surface border border-border">↑</kbd>
              <kbd class="font-mono px-1 rounded bg-surface border border-border">↓</kbd>
              {{ t('shortcuts.navigate') }}
            </span>
            <span class="flex items-center gap-1">
              <kbd class="font-mono px-1 rounded bg-surface border border-border">↵</kbd>
              {{ t('shortcuts.open') }}
            </span>
          </div>
        </div>
      </div>
    </Transition>
  </Teleport>
</template>

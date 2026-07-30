<script setup lang="ts">
import { computed, nextTick, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRouter } from 'vue-router'
import {
  Search,
  Network,
  Server,
  RouterIcon as RouterIco,
  Plug,
  X,
  Building2,
  DoorOpen,
  Tag,
  Globe,
} from '@lucide/vue'
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
  site: Building2,
  room: DoorOpen,
  vlan: Tag,
  subnet: Globe,
}

const groupLabel: Record<SearchResult['type'], string> = {
  ip: 'ip.labelPlural',
  device: 'device.labelPlural',
  switch: 'switch.labelPlural',
  port: 'port.labelPlural',
  site: 'site.labelPlural',
  room: 'room.labelPlural',
  vlan: 'vlan.labelPlural',
  subnet: 'subnet.labelPlural',
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

// Sequence guard against the keystroke race. With a 200ms debounce + a slow
// backend, "swit" → "switch" → "switche" can have three searches in flight;
// whichever resolves LAST wins on `results.value = …` because there's no
// ordering. Pin the freshest call by token so the late stragglers are
// dropped silently.
let searchSeq = 0

watch(debounced, async (q) => {
  const trimmed = q.trim()
  if (trimmed.length < 2) {
    results.value = []
    return
  }
  const seq = ++searchSeq
  loading.value = true
  try {
    const res = await searchApi.search(trimmed)
    if (seq !== searchSeq) return
    results.value = res.results
    activeIndex.value = 0
  } catch {
    if (seq !== searchSeq) return
    results.value = []
  } finally {
    if (seq === searchSeq) loading.value = false
  }
})

function routeFor(r: SearchResult): {
  name: string
  params?: Record<string, string | number>
  query?: Record<string, string>
} | null {
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
    case 'subnet':
      return { name: 'subnet-detail', params: { id: r.id } }
    case 'vlan':
      // No per-VLAN detail route — land on the VLAN list with `?highlight=`
      // so the list scrolls to and rings the matching row (useRowHighlight)
      // instead of just dropping the user on the bare list.
      return { name: 'vlans', query: { highlight: String(r.id) } }
    case 'site':
      // Sites aren't owners of a dedicated detail page; they live in the
      // Sites tab of SettingsView. `?tab=` opens the right tab, `?highlight=`
      // rings the matching row once it's loaded.
      return { name: 'settings', query: { tab: 'sites', highlight: String(r.id) } }
    case 'room':
      return { name: 'settings', query: { tab: 'rooms', highlight: String(r.id) } }
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
      enter-active-class="transition-opacity duration-150 ease-soft"
      enter-from-class="opacity-0"
      enter-to-class="opacity-100"
      leave-active-class="transition-opacity duration-100 ease-soft"
      leave-from-class="opacity-100"
      leave-to-class="opacity-0"
    >
      <div
        v-if="open"
        class="fixed inset-0 z-50 flex items-start justify-center p-4 pt-[12vh] bg-plate/70 backdrop-blur-sm"
        role="dialog"
        aria-modal="true"
        :aria-label="t('common.search')"
        @click.self="emit('close')"
        @keydown="onKey"
      >
        <div class="nf-card shadow-xl w-full max-w-xl flex flex-col overflow-hidden nf-enter">
          <div class="flex items-center gap-2.5 px-4 border-b border-border">
            <Search class="w-4 h-4 text-fg-subtle flex-shrink-0" aria-hidden="true" />
            <input
              ref="inputRef"
              v-model="query"
              type="search"
              class="flex-1 bg-transparent border-0 px-0 py-3.5 text-base text-fg placeholder:text-fg-subtle focus:outline-none focus:ring-0"
              :placeholder="t('common.search') + '…'"
              autocomplete="off"
              spellcheck="false"
            />
            <button
              v-if="query"
              type="button"
              class="p-1 rounded-md hover:bg-surface-hover text-fg-subtle hover:text-fg transition-colors duration-150 ease-soft"
              :aria-label="t('common.reset')"
              @click="query = ''"
            >
              <X class="w-4 h-4" aria-hidden="true" />
            </button>
            <kbd
              class="hidden sm:inline-block text-2xs font-medium px-1.5 py-0.5 rounded bg-muted text-fg-subtle"
            >
              Esc
            </kbd>
          </div>

          <div class="max-h-[60vh] overflow-y-auto py-1.5" role="listbox">
            <p
              v-if="!loading && query.trim().length < 2"
              class="px-4 py-8 text-sm text-fg-subtle text-center"
            >
              {{ t('common.searchHint') }}
            </p>
            <p v-else-if="loading" class="px-4 py-8 text-sm text-fg-subtle text-center">
              {{ t('common.loading') }}
            </p>
            <p
              v-else-if="results.length === 0"
              class="px-4 py-8 text-sm text-fg-subtle text-center"
            >
              {{ t('common.empty.title') }}
            </p>

            <template v-for="(group, gi) in grouped" :key="group.type">
              <p class="nf-label px-3 pt-2 pb-1">
                {{ t(groupLabel[group.type]) }}
              </p>
              <button
                v-for="(item, ii) in group.items"
                :key="`${item.type}-${item.id}`"
                type="button"
                role="option"
                :aria-selected="flatIndex(gi, ii) === activeIndex"
                class="flex items-center gap-2.5 w-full px-4 py-2 text-left rounded-md transition-colors duration-100 ease-soft"
                :class="
                  flatIndex(gi, ii) === activeIndex
                    ? 'bg-primary-50 text-primary-700 dark:bg-primary-500/15 dark:text-primary-300'
                    : 'text-fg hover:bg-surface-hover'
                "
                @mouseenter="activeIndex = flatIndex(gi, ii)"
                @click="selectActive"
              >
                <component
                  :is="iconFor[item.type]"
                  class="w-4 h-4 flex-shrink-0"
                  :stroke-width="1.9"
                  aria-hidden="true"
                />
                <span class="text-base truncate">{{ item.label }}</span>
                <span
                  v-if="item.context"
                  class="text-xs text-fg-subtle truncate ml-auto pl-2 font-mono"
                >
                  {{ item.context }}
                </span>
              </button>
            </template>
          </div>

          <div
            class="px-4 py-2.5 border-t border-border bg-bg/60 text-2xs text-fg-subtle flex items-center gap-4"
          >
            <span class="flex items-center gap-1.5">
              <kbd class="px-1.5 py-0.5 rounded bg-muted text-fg-muted">↑</kbd>
              <kbd class="px-1.5 py-0.5 rounded bg-muted text-fg-muted">↓</kbd>
              {{ t('shortcuts.navigate') }}
            </span>
            <span class="flex items-center gap-1.5">
              <kbd class="px-1.5 py-0.5 rounded bg-muted text-fg-muted">↵</kbd>
              {{ t('shortcuts.open') }}
            </span>
          </div>
        </div>
      </div>
    </Transition>
  </Teleport>
</template>

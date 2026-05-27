<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import type { SubnetIpEntry } from '@/api'

const props = defineProps<{
  ips: SubnetIpEntry[]
}>()

defineEmits<{ (e: 'select', entry: SubnetIpEntry): void }>()

const { t } = useI18n()

type StatusKey = 'assigned' | 'reserved' | 'dhcp' | 'free'

// Cell classes (used on the clickable IP buttons in the grid). They share
// the `bg-*` token with the legend so the swatch under each label matches
// what an IP of that status looks like on the grid.
const statusClass: Record<StatusKey, string> = {
  assigned: 'bg-primary-500 hover:bg-primary-600 text-white border-primary-600',
  reserved: 'bg-warning/90 hover:bg-warning text-white border-warning',
  dhcp: 'bg-success/80 hover:bg-success text-white border-success',
  // Free cells: muted fill on a slightly darker border so the empty
  // addresses stay distinguishable from the white card background in
  // light mode and from the elevated surface in dark mode.
  free: 'bg-muted/60 hover:bg-surface-hover text-fg-muted border-border',
}

// Legend swatches — same fill as the cell, plus an explicit 1-px border so
// every chip stays visible against `bg-surface` (the card it sits on). The
// cells themselves already get `border` via the button class, but the
// legend swatch is a plain `<span>` and would otherwise be borderless.
const legendSwatchClass: Record<StatusKey, string> = {
  assigned: 'bg-primary-500 border border-primary-600',
  reserved: 'bg-warning border border-warning',
  dhcp: 'bg-success border border-success',
  free: 'bg-muted/60 border border-border',
}

const statusLabel = computed<Record<StatusKey, string>>(() => ({
  assigned: t('ip.status.assigned'),
  reserved: t('ip.status.reserved'),
  dhcp: t('ip.status.dhcp'),
  free: t('ip.status.free'),
}))

function keyFor(status: string): StatusKey {
  return (status in statusClass ? status : 'free') as StatusKey
}

// --- Virtualisation by IntersectionObserver -------------------------------
//
// Rendering all 4096 cells of a /20 every time the grid renders (and on
// every reactive update) costs measurable time in DevTools. Instead we
// split the address list into fixed-size chunks of 128 addresses, render
// the chunk container always (so layout is stable), but only mount the
// inner cells when the chunk is near the viewport.
//
// Off-screen chunks render a tiny placeholder with a reserved height
// computed from the chunk size — keeps the scroll bar honest. The CSS
// grid uses `auto-fill, minmax(2.25rem, 1fr)`, so we don't know the exact
// column count up front; reserve a conservative four-rows worth (4 ×
// 36 px) so the scrollbar never collapses to zero on narrow viewports.
//
// rootMargin = "400px" preloads chunks before they're visible so quick
// scroll never reveals a blank patch.

const CHUNK_SIZE = 128

interface Chunk {
  /** Stable id so the IntersectionObserver can keep its mapping across
   *  the rare case where the same chunk index appears in two subnets
   *  (Vue tears down on subnet change so this is mostly defensive). */
  id: string
  entries: SubnetIpEntry[]
}

const chunks = computed<Chunk[]>(() => {
  const out: Chunk[] = []
  for (let i = 0; i < props.ips.length; i += CHUNK_SIZE) {
    out.push({
      id: `chunk-${i}`,
      entries: props.ips.slice(i, i + CHUNK_SIZE),
    })
  }
  return out
})

// Which chunks are currently mounted. Starts empty — the
// IntersectionObserver populates it as soon as the elements mount,
// including the ones already in view (the observer fires once
// synchronously after `.observe()`).
const visibleChunks = ref<Set<string>>(new Set())
const chunkRefs = ref<Map<string, HTMLDivElement>>(new Map())
let observer: IntersectionObserver | null = null
// Set to `true` once we discover the runtime doesn't have
// IntersectionObserver (SSR, jsdom, very old browsers). In that mode we
// render every chunk eagerly and the watcher MUST repopulate the set
// when `props.ips` changes — otherwise the grid stays blank after the
// first reload (Codex P1 on #81).
const fallbackEager = ref(false)

// Stable per-chunk-id callbacks, cached in a Map. Without this the
// template `:ref="setChunkRef(chunk.id)"` builds a NEW function identity
// every render — Vue then runs the previous one with `null` (unobserve +
// delete) and the new one with the element (observe + set) on every
// reactive change of `props.ips` or any parent re-render, defeating the
// virtualisation perf gains and momentarily emptying chunkRefs.
const _refCallbacks = new Map<string, (el: unknown) => void>()

function setChunkRef(id: string): (el: unknown) => void {
  const cached = _refCallbacks.get(id)
  if (cached) return cached
  // Vue's :ref callback is typed `(ref: Element | ComponentPublicInstance
  // | null) => void`. We're attaching to a plain <div>, so we narrow with
  // `instanceof` before storing it.
  const cb = (el: unknown) => {
    if (el instanceof HTMLDivElement) {
      chunkRefs.value.set(id, el)
      observer?.observe(el)
    } else {
      const prev = chunkRefs.value.get(id)
      if (prev) observer?.unobserve(prev)
      chunkRefs.value.delete(id)
    }
  }
  _refCallbacks.set(id, cb)
  return cb
}

onMounted(() => {
  // Defensive: SSR or test environments without IntersectionObserver
  // fall back to rendering every chunk eagerly. Same behaviour as the
  // pre-virtualisation code path, no regression.
  if (typeof IntersectionObserver === 'undefined') {
    fallbackEager.value = true
    visibleChunks.value = new Set(chunks.value.map((c) => c.id))
    return
  }
  observer = new IntersectionObserver(
    (entries) => {
      // Single state mutation per batch — avoids triggering a Vue update
      // per chunk when twenty observers fire on the same scroll tick.
      const next = new Set(visibleChunks.value)
      let changed = false
      for (const entry of entries) {
        const id = (entry.target as HTMLDivElement).dataset.chunkId
        if (!id) continue
        if (entry.isIntersecting) {
          if (!next.has(id)) {
            next.add(id)
            changed = true
          }
        } else if (next.has(id)) {
          next.delete(id)
          changed = true
        }
      }
      if (changed) visibleChunks.value = next
    },
    {
      // Preload chunks ~400 px above/below the viewport so quick scrolls
      // never reveal an empty patch.
      rootMargin: '400px 0px',
      threshold: 0,
    },
  )
  for (const el of chunkRefs.value.values()) observer.observe(el)
})

onBeforeUnmount(() => {
  observer?.disconnect()
  observer = null
})

// When the IPs list changes (e.g. parent reload after a bulk action)
// the chunk ids may or may not change:
//
//  - DIFFERENT subnet (size changed, navigated to another /subnets/:id):
//    chunk ids differ → Vue unmounts old chunks and mounts new ones →
//    the stable per-id ref callbacks (PR #94) call `setChunkRef`'s
//    handler with null then the new element → IntersectionObserver
//    re-attaches and fires once synchronously. Safe to clear
//    `visibleChunks`; the IO repopulates it on the next paint.
//
//  - SAME size reload (bulk-IP edit, individual IP status change): chunk
//    ids stay the same. The cached ref callbacks (PR #94) keep the
//    SAME element references, so Vue does NOT call setChunkRef with
//    null + new — the observer never re-fires. If we cleared
//    `visibleChunks` here, the grid would render as the empty
//    placeholder strip until the user scrolled, which Codex P1 on
//    #94 flagged. So: only clear the set when the chunk-id set
//    actually changed, and re-observe explicitly otherwise.
let _lastChunkIds: string[] = []
watch(
  () => props.ips,
  () => {
    const ids = chunks.value.map((c) => c.id)
    const idsChanged =
      ids.length !== _lastChunkIds.length || ids.some((id, i) => id !== _lastChunkIds[i])
    _lastChunkIds = ids

    if (fallbackEager.value) {
      visibleChunks.value = new Set(ids)
      return
    }
    if (idsChanged) {
      // The cached ref-callbacks were freed for the dropped chunk ids
      // when their elements unmounted; drop the cached entries too so
      // a future subnet with the same chunk-N name doesn't re-use a
      // stale callback bound to the previous lifetime.
      for (const id of _refCallbacks.keys()) {
        if (!ids.includes(id)) _refCallbacks.delete(id)
      }
      visibleChunks.value = new Set()
    } else {
      // Same ids — same DOM elements per stable refs. Keep the set;
      // the IO will fire on real intersection changes. Belt-and-braces
      // re-observe in case the observer was disconnected for any reason.
      if (observer) {
        for (const el of chunkRefs.value.values()) observer.observe(el)
      }
    }
  },
)

// Placeholder height: needs to stay close to the actual chunk height
// so the scrollbar doesn't jump when a chunk renders in. With the
// `auto-fill, minmax(2.25rem, 1fr)` rule, 128 cells render as
// roughly 5–10 rows depending on viewport width. 22 rem (≈ 352 px,
// or 8 rows of 36 + 4 px) covers the common 1024–1440 px desktop
// width comfortably. On very narrow viewports (~5 columns) the
// chunk may still be slightly taller, but the worst-case downward
// scroll jump is one or two rows instead of the previous 200 px.
</script>

<template>
  <div>
    <div class="flex flex-wrap items-center gap-4 mb-3 text-xs text-fg-muted">
      <span
        v-for="status in ['assigned', 'reserved', 'dhcp', 'free'] as const"
        :key="status"
        class="inline-flex items-center gap-1.5"
      >
        <span
          :class="['inline-block w-3.5 h-3.5 rounded-sm flex-shrink-0', legendSwatchClass[status]]"
          aria-hidden="true"
        />
        <span>{{ statusLabel[status] }}</span>
      </span>
    </div>

    <div role="grid" :aria-label="t('subnet.viewGrid')" :aria-rowcount="chunks.length">
      <div
        v-for="(chunk, idx) in chunks"
        :key="chunk.id"
        :ref="setChunkRef(chunk.id)"
        :data-chunk-id="chunk.id"
        :class="['grid gap-1', idx < chunks.length - 1 ? 'mb-1' : '']"
        :style="{
          gridTemplateColumns: 'repeat(auto-fill, minmax(2.25rem, 1fr))',
          // Reserve space for the placeholder so the scrollbar stays
          // honest as chunks render in. Once populated we let the
          // grid auto-size to its real content.
          minHeight: visibleChunks.has(chunk.id) ? undefined : '22rem',
        }"
      >
        <template v-if="visibleChunks.has(chunk.id)">
          <button
            v-for="entry in chunk.entries"
            :key="entry.address"
            type="button"
            :class="[
              'group relative h-9 text-[10px] font-mono rounded border transition flex items-center justify-center px-1 truncate',
              statusClass[keyFor(entry.status)],
            ]"
            :title="`${entry.address} · ${statusLabel[keyFor(entry.status)]}${entry.hostname ? ' · ' + entry.hostname : ''}`"
            :aria-label="`${entry.address} ${entry.status}`"
            @click="$emit('select', entry)"
          >
            <!-- Show last octet for compactness; full address surfaces in the tooltip. -->
            <span>{{ entry.address.split('.').pop() }}</span>
          </button>
        </template>
      </div>
    </div>
  </div>
</template>

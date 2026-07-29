<script setup lang="ts">
import { computed, ref } from 'vue'
import { useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { intToIp, parseCidr } from '@/utils/cidr'
import { formatNumber } from '@/utils/formatters'

/**
 * The address space, drawn.
 *
 * This is the one thing an IPAM can show that no other product can, so it opens
 * the app instead of a row of counters. Subnets are grouped by the private space
 * they live in, and each group becomes a track of 128 equal slices sitting on a
 * baseline. A slice is a real, contiguous range of addresses; a bar carries two
 * nested signals:
 *
 *   · the outer bar's height  — how many blocks live in that slice, relative to
 *                               the busiest slice in the track
 *   · the inner bar's height  — how much of those blocks' capacity is in use
 *
 * Two decisions make it readable, and both are worth stating because the obvious
 * alternatives fail on real data:
 *
 * 1. The track is zoomed to the smallest power-of-two block that encloses its
 *    members, not to the whole /8. A deployment with a hundred /24s inside
 *    10.0.0.0/8 occupies 0.15 % of it, so a full-/8 axis is 99 % empty and
 *    carries no information. The axis labels always state the real bounds, so
 *    zooming costs nothing in honesty.
 *
 * 2. Bar height is block *count*, normalised per track — not the share of the
 *    slice that is carved. Carved share is the intuitive choice and it is
 *    useless here: at any realistic scale it rounds to zero and every bar
 *    collapses to the floor. Count answers the question an operator actually
 *    has — where is my inventory concentrated, and where is there room. The
 *    carved percentage is still reported, as a number, in the track's legend.
 *
 * Below the tracks sits the readout: a fixed strip that names whatever the
 * pointer or the keyboard cursor is over. That is deliberately not a floating
 * tooltip — an instrument has a display, and a display doesn't move.
 */

interface BandSubnet {
  id: number
  cidr: string
  used?: number
  usable?: number
  description?: string | null
}

const props = withDefaults(
  defineProps<{
    subnets: BandSubnet[]
    loading?: boolean
    /** Total subnets on file, when more exist than were fetched. */
    total?: number
  }>(),
  { loading: false, total: 0 },
)

const { t } = useI18n()
const router = useRouter()

/** 128 keeps every slice boundary on a power-of-two prefix: a /8 divides into
 *  /15s, a /12 into /19s, a /16 into /23s. Arbitrary counts would put slice
 *  edges mid-subnet and the band would stop being addressable. */
const CELLS = 128

/** The spaces worth drawing on their own axis. Anything outside them lands in
 *  a final track spanning only the range those subnets actually occupy. */
const KNOWN_SPACES = [
  { key: 'net10', cidr: '10.0.0.0/8' },
  { key: 'net172', cidr: '172.16.0.0/12' },
  { key: 'net192', cidr: '192.168.0.0/16' },
  { key: 'cgnat', cidr: '100.64.0.0/10' },
]

interface Cell {
  /** Addresses in this slice that belong to some subnet. */
  carved: number
  usable: number
  used: number
  subnetIds: number[]
  cidrs: string[]
  startInt: number
  endInt: number
}

interface Track {
  key: string
  label: string
  startInt: number
  endInt: number
  cells: Cell[]
  subnetCount: number
  usable: number
  used: number
  carvedPct: number
  /** Blocks in the busiest slice — the scale every bar in this track is drawn
   *  against. Without it the tallest bar would mean something different from
   *  track to track. */
  maxCount: number
}

interface Parsed {
  id: number
  cidr: string
  startInt: number
  endInt: number
  total: number
  usable: number
  used: number
}

const parsed = computed<Parsed[]>(() =>
  props.subnets
    .map((s) => {
      try {
        const p = parseCidr(s.cidr)
        return {
          id: s.id,
          cidr: s.cidr,
          startInt: p.networkInt,
          endInt: p.networkInt + p.total - 1,
          total: p.total,
          // Fall back to the block's own capacity when the API omitted it, so a
          // subnet never reads as zero-capacity and vanishes from the band.
          usable: s.usable ?? p.usable,
          used: s.used ?? 0,
        }
      } catch {
        // A malformed CIDR is a data problem, not a rendering problem. Drop it
        // from the band rather than taking the dashboard down.
        return null
      }
    })
    .filter((p): p is Parsed => p !== null),
)

function buildTrack(key: string, label: string, startInt: number, size: number, members: Parsed[]) {
  // A track narrower than 128 addresses gets one cell per address rather than
  // 128 cells over a 128-address span: at `slice = 1` the surplus cells all
  // clamp their end to the track's last address, which lands *before* their own
  // start and makes the readout print a backwards range.
  const cellCount = Math.max(1, Math.min(CELLS, size))
  const slice = Math.max(1, Math.ceil(size / cellCount))
  const cells: Cell[] = Array.from({ length: cellCount }, (_, i) => ({
    carved: 0,
    usable: 0,
    used: 0,
    subnetIds: [],
    cidrs: [],
    startInt: startInt + i * slice,
    endInt: Math.min(startInt + size - 1, startInt + (i + 1) * slice - 1),
  }))

  for (const s of members) {
    const first = Math.max(0, Math.floor((s.startInt - startInt) / slice))
    const last = Math.min(cellCount - 1, Math.floor((s.endInt - startInt) / slice))
    for (let i = first; i <= last; i++) {
      const cell = cells[i]
      const overlap = Math.min(s.endInt, cell.endInt) - Math.max(s.startInt, cell.startInt) + 1
      if (overlap <= 0) continue
      const share = overlap / s.total
      cell.carved += overlap
      cell.usable += s.usable * share
      cell.used += s.used * share
      cell.subnetIds.push(s.id)
      cell.cidrs.push(s.cidr)
    }
  }

  const usable = members.reduce((a, s) => a + s.usable, 0)
  const used = members.reduce((a, s) => a + s.used, 0)
  const carved = members.reduce((a, s) => a + s.total, 0)
  return {
    key,
    label,
    startInt,
    endInt: startInt + size - 1,
    cells,
    subnetCount: members.length,
    usable,
    used,
    carvedPct: size > 0 ? carved / size : 0,
    maxCount: cells.reduce((m, c) => Math.max(m, c.subnetIds.length), 0),
  } satisfies Track
}

/**
 * The smallest power-of-two block containing both addresses — i.e. their common
 * prefix. `Math.clz32` of the XOR is exactly the number of leading bits the two
 * share, which is the prefix length.
 */
function enclosingBlock(startInt: number, endInt: number) {
  const diff = (startInt ^ endInt) >>> 0
  const prefix = diff === 0 ? 32 : Math.clz32(diff)
  // A 32-bit shift is a no-op in JS rather than a zero, so /0 gets handled
  // explicitly instead of silently returning the wrong base.
  if (prefix === 0) return { base: 0, size: 2 ** 32, prefix: 0 }
  const mask = (0xffffffff << (32 - prefix)) >>> 0
  return { base: (startInt & mask) >>> 0, size: 2 ** (32 - prefix), prefix }
}

/** `10.0.0.0/11` — the label a track wears, derived from the block it draws. */
function blockLabel(base: number, prefix: number): string {
  return `${intToIp(base)}/${prefix}`
}

const tracks = computed<Track[]>(() => {
  const remaining = new Set(parsed.value)
  const out: Track[] = []

  // The known spaces only decide the *grouping* — they stop one track from
  // spanning 10.x to 192.168.x, which no axis could usefully label. The extent
  // each track actually draws is the enclosing block of its own members.
  for (const space of KNOWN_SPACES) {
    const p = parseCidr(space.cidr)
    const members = [...remaining].filter(
      (s) => s.startInt >= p.networkInt && s.endInt <= p.networkInt + p.total - 1,
    )
    if (members.length === 0) continue
    members.forEach((m) => remaining.delete(m))
    const lo = Math.min(...members.map((s) => s.startInt))
    const hi = Math.max(...members.map((s) => s.endInt))
    const block = enclosingBlock(lo, hi)
    out.push(
      buildTrack(space.key, blockLabel(block.base, block.prefix), block.base, block.size, members),
    )
  }

  // Everything left over — public ranges, CGNAT edge cases, anything the deploy
  // uses that isn't RFC 1918. Same treatment: the enclosing block of what's
  // there, since there is no meaningful parent to draw it inside.
  const rest = [...remaining]
  if (rest.length > 0) {
    const lo = Math.min(...rest.map((s) => s.startInt))
    const hi = Math.max(...rest.map((s) => s.endInt))
    const block = enclosingBlock(lo, hi)
    out.push(
      buildTrack('other', blockLabel(block.base, block.prefix), block.base, block.size, rest),
    )
  }

  return out
})

/** Outer bar: blocks in this slice as a share of the busiest slice in the track,
 *  floored at 12 % so a slice holding one block out of a busy track's twenty is
 *  still unmistakably there rather than a smudge on the baseline. */
function barHeight(cell: Cell, track: Track): number {
  const count = cell.subnetIds.length
  if (count <= 0) return 0
  if (track.maxCount <= 1) return 1
  return Math.max(0.12, Math.min(1, count / track.maxCount))
}

/** Inner bar: share of the enclosed blocks' capacity that is in use. Relative to
 *  the outer bar, not the slice, so it survives the floor above. Floored at 10 %
 *  of the bar: a barely-populated estate is common, and "some addresses are in
 *  use here" has to be distinguishable from "none are". */
function usedHeight(cell: Cell): number {
  if (cell.usable <= 0 || cell.used <= 0) return 0
  return Math.max(0.1, Math.min(1, cell.used / cell.usable))
}

// ---------------------------------------------------------------------------
// Cursor + readout
// ---------------------------------------------------------------------------

const cursor = ref<{ track: number; cell: number } | null>(null)

/** One listener per track rather than one per cell: 512 mouseenter handlers is
 *  a lot of bookkeeping for a value we can read off the pointer's offset. Bounds
 *  come from the track's own cell count, which is below CELLS on narrow tracks. */
function onTrackMove(event: MouseEvent, trackIndex: number) {
  const count = tracks.value[trackIndex]?.cells.length ?? 0
  if (count === 0) return
  const rect = (event.currentTarget as HTMLElement).getBoundingClientRect()
  if (rect.width === 0) return
  const i = Math.floor(((event.clientX - rect.left) / rect.width) * count)
  cursor.value = { track: trackIndex, cell: Math.min(count - 1, Math.max(0, i)) }
}

/** Keyboard parity without 512 tab stops: the track itself takes focus and the
 *  arrow keys walk the cursor along it. */
function onTrackKey(event: KeyboardEvent, trackIndex: number) {
  const track = tracks.value[trackIndex]
  if (!track) return
  const last = track.cells.length - 1
  const current = cursor.value?.track === trackIndex ? cursor.value.cell : -1
  let next = current
  switch (event.key) {
    case 'ArrowRight':
      next = Math.min(last, current + 1)
      break
    case 'ArrowLeft':
      next = Math.max(0, current <= 0 ? 0 : current - 1)
      break
    case 'Home':
      next = 0
      break
    case 'End':
      next = last
      break
    case 'Enter':
    case ' ':
      if (current >= 0) openCell(track.cells[current])
      event.preventDefault()
      return
    default:
      return
  }
  event.preventDefault()
  cursor.value = { track: trackIndex, cell: next }
}

function onTrackFocus(trackIndex: number) {
  if (cursor.value?.track === trackIndex) return
  const track = tracks.value[trackIndex]
  const first = track?.cells.findIndex((c) => c.carved > 0) ?? -1
  cursor.value = { track: trackIndex, cell: first >= 0 ? first : 0 }
}

const activeCell = computed<Cell | null>(() => {
  if (!cursor.value) return null
  return tracks.value[cursor.value.track]?.cells[cursor.value.cell] ?? null
})

/** A slice resolves to a subnet when it holds exactly one; otherwise it hands
 *  off to the list, pre-filtered to the range the user was looking at. */
function openCell(cell: Cell | null) {
  if (!cell) return
  const ids = [...new Set(cell.subnetIds)]
  if (ids.length === 1) {
    router.push(`/subnets/${ids[0]}`)
  } else if (ids.length > 1) {
    router.push({
      path: '/subnets',
      query: { q: intToIp(cell.startInt).split('.').slice(0, 2).join('.') },
    })
  }
}

const totals = computed(() => {
  const used = parsed.value.reduce((a, s) => a + s.used, 0)
  const usable = parsed.value.reduce((a, s) => a + s.usable, 0)
  return { count: parsed.value.length, used, usable }
})

const truncated = computed(() => props.total > props.subnets.length)

/** One decimal below 10 %, because subnet estates routinely sit at 1–2 % of the
 *  block that encloses them and "0 %" reads as a bug rather than as sparse. */
function pct(n: number): string {
  const v = n * 100
  return `${v > 0 && v < 10 ? v.toFixed(1) : Math.round(v)} %`
}
</script>

<template>
  <!-- The plate. Chamfered top-right corner — the milled edge of a rack panel,
       and the only element in the interface allowed that shape. -->
  <section class="nf-chamfer nf-plate-lip bg-plate text-plate-fg px-4 pt-3.5 pb-0 sm:px-6">
    <div class="flex items-baseline justify-between gap-4 flex-wrap">
      <h2 class="nf-legend text-plate-fg-muted">{{ t('dashboard.band.title') }}</h2>
      <!-- Key. Two swatches, because the band carries exactly two signals. -->
      <div class="flex items-center gap-4">
        <span class="nf-legend text-plate-fg-muted flex items-center gap-1.5">
          <span class="w-2.5 h-2.5 bg-primary-700 flex-shrink-0" aria-hidden="true" />
          {{ t('dashboard.band.legendBlocks') }}
        </span>
        <span class="nf-legend text-plate-fg-muted flex items-center gap-1.5">
          <span class="w-2.5 h-2.5 bg-primary-400 flex-shrink-0" aria-hidden="true" />
          {{ t('dashboard.band.legendUsed') }}
        </span>
      </div>
    </div>

    <!-- Loading: the frame and its slices are already there, empty. Nothing
         moves except the pulse, because the layout is about to be identical. -->
    <div v-if="loading" class="mt-5 mb-5" aria-busy="true">
      <div class="flex gap-px h-14 border-b border-plate-border animate-pulse">
        <span
          v-for="i in CELLS"
          :key="`sk-${i}`"
          class="flex-1 min-w-0 self-end h-1.5 bg-plate-fg/[0.10]"
          aria-hidden="true"
        />
      </div>
    </div>

    <!-- Empty: an invitation, not a shrug. -->
    <div v-else-if="tracks.length === 0" class="mt-5 mb-6">
      <p class="text-base text-plate-fg-muted">{{ t('dashboard.band.empty') }}</p>
      <RouterLink
        to="/subnets/new"
        class="inline-flex items-center gap-1.5 mt-3 h-8 px-3 rounded-md bg-primary-600 hover:bg-primary-500 text-white text-base font-medium transition-colors duration-150 ease-panel"
      >
        {{ t('dashboard.band.emptyCta') }}
      </RouterLink>
    </div>

    <template v-else>
      <div class="mt-5 space-y-4">
        <div v-for="(track, ti) in tracks" :key="track.key">
          <div class="flex items-baseline justify-between gap-3 mb-1.5">
            <span class="font-mono text-xs text-plate-fg tabular-nums">{{ track.label }}</span>
            <span class="nf-legend text-plate-fg-muted">
              {{
                t('dashboard.band.trackMeta', { n: track.subnetCount, pct: pct(track.carvedPct) })
              }}
            </span>
          </div>

          <!-- The bars stand on a baseline rather than inside a row of filled
               slots. An empty slice draws nothing at all: with 128 slices and a
               sparse estate, faint full-height blocks turn the whole panel into
               one dark rectangle and the actual data disappears into it.

               `role="group"`, not `img`: the track takes focus and responds to
               arrow keys, and a focusable, clickable element must not claim a
               non-interactive role. -->
          <div
            class="flex gap-px h-14 cursor-crosshair outline-offset-4 border-b border-plate-border"
            role="group"
            tabindex="0"
            :aria-label="
              t('dashboard.band.trackAria', {
                cidr: track.label,
                n: track.subnetCount,
                pct: pct(track.carvedPct),
              })
            "
            @mousemove="onTrackMove($event, ti)"
            @mouseleave="cursor = null"
            @focus="onTrackFocus(ti)"
            @blur="cursor = null"
            @keydown="onTrackKey($event, ti)"
            @click="openCell(activeCell)"
          >
            <span
              v-for="(cell, ci) in track.cells"
              :key="ci"
              class="nf-band-cell relative flex-1 min-w-0 h-full"
              :class="
                cursor && cursor.track === ti && cursor.cell === ci ? 'bg-plate-fg/[0.14]' : ''
              "
              :style="{ '--nf-i': ci }"
              aria-hidden="true"
            >
              <!-- Blocks in this slice, against the track's busiest slice. -->
              <span
                v-if="cell.carved > 0"
                class="absolute inset-x-0 bottom-0 bg-primary-700"
                :style="{ height: `${barHeight(cell, track) * 100}%` }"
              >
                <!-- In use, as a share of those blocks' capacity. -->
                <span
                  v-if="usedHeight(cell) > 0"
                  class="absolute inset-x-0 bottom-0 bg-primary-400"
                  :style="{ height: `${usedHeight(cell) * 100}%` }"
                />
              </span>
            </span>
          </div>

          <!-- Axis. Three real addresses — the band is useless if you can't tell
               where in the space you are pointing. -->
          <div
            class="flex justify-between mt-1.5 font-mono text-[0.625rem] text-plate-fg-muted tabular-nums"
          >
            <span>{{ intToIp(track.startInt) }}</span>
            <span class="hidden sm:inline">
              {{ intToIp(track.startInt + Math.floor((track.endInt - track.startInt) / 2)) }}
            </span>
            <span>{{ intToIp(track.endInt) }}</span>
          </div>
        </div>
      </div>

      <!-- The readout. Fixed position, fixed height, never empty: with no cursor
           it reports the whole estate. -->
      <div
        class="mt-4 -mx-4 sm:-mx-6 px-4 sm:px-6 py-2.5 border-t border-plate-border min-h-[2.75rem] flex items-center"
        aria-live="polite"
      >
        <p v-if="activeCell" class="flex flex-wrap items-baseline gap-x-3 gap-y-1 text-base">
          <span class="font-mono text-plate-fg tabular-nums">
            {{ intToIp(activeCell.startInt) }} – {{ intToIp(activeCell.endInt) }}
          </span>
          <template v-if="activeCell.carved > 0">
            <span class="text-plate-fg-muted">
              {{ [...new Set(activeCell.cidrs)].slice(0, 3).join('  ') }}
              <template v-if="new Set(activeCell.cidrs).size > 3">
                +{{ new Set(activeCell.cidrs).size - 3 }}
              </template>
            </span>
            <span class="font-mono text-primary-300 tabular-nums">
              {{ formatNumber(Math.round(activeCell.used)) }} /
              {{ formatNumber(Math.round(activeCell.usable)) }} IP
            </span>
          </template>
          <span v-else class="nf-legend text-plate-fg-muted">
            {{ t('dashboard.band.cellFree') }}
          </span>
        </p>
        <p v-else class="flex flex-wrap items-baseline gap-x-3 gap-y-1 text-base">
          <span class="text-plate-fg-muted">
            {{ t('dashboard.band.summary', { n: totals.count }) }}
          </span>
          <span class="font-mono text-plate-fg tabular-nums">
            {{ formatNumber(totals.used) }} / {{ formatNumber(totals.usable) }} IP
          </span>
          <span v-if="truncated" class="nf-legend text-warning">
            {{ t('dashboard.band.truncated', { n: subnets.length, total }) }}
          </span>
        </p>
      </div>
    </template>
  </section>
</template>

<style scoped>
/* The orchestrated moment: the band draws itself left to right on load, like a
   sweep across a display. 128 cells at 2.5 ms apart is a ~320 ms pass, and the
   dashboard's sections rise underneath it over roughly the same window — one
   sequence rather than two competing ones.

   `transform` and `opacity` only, so it stays on the compositor. */
.nf-band-cell {
  transform-origin: bottom;
  animation: nf-band-sweep 200ms cubic-bezier(0.2, 0.9, 0.25, 1) backwards;
  animation-delay: calc(var(--nf-i) * 2.5ms);
  /* The crosshair column. Short enough to feel attached to the pointer, long
     enough that scrubbing across 128 slices doesn't strobe. */
  transition: background-color 90ms cubic-bezier(0.2, 0.9, 0.25, 1);
}

@keyframes nf-band-sweep {
  from {
    transform: scaleY(0.04);
    opacity: 0;
  }
  to {
    transform: scaleY(1);
    opacity: 1;
  }
}

/* The global reduce rule in tailwind.css can't name a scoped class, so the
   opt-out is declared here alongside the animation it disables. */
@media (prefers-reduced-motion: reduce) {
  .nf-band-cell {
    animation: none;
    transition: none;
  }
}
</style>

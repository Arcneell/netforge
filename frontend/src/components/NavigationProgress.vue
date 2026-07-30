<script setup lang="ts">
/**
 * Thin accent bar across the top while a route navigation is in flight.
 *
 * Prefetching (`composables/useRoutePrefetch.ts`) is what actually removes the
 * wait; this is the honesty backstop for the cases it cannot cover — a deep link
 * typed into the address bar, a route reached from somewhere with no hover, a
 * cold chunk on a slow link. Vue Router holds the old page on screen until the
 * lazy import resolves, so without this those cases look like a dead click.
 *
 * Only appears after `SHOW_AFTER_MS`. A warm navigation completes in a few
 * milliseconds, and flashing a progress bar on every one of those would read as
 * jitter — worse than showing nothing. The threshold is set just above the point
 * where a delay stops feeling instant and starts feeling like a wait.
 */
import { onMounted, onUnmounted, ref } from 'vue'
import { useRouter } from 'vue-router'

const SHOW_AFTER_MS = 120

const router = useRouter()
const visible = ref(false)
let timer: number | undefined
const teardown: Array<() => void> = []

function begin() {
  window.clearTimeout(timer)
  timer = window.setTimeout(() => {
    visible.value = true
  }, SHOW_AFTER_MS)
}

function end() {
  window.clearTimeout(timer)
  timer = undefined
  visible.value = false
}

onMounted(() => {
  // `afterEach` fires on completed *and* aborted navigations, and `onError`
  // covers a failed chunk fetch. Between them the bar cannot get stuck on:
  // every path out of a navigation clears it.
  teardown.push(
    router.beforeEach(() => {
      begin()
      return true
    }),
  )
  teardown.push(router.afterEach(end))
  teardown.push(router.onError(end))
})

onUnmounted(() => {
  window.clearTimeout(timer)
  teardown.forEach((remove) => remove())
})
</script>

<template>
  <Transition
    enter-active-class="transition-opacity duration-100"
    enter-from-class="opacity-0"
    leave-active-class="transition-opacity duration-150"
    leave-to-class="opacity-0"
  >
    <div
      v-if="visible"
      class="fixed top-0 left-0 right-0 z-50 h-[2px] overflow-hidden pointer-events-none"
      role="status"
      aria-live="polite"
      :aria-label="$t('common.loading')"
    >
      <div class="nav-progress-bar h-full w-1/3 bg-primary-400" />
    </div>
  </Transition>
</template>

<style scoped>
/* Indeterminate: the chunk gives no progress events, so a bar that pretended to
   know a percentage would be making it up. This just shows work in flight. */
@keyframes nav-progress-slide {
  0% {
    transform: translateX(-100%);
  }
  100% {
    transform: translateX(400%);
  }
}

.nav-progress-bar {
  animation: nav-progress-slide 1.1s ease-in-out infinite;
}

@media (prefers-reduced-motion: reduce) {
  .nav-progress-bar {
    animation: none;
    width: 100%;
    opacity: 0.7;
  }
}
</style>

<script setup lang="ts">
import { ref } from 'vue'
import { RouterView } from 'vue-router'
import AppSidebar from '@/components/AppSidebar.vue'
import AppTopbar from '@/components/AppTopbar.vue'
import ToastContainer from '@/components/ui/Toast.vue'
import GlobalSearch from '@/components/GlobalSearch.vue'
import KeyboardShortcutsHelp from '@/components/KeyboardShortcutsHelp.vue'
import { useGlobalShortcuts } from '@/composables/useShortcuts'

const searchOpen = ref(false)
const helpOpen = ref(false)

useGlobalShortcuts({
  onSearch: () => (searchOpen.value = true),
  onHelp: () => (helpOpen.value = true),
})
</script>

<template>
  <div class="flex h-full bg-bg text-fg">
    <AppSidebar />
    <div class="flex-1 flex flex-col min-w-0">
      <AppTopbar @open-search="searchOpen = true" />
      <main class="flex-1 overflow-y-auto">
        <!-- Leaving is a quick fade; arriving is handled by `.nf-stagger` on
             each page root, which sequences the page's own sections. Doing
             both here would stack two animations on the same frames. -->
        <RouterView v-slot="{ Component }">
          <Transition
            mode="out-in"
            leave-active-class="transition-opacity duration-75 ease-soft"
            leave-from-class="opacity-100"
            leave-to-class="opacity-0"
          >
            <component :is="Component" />
          </Transition>
        </RouterView>
      </main>
    </div>
    <GlobalSearch :open="searchOpen" @close="searchOpen = false" />
    <KeyboardShortcutsHelp :open="helpOpen" @close="helpOpen = false" />
    <ToastContainer />
  </div>
</template>

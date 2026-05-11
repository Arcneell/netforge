<script setup lang="ts">
import { RouterView } from 'vue-router'
import AppSidebar from '@/components/AppSidebar.vue'
import AppTopbar from '@/components/AppTopbar.vue'
import ToastContainer from '@/components/ui/Toast.vue'
</script>

<template>
  <div class="flex h-full bg-bg text-fg">
    <AppSidebar />
    <div class="flex-1 flex flex-col min-w-0">
      <AppTopbar />
      <main class="flex-1 overflow-y-auto">
        <RouterView v-slot="{ Component }">
          <Transition
            mode="out-in"
            enter-active-class="transition duration-150 ease-out"
            enter-from-class="opacity-0 translate-y-1"
            enter-to-class="opacity-100 translate-y-0"
            leave-active-class="transition duration-75 ease-in"
            leave-from-class="opacity-100"
            leave-to-class="opacity-0"
          >
            <component :is="Component" />
          </Transition>
        </RouterView>
      </main>
    </div>
    <ToastContainer />
  </div>
</template>

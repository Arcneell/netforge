<script setup lang="ts">
import type { Component } from 'vue'
import { Inbox } from 'lucide-vue-next'

withDefaults(
  defineProps<{
    icon?: Component
    title: string
    description?: string
    size?: 'sm' | 'md'
  }>(),
  { icon: Inbox, description: undefined, size: 'md' },
)
</script>

<template>
  <div
    :class="[
      'flex flex-col items-center justify-center text-center',
      size === 'sm' ? 'py-10 px-6' : 'py-16 px-6',
    ]"
  >
    <component
      :is="icon"
      :class="size === 'sm' ? 'w-5 h-5' : 'w-6 h-6'"
      class="text-fg-subtle mb-3"
      :stroke-width="1.75"
      aria-hidden="true"
    />
    <p :class="size === 'sm' ? 'text-base' : 'text-md'" class="font-medium text-fg">
      {{ title }}
    </p>
    <p v-if="description" class="text-base text-fg-muted max-w-sm mt-1.5">{{ description }}</p>
    <div v-if="$slots.action" class="mt-5">
      <slot name="action" />
    </div>
  </div>
</template>

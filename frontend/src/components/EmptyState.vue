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
  { icon: Inbox, size: 'md' },
)
</script>

<template>
  <div
    :class="[
      'flex flex-col items-center justify-center text-center text-fg-muted',
      size === 'sm' ? 'p-6 gap-2' : 'p-10 gap-3',
    ]"
  >
    <component :is="icon" :class="size === 'sm' ? 'w-6 h-6' : 'w-10 h-10'" aria-hidden="true" />
    <p :class="size === 'sm' ? 'text-sm' : 'text-base'" class="font-medium text-fg">{{ title }}</p>
    <p v-if="description" class="text-sm max-w-md">{{ description }}</p>
    <div v-if="$slots.action" class="mt-2">
      <slot name="action" />
    </div>
  </div>
</template>

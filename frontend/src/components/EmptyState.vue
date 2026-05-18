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
      size === 'sm' ? 'py-8 px-6 gap-2' : 'py-14 px-6 gap-3',
    ]"
  >
    <!-- Icon sits inside a soft tinted disc — iOS empty-state pattern.
         The disc adds visual weight without competing with the message. -->
    <div
      :class="[
        'inline-flex items-center justify-center rounded-full',
        'bg-primary-50 text-primary-500 dark:bg-primary-400/15 dark:text-primary-300',
        size === 'sm' ? 'w-10 h-10' : 'w-14 h-14',
      ]"
    >
      <component :is="icon" :class="size === 'sm' ? 'w-5 h-5' : 'w-7 h-7'" aria-hidden="true" />
    </div>
    <p
      :class="size === 'sm' ? 'text-sm' : 'text-base'"
      class="font-semibold text-fg tracking-tight mt-1"
    >
      {{ title }}
    </p>
    <p v-if="description" class="text-sm max-w-md leading-relaxed">{{ description }}</p>
    <div v-if="$slots.action" class="mt-3">
      <slot name="action" />
    </div>
  </div>
</template>

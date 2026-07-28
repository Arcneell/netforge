<script setup lang="ts">
import { useRouter } from 'vue-router'
import Button from '@/components/ui/Button.vue'

const router = useRouter()
</script>

<template>
  <div class="min-h-[70vh] flex items-center justify-center px-4">
    <div class="text-center max-w-md nf-enter">
      <p class="text-sm font-medium text-primary-600 dark:text-primary-400 tabular-nums">404</p>
      <h1 class="mt-2 text-2xl font-semibold tracking-[-0.02em]">
        {{ $t('errors.notFoundTitle') }}
      </h1>
      <p class="mt-2 text-base text-fg-muted">{{ $t('errors.notFoundBody') }}</p>
      <div class="mt-7">
        <Button variant="primary" @click="router.replace('/')">{{ $t('common.back') }}</Button>
      </div>
    </div>
  </div>
</template>

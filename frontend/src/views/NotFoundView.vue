<script setup lang="ts">
import { useRouter } from 'vue-router'
import Button from '@/components/ui/Button.vue'

const router = useRouter()
</script>

<template>
  <div class="min-h-[60vh] flex items-center justify-center px-4">
    <div class="text-center max-w-md">
      <p class="text-7xl font-bold text-primary-600 dark:text-primary-3000">404</p>
      <h1 class="mt-3 text-xl font-semibold">{{ $t('errors.notFoundTitle') }}</h1>
      <p class="mt-2 text-sm text-fg-muted">{{ $t('errors.notFoundBody') }}</p>
      <div class="mt-6">
        <Button variant="primary" @click="router.replace('/')">{{ $t('common.back') }}</Button>
      </div>
    </div>
  </div>
</template>

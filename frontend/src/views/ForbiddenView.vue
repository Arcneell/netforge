<script setup lang="ts">
import { useRouter } from 'vue-router'
import { ShieldAlert } from 'lucide-vue-next'
import Button from '@/components/ui/Button.vue'

const router = useRouter()
</script>

<template>
  <div class="min-h-[60vh] flex items-center justify-center px-4">
    <div class="text-center max-w-md">
      <ShieldAlert class="w-12 h-12 text-warning mx-auto" aria-hidden="true" />
      <h1 class="mt-4 text-xl font-semibold">{{ $t('errors.forbiddenTitle') }}</h1>
      <p class="mt-2 text-sm text-fg-muted">{{ $t('errors.forbiddenBody') }}</p>
      <div class="mt-6">
        <Button variant="primary" @click="router.replace('/')">{{ $t('common.back') }}</Button>
      </div>
    </div>
  </div>
</template>

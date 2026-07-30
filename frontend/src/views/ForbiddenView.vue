<script setup lang="ts">
import { useRouter } from 'vue-router'
import { ShieldAlert } from '@lucide/vue'
import Button from '@/components/ui/Button.vue'

const router = useRouter()
</script>

<template>
  <div class="min-h-[70vh] flex items-center justify-center px-4">
    <div class="text-center max-w-md nf-enter">
      <span
        class="inline-flex items-center justify-center w-11 h-11 rounded-full bg-warning/10 text-warning"
      >
        <ShieldAlert class="w-5 h-5" :stroke-width="1.9" aria-hidden="true" />
      </span>
      <h1 class="mt-5 text-2xl font-semibold tracking-[-0.02em]">
        {{ $t('errors.forbiddenTitle') }}
      </h1>
      <p class="mt-2 text-base text-fg-muted">{{ $t('errors.forbiddenBody') }}</p>
      <div class="mt-7">
        <Button variant="primary" @click="router.replace('/')">{{ $t('common.back') }}</Button>
      </div>
    </div>
  </div>
</template>

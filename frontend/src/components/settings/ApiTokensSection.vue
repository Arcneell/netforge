<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { Copy, Plus, Trash2, CheckCircle2 } from 'lucide-vue-next'
import Button from '@/components/ui/Button.vue'
import Input from '@/components/ui/Input.vue'
import Modal from '@/components/ui/Modal.vue'
import FormField from '@/components/ui/FormField.vue'
import DataTable, { type DataTableColumn } from '@/components/DataTable.vue'
import ConfirmDialog from '@/components/ConfirmDialog.vue'
import { authApi } from '@/api'
import type { ApiToken, ApiTokenCreated } from '@/api'
import { useToast } from '@/composables/useToast'
import { useApiErrorMessage } from '@/composables/useApiErrorMessage'
import { formatDate } from '@/utils/formatters'

const { t } = useI18n()
const { success, error: toastError } = useToast()
const { describe } = useApiErrorMessage()

const tokens = ref<ApiToken[]>([])
const loading = ref(false)

const createOpen = ref(false)
const newName = ref('')
const creating = ref(false)
const createError = ref<string | null>(null)

// Holds the plaintext we got back from POST. We surface it in a "copy-once"
// banner; after the user closes the modal it's wiped from memory because we
// never want to keep it around (no localStorage, no re-display).
const justCreated = ref<ApiTokenCreated | null>(null)
const copied = ref(false)

const tokenToRevoke = ref<ApiToken | null>(null)
const revoking = ref(false)

const columns: DataTableColumn[] = [
  { key: 'name', label: t('apiTokens.fields.name'), cellClass: 'font-medium' },
  { key: 'prefix', label: t('apiTokens.fields.prefix'), cellClass: 'font-mono w-32' },
  { key: 'created_at', label: t('apiTokens.fields.created'), cellClass: 'w-44 whitespace-nowrap' },
  {
    key: 'last_used_at',
    label: t('apiTokens.fields.lastUsed'),
    cellClass: 'w-44 whitespace-nowrap',
  },
  { key: 'status', label: t('apiTokens.fields.status'), cellClass: 'w-32' },
  { key: 'actions', label: t('common.actions'), align: 'right', cellClass: 'w-20' },
]

async function load() {
  loading.value = true
  try {
    tokens.value = await authApi.listTokens()
  } catch (err) {
    toastError(describe(err))
  } finally {
    loading.value = false
  }
}

onMounted(load)

function openCreate() {
  newName.value = ''
  createError.value = null
  // Wipe a previous plaintext before opening — we never want two open tokens
  // visible at once. The user closing the previous create-result modal also
  // wipes it (see closePlaintextBanner).
  justCreated.value = null
  copied.value = false
  createOpen.value = true
}

async function submitCreate(e: Event) {
  e.preventDefault()
  if (creating.value) return
  if (!newName.value.trim()) {
    createError.value = t('common.validation.required')
    return
  }
  creating.value = true
  createError.value = null
  try {
    const result = await authApi.createToken({ name: newName.value.trim() })
    justCreated.value = result
    createOpen.value = false
    await load()
  } catch (err) {
    createError.value = describe(err)
  } finally {
    creating.value = false
  }
}

async function copyPlaintext() {
  if (!justCreated.value) return
  try {
    await navigator.clipboard.writeText(justCreated.value.token)
    copied.value = true
    success(t('apiTokens.copied'))
  } catch {
    toastError(t('apiTokens.copyFailed'))
  }
}

function closePlaintextBanner() {
  // Wiping the plaintext from memory is more security theatre than reality
  // (it's already been DOM-rendered and probably in network logs), but it
  // matches the "shown once" contract — once the user dismisses the banner
  // we don't surface the secret anywhere again.
  justCreated.value = null
  copied.value = false
}

async function confirmRevoke() {
  if (!tokenToRevoke.value) return
  revoking.value = true
  try {
    await authApi.revokeToken(tokenToRevoke.value.id)
    success(t('apiTokens.revokedToast'))
    tokenToRevoke.value = null
    await load()
  } catch (err) {
    toastError(describe(err))
  } finally {
    revoking.value = false
  }
}

function statusFor(token: ApiToken): { key: string; tone: string } {
  if (token.revoked_at) return { key: 'apiTokens.status.revoked', tone: 'text-danger' }
  if (token.expires_at && new Date(token.expires_at) < new Date())
    return { key: 'apiTokens.status.expired', tone: 'text-warning' }
  return { key: 'apiTokens.status.active', tone: 'text-success' }
}
</script>

<template>
  <section>
    <!-- Plaintext banner — visible right after a successful create -->
    <div
      v-if="justCreated"
      class="nf-card border-success/40 bg-success/5 p-4 mb-4 flex items-start gap-3"
      role="status"
    >
      <CheckCircle2 class="w-5 h-5 text-success flex-shrink-0 mt-0.5" aria-hidden="true" />
      <div class="min-w-0 flex-1">
        <p class="text-sm font-medium text-fg">{{ t('apiTokens.plaintextTitle') }}</p>
        <p class="text-xs text-fg-muted mt-0.5">{{ t('apiTokens.plaintextHint') }}</p>
        <div class="mt-2 flex items-center gap-2">
          <code
            class="flex-1 min-w-0 truncate font-mono text-xs px-2 py-1.5 rounded border border-border bg-surface"
          >
            {{ justCreated.token }}
          </code>
          <Button variant="secondary" size="sm" @click="copyPlaintext">
            <Copy class="w-4 h-4" aria-hidden="true" />
            {{ copied ? t('common.copied') : t('common.copy') }}
          </Button>
          <Button variant="ghost" size="sm" @click="closePlaintextBanner">
            {{ t('common.close') }}
          </Button>
        </div>
      </div>
    </div>

    <div class="flex items-start justify-between gap-3 mb-3">
      <p class="text-xs text-fg-muted max-w-2xl">{{ t('apiTokens.subtitle') }}</p>
      <Button variant="primary" @click="openCreate">
        <Plus class="w-4 h-4" aria-hidden="true" />
        {{ t('apiTokens.new') }}
      </Button>
    </div>

    <DataTable
      :columns="columns"
      :rows="tokens"
      :loading="loading"
      :empty-title="t('apiTokens.empty.title')"
      :empty-description="t('apiTokens.empty.description')"
    >
      <template #cell-created_at="{ row }">
        <span class="text-fg-muted">{{ formatDate(row.created_at) }}</span>
      </template>
      <template #cell-last_used_at="{ row }">
        <span class="text-fg-muted">
          {{ row.last_used_at ? formatDate(row.last_used_at) : '—' }}
        </span>
      </template>
      <template #cell-status="{ row }">
        <span :class="statusFor(row).tone">{{ t(statusFor(row).key) }}</span>
      </template>
      <template #cell-actions="{ row }">
        <div class="flex justify-end">
          <Button
            v-if="!row.revoked_at"
            variant="ghost"
            size="sm"
            :aria-label="t('apiTokens.revoke')"
            @click.stop="tokenToRevoke = row"
          >
            <Trash2 class="w-4 h-4 text-danger" aria-hidden="true" />
          </Button>
        </div>
      </template>
    </DataTable>

    <Modal :open="createOpen" :title="t('apiTokens.new')" size="md" @close="createOpen = false">
      <form class="flex flex-col gap-4" @submit="submitCreate">
        <FormField :label="t('apiTokens.fields.name')" :error="createError" required>
          <template #default="{ id, invalid }">
            <Input
              :id="id"
              v-model="newName"
              :invalid="invalid"
              :placeholder="t('apiTokens.namePlaceholder')"
              maxlength="100"
              autocomplete="off"
            />
          </template>
        </FormField>
        <p class="text-xs text-fg-muted -mt-2">{{ t('apiTokens.nameHint') }}</p>
      </form>
      <template #footer>
        <div class="flex justify-end gap-2">
          <Button variant="secondary" :disabled="creating" @click="createOpen = false">
            {{ t('common.cancel') }}
          </Button>
          <Button variant="primary" :loading="creating" @click="submitCreate">
            {{ t('apiTokens.generate') }}
          </Button>
        </div>
      </template>
    </Modal>

    <ConfirmDialog
      :open="!!tokenToRevoke"
      :title="t('apiTokens.confirmRevokeTitle', { name: tokenToRevoke?.name ?? '' })"
      :message="t('apiTokens.confirmRevokeMessage')"
      variant="danger"
      :loading="revoking"
      @confirm="confirmRevoke"
      @cancel="tokenToRevoke = null"
    />
  </section>
</template>

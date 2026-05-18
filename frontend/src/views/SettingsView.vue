<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { Plus, Pencil, Trash2 } from 'lucide-vue-next'
import PageHeader from '@/components/PageHeader.vue'
import DataTable, { type DataTableColumn } from '@/components/DataTable.vue'
import Button from '@/components/ui/Button.vue'
import SiteEditor from '@/components/editors/SiteEditor.vue'
import RoomEditor from '@/components/editors/RoomEditor.vue'
import ApiTokensSection from '@/components/settings/ApiTokensSection.vue'
import ConfirmDialog from '@/components/ConfirmDialog.vue'
import { roomsApi, sitesApi } from '@/api'
import type { Room, Site } from '@/api'
import { useToast } from '@/composables/useToast'
import { useApiErrorMessage } from '@/composables/useApiErrorMessage'

const { t } = useI18n()
const { success } = useToast()
const { describe } = useApiErrorMessage()

const tab = ref<'sites' | 'rooms' | 'tokens'>('sites')

// --- Sites ---
const sites = ref<Site[]>([])
const sitesLoading = ref(false)
const siteEditorOpen = ref(false)
const editingSite = ref<Site | null>(null)
const siteToDelete = ref<Site | null>(null)
const deletingSite = ref(false)

async function loadSites() {
  sitesLoading.value = true
  try {
    const res = await sitesApi.list({ page_size: 200 })
    sites.value = res.items
  } finally {
    sitesLoading.value = false
  }
}

async function confirmDeleteSite() {
  if (!siteToDelete.value) return
  deletingSite.value = true
  try {
    await sitesApi.delete(siteToDelete.value.id)
    success(t('common.success'))
    siteToDelete.value = null
    loadSites()
  } catch (err) {
    void describe(err)
  } finally {
    deletingSite.value = false
  }
}

// --- Rooms ---
const rooms = ref<Room[]>([])
const sitesById = computed(() => new Map(sites.value.map((s) => [s.id, s])))
const roomsLoading = ref(false)
const roomEditorOpen = ref(false)
const editingRoom = ref<Room | null>(null)
const roomToDelete = ref<Room | null>(null)
const deletingRoom = ref(false)

async function loadRooms() {
  roomsLoading.value = true
  try {
    const res = await roomsApi.list({ page_size: 200 })
    rooms.value = res.items
  } finally {
    roomsLoading.value = false
  }
}

async function confirmDeleteRoom() {
  if (!roomToDelete.value) return
  deletingRoom.value = true
  try {
    await roomsApi.delete(roomToDelete.value.id)
    success(t('common.success'))
    roomToDelete.value = null
    loadRooms()
  } catch (err) {
    void describe(err)
  } finally {
    deletingRoom.value = false
  }
}

onMounted(async () => {
  // Load sites first so the Rooms tab can resolve site codes when it opens.
  await loadSites()
  loadRooms()
})

// Inlined @click="a; b" expressions trip the Vue template parser on Windows
// once Prettier reflows them onto separate lines — keep the open-modal logic
// in named handlers for readability and a stable parse tree.
function openNewSite() {
  editingSite.value = null
  siteEditorOpen.value = true
}
function openEditSite(row: Site) {
  editingSite.value = row
  siteEditorOpen.value = true
}
function openNewRoom() {
  editingRoom.value = null
  roomEditorOpen.value = true
}
function openEditRoom(row: Room) {
  editingRoom.value = row
  roomEditorOpen.value = true
}

const siteColumns: DataTableColumn[] = [
  { key: 'code', label: t('site.fields.code'), cellClass: 'font-mono w-40' },
  { key: 'name', label: t('site.fields.name'), cellClass: 'font-medium' },
  { key: 'address', label: t('site.fields.address'), hideOnSm: true },
  { key: 'actions', label: t('common.actions'), align: 'right', cellClass: 'w-32' },
]

const roomColumns: DataTableColumn[] = [
  { key: 'site_id', label: t('room.fields.site'), cellClass: 'w-40' },
  { key: 'code', label: t('room.fields.code'), cellClass: 'font-mono' },
  { key: 'description', label: t('room.fields.description'), hideOnSm: true },
  { key: 'actions', label: t('common.actions'), align: 'right', cellClass: 'w-32' },
]
</script>

<template>
  <div class="p-4 sm:p-6 max-w-7xl mx-auto">
    <PageHeader :title="t('nav.settings')" :subtitle="t('settings.subtitle')" />

    <div
      class="inline-flex items-center gap-0.5 p-0.5 rounded-md border border-border bg-surface mb-4"
      role="tablist"
    >
      <button
        type="button"
        role="tab"
        :aria-selected="tab === 'sites'"
        :class="[
          'px-3 h-8 rounded text-sm font-medium transition',
          tab === 'sites'
            ? 'bg-primary-100 text-primary-700 dark:bg-primary-900/40 dark:text-primary-300'
            : 'text-fg-muted hover:bg-surface-hover hover:text-fg',
        ]"
        @click="tab = 'sites'"
      >
        {{ t('settings.sitesTab') }}
      </button>
      <button
        type="button"
        role="tab"
        :aria-selected="tab === 'rooms'"
        :class="[
          'px-3 h-8 rounded text-sm font-medium transition',
          tab === 'rooms'
            ? 'bg-primary-100 text-primary-700 dark:bg-primary-900/40 dark:text-primary-300'
            : 'text-fg-muted hover:bg-surface-hover hover:text-fg',
        ]"
        @click="tab = 'rooms'"
      >
        {{ t('settings.roomsTab') }}
      </button>
      <button
        type="button"
        role="tab"
        :aria-selected="tab === 'tokens'"
        :class="[
          'px-3 h-8 rounded text-sm font-medium transition',
          tab === 'tokens'
            ? 'bg-primary-100 text-primary-700 dark:bg-primary-900/40 dark:text-primary-300'
            : 'text-fg-muted hover:bg-surface-hover hover:text-fg',
        ]"
        @click="tab = 'tokens'"
      >
        {{ t('settings.tokensTab') }}
      </button>
    </div>

    <!-- Sites tab -->
    <section v-if="tab === 'sites'">
      <div class="flex justify-end mb-3">
        <Button variant="primary" @click="openNewSite">
          <Plus class="w-4 h-4" aria-hidden="true" />
          {{ t('site.new') }}
        </Button>
      </div>
      <DataTable
        :columns="siteColumns"
        :rows="sites"
        :loading="sitesLoading"
        :empty-title="t('site.labelPlural')"
        :empty-description="t('site.empty')"
      >
        <template #cell-address="{ row }">
          <span class="text-fg-muted">{{ row.address || '—' }}</span>
        </template>
        <template #cell-actions="{ row }">
          <div class="flex justify-end gap-1">
            <Button
              variant="ghost"
              size="sm"
              :aria-label="t('common.edit')"
              @click.stop="openEditSite(row)"
            >
              <Pencil class="w-4 h-4" aria-hidden="true" />
            </Button>
            <Button
              variant="ghost"
              size="sm"
              :aria-label="t('common.delete')"
              @click.stop="siteToDelete = row"
            >
              <Trash2 class="w-4 h-4 text-danger" aria-hidden="true" />
            </Button>
          </div>
        </template>
      </DataTable>
    </section>

    <!-- Tokens tab -->
    <ApiTokensSection v-else-if="tab === 'tokens'" />

    <!-- Rooms tab -->
    <section v-else>
      <div class="flex justify-end mb-3">
        <Button variant="primary" @click="openNewRoom">
          <Plus class="w-4 h-4" aria-hidden="true" />
          {{ t('room.new') }}
        </Button>
      </div>
      <DataTable
        :columns="roomColumns"
        :rows="rooms"
        :loading="roomsLoading"
        :empty-title="t('room.labelPlural')"
        :empty-description="t('room.empty')"
      >
        <template #cell-site_id="{ row }">
          <span class="font-mono text-xs">
            {{ sitesById.get(row.site_id)?.code ?? `#${row.site_id}` }}
          </span>
        </template>
        <template #cell-description="{ row }">
          <span class="text-fg-muted">{{ row.description || '—' }}</span>
        </template>
        <template #cell-actions="{ row }">
          <div class="flex justify-end gap-1">
            <Button
              variant="ghost"
              size="sm"
              :aria-label="t('common.edit')"
              @click.stop="openEditRoom(row)"
            >
              <Pencil class="w-4 h-4" aria-hidden="true" />
            </Button>
            <Button
              variant="ghost"
              size="sm"
              :aria-label="t('common.delete')"
              @click.stop="roomToDelete = row"
            >
              <Trash2 class="w-4 h-4 text-danger" aria-hidden="true" />
            </Button>
          </div>
        </template>
      </DataTable>
    </section>

    <SiteEditor
      :open="siteEditorOpen"
      :site="editingSite"
      @close="siteEditorOpen = false"
      @saved="loadSites"
    />
    <RoomEditor
      :open="roomEditorOpen"
      :room="editingRoom"
      @close="roomEditorOpen = false"
      @saved="loadRooms"
    />
    <ConfirmDialog
      :open="!!siteToDelete"
      :title="t('common.confirmDelete.title', { label: siteToDelete?.code ?? '' })"
      :message="t('common.confirmDelete.message')"
      variant="danger"
      :loading="deletingSite"
      @confirm="confirmDeleteSite"
      @cancel="siteToDelete = null"
    />
    <ConfirmDialog
      :open="!!roomToDelete"
      :title="t('common.confirmDelete.title', { label: roomToDelete?.code ?? '' })"
      :message="t('common.confirmDelete.message')"
      variant="danger"
      :loading="deletingRoom"
      @confirm="confirmDeleteRoom"
      @cancel="roomToDelete = null"
    />
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref, watch, type Component } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRoute } from 'vue-router'
import {
  Building2,
  DoorOpen,
  KeyRound,
  Network,
  Pencil,
  Plus,
  Sparkles,
  Trash2,
  Webhook as WebhookIcon,
} from '@lucide/vue'
import PageHeader from '@/components/PageHeader.vue'
import DataTable, { type DataTableColumn } from '@/components/DataTable.vue'
import Button from '@/components/ui/Button.vue'
import SiteEditor from '@/components/editors/SiteEditor.vue'
import RoomEditor from '@/components/editors/RoomEditor.vue'
import ApiTokensSection from '@/components/settings/ApiTokensSection.vue'
import AiSection from '@/components/settings/AiSection.vue'
import WebhooksSection from '@/components/settings/WebhooksSection.vue'
import VrfsSection from '@/components/settings/VrfsSection.vue'
import ConfirmDialog from '@/components/ConfirmDialog.vue'
import { fetchAllPages, roomsApi, sitesApi } from '@/api'
import type { Room, Site } from '@/api'
import { useToast } from '@/composables/useToast'
import { useApiErrorMessage } from '@/composables/useApiErrorMessage'
import { useRowHighlight } from '@/composables/useRowHighlight'

const { t } = useI18n()
const { success } = useToast()
const { notify } = useApiErrorMessage()
const route = useRoute()
// Scrolls to + rings the row named by `?highlight=<id>` — GlobalSearch has
// no dedicated site/room detail route, so a search result lands here with
// `?tab=sites&highlight=<id>` (or `rooms`) instead of just the bare list.
const { applyHighlight, rowClass } = useRowHighlight()

type SettingsTab = 'sites' | 'rooms' | 'tokens' | 'ai' | 'webhooks' | 'vrfs'

const VALID_TABS: SettingsTab[] = ['sites', 'rooms', 'tokens', 'ai', 'webhooks', 'vrfs']

function initialTab(): SettingsTab {
  const q = route.query.tab
  return typeof q === 'string' && (VALID_TABS as string[]).includes(q)
    ? (q as SettingsTab)
    : 'sites'
}

const tab = ref<SettingsTab>(initialTab())

// A search result clicked while ALREADY on the settings page only changes
// the query string — the component doesn't remount, so `initialTab()` never
// reruns. Follow `?tab=` changes so the right tab opens in that case too
// (the highlight itself is re-applied by useRowHighlight's own watcher).
watch(
  () => route.query.tab,
  (value) => {
    if (typeof value === 'string' && (VALID_TABS as string[]).includes(value)) {
      tab.value = value as SettingsTab
    }
  },
)

// Six sections is past the point where a pill group reads as a control rather
// than navigation — an underlined tab bar (the same `.nf-tab` the workspaces
// use) keeps them legible and scannable in one row.
const tabs = computed<{ value: SettingsTab; label: string; icon: Component }[]>(() => [
  { value: 'sites', label: t('settings.sitesTab'), icon: Building2 },
  { value: 'rooms', label: t('settings.roomsTab'), icon: DoorOpen },
  { value: 'tokens', label: t('settings.tokensTab'), icon: KeyRound },
  { value: 'ai', label: t('settings.aiTab'), icon: Sparkles },
  { value: 'webhooks', label: t('settings.webhooksTab'), icon: WebhookIcon },
  { value: 'vrfs', label: t('settings.vrfsTab'), icon: Network },
])

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
    sites.value = await fetchAllPages((p) => sitesApi.list(p))
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
    notify(err)
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
    rooms.value = await fetchAllPages((p) => roomsApi.list(p))
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
    notify(err)
  } finally {
    deletingRoom.value = false
  }
}

onMounted(async () => {
  // Load sites first so the Rooms tab can resolve site codes when it opens.
  await loadSites()
  await loadRooms()
  // Whichever tab `?tab=` selected is now populated — safe to scroll/ring.
  await applyHighlight()
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

const siteColumns = computed<DataTableColumn[]>(() => [
  { key: 'code', label: t('site.fields.code'), cellClass: 'font-mono w-40' },
  { key: 'name', label: t('site.fields.name'), cellClass: 'font-medium' },
  { key: 'address', label: t('site.fields.address'), hideOnSm: true },
  { key: 'actions', label: t('common.actions'), align: 'right', cellClass: 'w-32' },
])

const roomColumns = computed<DataTableColumn[]>(() => [
  { key: 'site_id', label: t('room.fields.site'), cellClass: 'w-40' },
  { key: 'code', label: t('room.fields.code'), cellClass: 'font-mono' },
  { key: 'description', label: t('room.fields.description'), hideOnSm: true },
  { key: 'actions', label: t('common.actions'), align: 'right', cellClass: 'w-32' },
])
</script>

<template>
  <div class="px-4 py-8 sm:px-8 max-w-[1400px] mx-auto nf-stagger">
    <PageHeader :title="t('nav.settings')" :subtitle="t('settings.subtitle')" />

    <!-- Section navigation. Underlined tabs, one row, horizontally scrollable
         on narrow viewports so the bar never wraps into two lines. -->
    <div class="border-b border-border mb-6">
      <div
        class="flex items-center gap-6 overflow-x-auto"
        role="tablist"
        :aria-label="t('settings.tabsLabel')"
      >
        <button
          v-for="s in tabs"
          :id="`settings-tab-${s.value}`"
          :key="s.value"
          type="button"
          role="tab"
          :aria-selected="tab === s.value"
          :aria-controls="`settings-panel-${s.value}`"
          :class="['nf-tab', tab === s.value ? 'nf-tab-active' : '']"
          @click="tab = s.value"
        >
          <component :is="s.icon" class="w-4 h-4" :stroke-width="1.9" aria-hidden="true" />
          {{ s.label }}
        </button>
      </div>
    </div>

    <!-- Sites -->
    <section
      v-if="tab === 'sites'"
      id="settings-panel-sites"
      role="tabpanel"
      aria-labelledby="settings-tab-sites"
    >
      <div class="nf-toolbar items-start justify-between">
        <div class="min-w-0">
          <h2 class="nf-section-title">{{ t('settings.sitesTab') }}</h2>
          <p class="text-sm text-fg-muted mt-1 max-w-2xl">{{ t('settings.sitesDescription') }}</p>
        </div>
        <Button variant="primary" @click="openNewSite">
          <Plus class="w-4 h-4" aria-hidden="true" />
          {{ t('site.new') }}
        </Button>
      </div>

      <DataTable
        :columns="siteColumns"
        :rows="sites"
        :loading="sitesLoading"
        :empty-title="t('site.emptyTitle')"
        :empty-description="t('site.empty')"
        :row-class="rowClass"
      >
        <template #empty-action>
          <Button variant="primary" @click="openNewSite">
            <Plus class="w-4 h-4" aria-hidden="true" />
            {{ t('site.new') }}
          </Button>
        </template>
        <template #cell-address="{ row }">
          <span class="text-fg-muted">{{ row.address || '—' }}</span>
        </template>
        <template #cell-actions="{ row }">
          <div class="flex items-center justify-end gap-1">
            <Button
              variant="ghost"
              size="sm"
              :aria-label="`${t('common.edit')} ${row.code}`"
              :title="t('common.edit')"
              @click.stop="openEditSite(row)"
            >
              <Pencil class="w-4 h-4" aria-hidden="true" />
            </Button>
            <!-- Hairline before the destructive action so it is never the
                 button you hit by momentum after Edit. -->
            <span class="w-px h-5 bg-border" aria-hidden="true" />
            <Button
              variant="ghost"
              size="sm"
              :aria-label="`${t('common.delete')} ${row.code}`"
              :title="t('common.delete')"
              @click.stop="siteToDelete = row"
            >
              <Trash2 class="w-4 h-4 text-danger" aria-hidden="true" />
            </Button>
          </div>
        </template>
      </DataTable>
    </section>

    <!-- Rooms -->
    <section
      v-else-if="tab === 'rooms'"
      id="settings-panel-rooms"
      role="tabpanel"
      aria-labelledby="settings-tab-rooms"
    >
      <div class="nf-toolbar items-start justify-between">
        <div class="min-w-0">
          <h2 class="nf-section-title">{{ t('settings.roomsTab') }}</h2>
          <p class="text-sm text-fg-muted mt-1 max-w-2xl">{{ t('settings.roomsDescription') }}</p>
        </div>
        <Button variant="primary" @click="openNewRoom">
          <Plus class="w-4 h-4" aria-hidden="true" />
          {{ t('room.new') }}
        </Button>
      </div>

      <DataTable
        :columns="roomColumns"
        :rows="rooms"
        :loading="roomsLoading"
        :empty-title="t('room.emptyTitle')"
        :empty-description="t('room.emptyHint')"
        :row-class="rowClass"
      >
        <template #empty-action>
          <Button variant="primary" @click="openNewRoom">
            <Plus class="w-4 h-4" aria-hidden="true" />
            {{ t('room.new') }}
          </Button>
        </template>
        <template #cell-site_id="{ row }">
          <span class="font-mono text-xs">
            {{ sitesById.get(row.site_id)?.code ?? `#${row.site_id}` }}
          </span>
        </template>
        <template #cell-description="{ row }">
          <span class="text-fg-muted">{{ row.description || '—' }}</span>
        </template>
        <template #cell-actions="{ row }">
          <div class="flex items-center justify-end gap-1">
            <Button
              variant="ghost"
              size="sm"
              :aria-label="`${t('common.edit')} ${row.code}`"
              :title="t('common.edit')"
              @click.stop="openEditRoom(row)"
            >
              <Pencil class="w-4 h-4" aria-hidden="true" />
            </Button>
            <span class="w-px h-5 bg-border" aria-hidden="true" />
            <Button
              variant="ghost"
              size="sm"
              :aria-label="`${t('common.delete')} ${row.code}`"
              :title="t('common.delete')"
              @click.stop="roomToDelete = row"
            >
              <Trash2 class="w-4 h-4 text-danger" aria-hidden="true" />
            </Button>
          </div>
        </template>
      </DataTable>
    </section>

    <!-- API tokens -->
    <ApiTokensSection
      v-else-if="tab === 'tokens'"
      id="settings-panel-tokens"
      role="tabpanel"
      aria-labelledby="settings-tab-tokens"
    />

    <!-- AI -->
    <AiSection
      v-else-if="tab === 'ai'"
      id="settings-panel-ai"
      role="tabpanel"
      aria-labelledby="settings-tab-ai"
    />

    <!-- Webhooks -->
    <WebhooksSection
      v-else-if="tab === 'webhooks'"
      id="settings-panel-webhooks"
      role="tabpanel"
      aria-labelledby="settings-tab-webhooks"
    />

    <!-- VRFs -->
    <VrfsSection
      v-else
      id="settings-panel-vrfs"
      role="tabpanel"
      aria-labelledby="settings-tab-vrfs"
    />

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
      :confirm-label="t('common.delete')"
      variant="danger"
      :loading="deletingSite"
      @confirm="confirmDeleteSite"
      @cancel="siteToDelete = null"
    />
    <ConfirmDialog
      :open="!!roomToDelete"
      :title="t('common.confirmDelete.title', { label: roomToDelete?.code ?? '' })"
      :message="t('common.confirmDelete.message')"
      :confirm-label="t('common.delete')"
      variant="danger"
      :loading="deletingRoom"
      @confirm="confirmDeleteRoom"
      @cancel="roomToDelete = null"
    />
  </div>
</template>

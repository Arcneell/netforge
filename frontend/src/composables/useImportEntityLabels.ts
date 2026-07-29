import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { IMPORT_ENTITIES, type ImportEntity } from '@/api'
import type { SelectOption } from '@/components/ui/Select.vue'

/**
 * Recommended import order — sites first, links last. IPs come BEFORE ports
 * because `_persist_port` resolves `connected_ip` via the Ip table and errors
 * out if the IP doesn't exist yet; round-tripping a CSV with port→IP
 * associations on a fresh restore requires this ordering.
 */
export const ORDERED_IMPORT_ENTITIES: ImportEntity[] = [
  'sites',
  'rooms',
  'vlans',
  'subnets',
  'devices',
  'switches',
  'ips',
  'ports',
  'links',
]

/** Locale key that names each importable entity (plural form). */
export const IMPORT_ENTITY_LABEL_KEYS: Record<ImportEntity, string> = {
  sites: 'site.labelPlural',
  rooms: 'room.labelPlural',
  vlans: 'vlan.labelPlural',
  subnets: 'subnet.labelPlural',
  ips: 'ip.labelPlural',
  devices: 'device.labelPlural',
  switches: 'switch.labelPlural',
  ports: 'port.labelPlural',
  links: 'nav.topology', // closest existing key — links aren't a top-level nav item
}

/**
 * Translated names for the CSV import entities. Shared by the import panels
 * and the per-file report rows so a given entity always reads the same.
 */
export function useImportEntityLabels() {
  const { t } = useI18n()

  const entityOptions = computed<SelectOption<ImportEntity>[]>(() =>
    IMPORT_ENTITIES.map((e) => ({ value: e, label: t(IMPORT_ENTITY_LABEL_KEYS[e]) })),
  )

  function entityLabel(e: ImportEntity): string {
    return t(IMPORT_ENTITY_LABEL_KEYS[e])
  }

  /** Detection can come back empty — name that state instead of rendering "". */
  function entityLabelOrFallback(e: ImportEntity | null): string {
    if (e === null) return t('import.bulk.detected.unknown')
    return t(IMPORT_ENTITY_LABEL_KEYS[e])
  }

  return { entityOptions, entityLabel, entityLabelOrFallback }
}

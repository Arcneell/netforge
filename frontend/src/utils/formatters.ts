import { i18n } from '@/i18n'

/**
 * Locale-aware date formatter. We pass the i18n locale through to Intl rather
 * than reading navigator.language so it follows the user's in-app preference.
 */
export function formatDate(
  iso: string | null | undefined,
  opts?: Intl.DateTimeFormatOptions,
): string {
  if (!iso) return '—'
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return '—'
  return d.toLocaleString(
    i18n.global.locale.value,
    opts ?? { dateStyle: 'medium', timeStyle: 'short' },
  )
}

export function formatRelativeTime(iso: string | null | undefined): string {
  if (!iso) return '—'
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return '—'
  const deltaSec = (d.getTime() - Date.now()) / 1000
  const rtf = new Intl.RelativeTimeFormat(i18n.global.locale.value, { numeric: 'auto' })
  const absSec = Math.abs(deltaSec)
  // Pick the largest unit that yields a value ≥ 1; mirrors Twitter-style timestamps.
  if (absSec < 60) return rtf.format(Math.round(deltaSec), 'second')
  if (absSec < 3600) return rtf.format(Math.round(deltaSec / 60), 'minute')
  if (absSec < 86400) return rtf.format(Math.round(deltaSec / 3600), 'hour')
  if (absSec < 86400 * 30) return rtf.format(Math.round(deltaSec / 86400), 'day')
  if (absSec < 86400 * 365) return rtf.format(Math.round(deltaSec / (86400 * 30)), 'month')
  return rtf.format(Math.round(deltaSec / (86400 * 365)), 'year')
}

export function formatPercent(value: number, fractionDigits = 0): string {
  if (!Number.isFinite(value)) return '—'
  return new Intl.NumberFormat(i18n.global.locale.value, {
    style: 'percent',
    maximumFractionDigits: fractionDigits,
  }).format(value)
}

export function formatNumber(value: number): string {
  if (!Number.isFinite(value)) return '—'
  return new Intl.NumberFormat(i18n.global.locale.value).format(value)
}

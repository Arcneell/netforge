import { useI18n } from 'vue-i18n'
import { ApiError } from '@/api'
import { useToast } from '@/composables/useToast'

/**
 * Maps backend error codes to localized messages.
 *
 * Falls back to the backend-provided message (which is already in plain
 * English) when the code is unknown to the frontend — better than showing
 * the raw code to the user.
 */
export function useApiErrorMessage() {
  const { t, te } = useI18n()
  const toast = useToast()

  function describe(err: unknown): string {
    if (err instanceof ApiError) {
      const key = `errorCodes.${err.code}`
      if (te(key)) return t(key)
      return err.message
    }
    if (err instanceof Error) return err.message
    return t('errors.unknown')
  }

  /**
   * Describe the failure AND surface it.
   *
   * The axios interceptor in `api/client.ts` only calls back on network
   * failures, 401 and 403 — a 409 on delete or a 422 on save reaches the
   * caller with no user-visible signal at all. Call sites that have nowhere
   * to render an inline error (a row action, a background refresh) should
   * use this instead of discarding the string.
   */
  function notify(err: unknown): string {
    const message = describe(err)
    toast.error(message)
    return message
  }

  return { describe, notify }
}

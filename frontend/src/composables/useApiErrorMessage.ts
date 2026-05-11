import { useI18n } from 'vue-i18n'
import { ApiError } from '@/api'

/**
 * Maps backend error codes to localized messages.
 *
 * Falls back to the backend-provided message (which is already in plain
 * English) when the code is unknown to the frontend — better than showing
 * the raw code to the user.
 */
export function useApiErrorMessage() {
  const { t, te } = useI18n()

  function describe(err: unknown): string {
    if (err instanceof ApiError) {
      const key = `errorCodes.${err.code}`
      if (te(key)) return t(key)
      return err.message
    }
    if (err instanceof Error) return err.message
    return t('errors.unknown')
  }

  return { describe }
}

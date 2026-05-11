/// <reference types="vite/client" />

declare module '*.vue' {
  import type { DefineComponent } from 'vue'
  const component: DefineComponent<Record<string, never>, Record<string, never>, unknown>
  export default component
}

interface ImportMetaEnv {
  readonly VITE_BACKEND_URL?: string
  readonly VITE_AUTH_PROVIDER?: 'github' | 'oidc' | 'default'
  readonly VITE_APP_VERSION?: string
}

interface ImportMeta {
  readonly env: ImportMetaEnv
}

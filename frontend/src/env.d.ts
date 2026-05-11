/// <reference types="vite/client" />

declare module '*.vue' {
  import type { DefineComponent } from 'vue'
  const component: DefineComponent<Record<string, never>, Record<string, never>, unknown>
  export default component
}

interface ImportMetaEnv {
  readonly VITE_BACKEND_URL?: string
  readonly VITE_AUTH_PROVIDER?: 'github' | 'oidc' | 'dev' | 'default'
  readonly VITE_APP_VERSION?: string
}

interface ImportMeta {
  readonly env: ImportMetaEnv
}

// cytoscape-dagre ships no official types — declare just enough that
// `cytoscape.use(cytoscapeDagre)` type-checks. The layout itself is invoked
// via `{ name: 'dagre', ... }` and Cytoscape's loose layout typing handles it.
declare module 'cytoscape-dagre' {
  import type { Ext } from 'cytoscape'
  const extension: Ext
  export default extension
}

<script setup lang="ts">
import { useRouter } from 'vue-router'
import DOMPurify from 'dompurify'

/**
 * The rendered body of one chat bubble.
 *
 * SECURITY: this component owns the only `v-html` in the app. The chain is
 * escape → citation allow-list regex → DOMPurify with a restrictive
 * `ALLOWED_TAGS`, in that exact order. Do not reorder, shorten or "simplify"
 * it — every step is load-bearing.
 */
defineProps<{
  text: string
  role: 'user' | 'assistant'
}>()

const router = useRouter()

/**
 * Intercept clicks on inline citation links (`<a data-internal-link>`)
 * inside a v-html'd assistant bubble. Without this, the browser would
 * navigate via a full page reload — losing the conversation state.
 *
 * Modifier keys (Cmd/Ctrl/Shift/middle-click) fall through to the
 * default behaviour so "open in new tab" still works.
 */
function onInlineClick(e: MouseEvent): void {
  const anchor = (e.target as HTMLElement | null)?.closest?.('a[data-internal-link]')
  if (!(anchor instanceof HTMLAnchorElement)) return
  if (e.metaKey || e.ctrlKey || e.shiftKey || e.button !== 0) return
  e.preventDefault()
  const href = anchor.getAttribute('href') || ''
  if (href.startsWith('/')) void router.push(href)
}

/**
 * Tiny Markdown renderer — bold (**...**), inline code (`...`), and line
 * breaks. We deliberately avoid pulling marked / markdown-it in: the LLM's
 * output is constrained by the prompt to a narrow subset, the surface area
 * is small, and we don't want to ship a 20 KB parser for two formatting
 * features. HTML inside user-supplied text is escaped first; only the
 * recognised patterns are turned into markup.
 */
// Entity-citation token: `[[type:id|label]]` (label optional). The LLM
// emits these inline; we convert them to clickable <a> tags pointing
// at the matching IPAM page. Type set must stay in sync with the
// backend's QueryEntityRef enum (see services/ai/nl_query.py).
const _CITATION_RE = /\[\[(site|room|switch|port|vlan|subnet|device):(\d+)(?:\|([^\]]+))?\]\]/g

function _citationHref(type: string, id: string): string | null {
  switch (type) {
    case 'switch':
      return `/switches/${id}`
    case 'subnet':
      return `/subnets/${id}`
    case 'port':
      // No per-port page; route to the parent switch's detail. The id we
      // have is the port id, not the switch id — fall back to the
      // switches list. The bottom-chips already do this.
      return '/switches'
    case 'vlan':
      return '/vlans'
    case 'device':
      return '/devices'
    case 'site':
    case 'room':
      // No per-site/room page in the SPA today; surface the label
      // as plain text styled like a pill (no href).
      return null
    default:
      return null
  }
}

function _renderCitations(escaped: string): string {
  return escaped.replace(_CITATION_RE, (_match, type: string, id: string, label?: string) => {
    const text = (label || `${type} #${id}`).trim()
    const href = _citationHref(type, id)
    // Same visual language as the chip row under an answer: a bordered
    // pill. The clickable variant additionally underlines on hover so a
    // citation never reads as decoration.
    const base =
      'inline-flex items-center gap-1 px-1.5 py-0.5 rounded font-medium text-[0.92em] ' +
      'border border-primary-200 dark:border-primary-800 ' +
      'bg-primary-50 text-primary-700 dark:bg-primary-500/15 dark:text-primary-300'
    if (href) {
      return `<a href="${href}" data-internal-link="1" class="${base} cursor-pointer hover:border-primary-500 hover:underline underline-offset-2 transition-colors duration-150">${text}</a>`
    }
    return `<span class="${base}">${text}</span>`
  })
}

// Final allow-list for the sanitiser: exactly the tags/attributes
// renderMarkdown can legitimately produce. Anything else the LLM (or a
// future regression in the renderer) emits is stripped before it reaches
// v-html.
const _SANITIZE_CONFIG = {
  ALLOWED_TAGS: ['strong', 'code', 'br', 'a', 'span'],
  ALLOWED_ATTR: ['href', 'class', 'data-internal-link'],
}

function renderMarkdown(src: string): string {
  // Escape first, then re-introduce only the markup we recognise. The
  // citation pattern is applied AFTER escape so its angle brackets in
  // the produced HTML survive the user-content sanitisation.
  const esc = src.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
  const html = _renderCitations(esc)
    .replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>')
    .replace(
      /`([^`]+)`/g,
      '<code class="px-1 py-0.5 rounded bg-muted font-mono text-[0.85em]">$1</code>',
    )
    .replace(/\n/g, '<br>')
  // Defence in depth: even though we escape and only inject a known subset,
  // DOMPurify guarantees the string handed to v-html can never carry script,
  // event handlers, or any tag/attribute outside the allow-list above.
  return DOMPurify.sanitize(html, _SANITIZE_CONFIG)
}
</script>

<template>
  <!-- renderMarkdown escapes HTML before applying the bold/code/br
       transforms, so the input is safe even if the LLM returns
       raw markup. Inline citation tokens [[type:id|label]]
       become <a data-internal-link>; we intercept clicks on
       those at this wrapping div to route through Vue Router
       instead of triggering a full page reload. -->
  <!-- eslint-disable vue/no-v-html -->
  <div
    :class="[
      'text-base leading-relaxed max-w-[70ch] break-words',
      role === 'assistant' ? 'text-fg' : 'text-fg rounded-lg bg-muted px-3.5 py-2.5 inline-block',
    ]"
    @click="onInlineClick"
    v-html="renderMarkdown(text)"
  />
  <!-- eslint-enable vue/no-v-html -->
</template>

<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, reactive, ref } from 'vue'
import { RouterLink, useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import {
  AlertTriangle,
  ArrowRight,
  Bot,
  History,
  Network,
  Plus,
  Send,
  Server,
  Sparkles,
  Tags,
  Trash2,
  User as UserIcon,
  Router as RouterIcon,
} from 'lucide-vue-next'
import PageHeader from '@/components/PageHeader.vue'
import Button from '@/components/ui/Button.vue'
import HelpTooltip from '@/components/ui/HelpTooltip.vue'
import Modal from '@/components/ui/Modal.vue'
import EmptyState from '@/components/EmptyState.vue'
import {
  aiApi,
  type AIStatus,
  type Conversation,
  type QueryEntityRef,
  type QueryHistoryTurn,
} from '@/api'
import DOMPurify from 'dompurify'
import { useApiErrorMessage } from '@/composables/useApiErrorMessage'
import { useToast } from '@/composables/useToast'

const { t } = useI18n()
const { describe } = useApiErrorMessage()
const { error: toastError } = useToast()
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

interface Turn {
  id: number
  role: 'user' | 'assistant'
  text: string
  entities?: QueryEntityRef[]
  latency_ms?: number
}

const status = ref<AIStatus | null>(null)
const turns = ref<Turn[]>([])
const input = ref('')
const pending = ref(false)
// Per-stream cancellation token. Each `send()` call captures a fresh
// `{ v: false }` object in its closure and passes it into streamAnswer;
// the read loop checks the LOCAL flag. The module-level `activeReader`
// handle still satisfies the cancel-on-resubmit / cancel-on-unmount
// contract — when send() runs again we cancel the current reader (which
// also flips its own token to true so the OLD send's finally branch
// knows the stream was cancelled by us, not by the server, and skips
// the "empty answer" / "incomplete answer" fallback messages that
// would otherwise drop spurious bubbles into the chat).
interface CancelToken {
  v: boolean
}
let activeReader: ReadableStreamDefaultReader<Uint8Array> | null = null
let activeCancelToken: CancelToken | null = null
// Lite-context toggle: ask the backend to send a stripped snapshot
// (identifiers only — no vendor / model / serial / notes / descriptions /
// MACs / addresses). Cuts tokens ~10× and keeps free-text out of the
// outbound request, at the cost of any answer that needs free-text.
// Off by default — the verbose mode is the right default for a fresh
// session, and operators who care opt-in per session.
const liteContext = ref(false)
const transcriptRef = ref<HTMLDivElement | null>(null)
let nextId = 1

// --- Persistent conversation state --------------------------------------
//
// `activeConversationId` is the id of the thread currently displayed in
// the transcript. It is `null` for a brand-new (unsaved) chat — the first
// successful exchange triggers `ensureConversation()` to create one
// server-side and store the id here for subsequent appends. Loading an
// existing thread from the sidebar sets the id + replaces `turns`.
const activeConversationId = ref<number | null>(null)
const conversations = ref<Conversation[]>([])
const conversationsLoading = ref(false)
const conversationsError = ref<string | null>(null)
const historyOpen = ref(false)

async function loadStatus() {
  try {
    status.value = await aiApi.status()
  } catch {
    status.value = null
  }
}

// History capped to the last 10 turns to match the server-side schema cap.
// The newest user message is NOT part of the history we send — it goes in the
// `question` field, so we only need to forward the prior turns.
const HISTORY_CAP = 10

function historyForBackend(): QueryHistoryTurn[] {
  // Take the most recent turns up to the cap; preserve order.
  const previous = turns.value.slice(-HISTORY_CAP)
  return previous.map((t) => ({
    role: t.role,
    text: t.text,
  }))
}

function cancelActiveStream(): void {
  if (activeCancelToken) activeCancelToken.v = true
  if (activeReader) {
    try {
      void activeReader.cancel()
    } catch {
      // The reader can throw if the stream is already done — best-effort.
    }
    activeReader = null
  }
  activeCancelToken = null
}

onBeforeUnmount(cancelActiveStream)

async function send() {
  const question = input.value.trim()
  if (!question || pending.value) return
  // Cancel any earlier inflight stream (e.g., the operator hit Enter
  // again while a slow answer was still streaming). Without this the
  // two streams race and tokens interleave in the same assistant bubble.
  // The cancelled stream's own token is flipped to true so the old
  // send()'s finally branch can distinguish user-cancellation from
  // server-side stream-ended-prematurely.
  cancelActiveStream()
  const cancelToken: CancelToken = { v: false }
  activeCancelToken = cancelToken
  input.value = ''
  // Snapshot history BEFORE we push the new user turn so the server sees
  // exactly the prior exchange, not a copy of the question it's about to
  // answer.
  const history = historyForBackend()
  // Create the persistent conversation now (lazy first-prompt). The
  // server then uses its own copy of the history when it persists turns,
  // so the second call onward our local `history` is overridden — that's
  // fine because the persisted version is authoritative anyway.
  const conversationId = await ensureConversation()
  const userTurn: Turn = { id: nextId++, role: 'user', text: question }
  turns.value.push(userTurn)
  await scrollToBottom()

  pending.value = true
  // The assistant turn is created lazily on the FIRST delta so the existing
  // "thinking" indicator (three pulsing dots) stays visible until the
  // model actually starts emitting tokens. After that it's replaced by the
  // typed bubble, which grows in place.
  //
  // The turn MUST be wrapped in `reactive()` before we mutate its `text`
  // per-delta. Plain object refs pushed into `turns.value` are not the
  // same identity as the proxied element Vue returns from `turns.value[i]`,
  // so `obj.text += delta` would go straight to the raw target and skip
  // the reactivity system — only the first delta would render (because the
  // initial `push` + `pending = false` happened to trigger a re-render in
  // the same microtask). Wrapping in `reactive()` makes our local handle
  // the proxy itself, so every subsequent token append re-renders the
  // bubble. Regression for the "Cette infrastructure / et puis plus rien"
  // bug on Ask AI with fast providers (Gemini flash, Anthropic Haiku).
  let assistantTurn: Turn | null = null
  try {
    const outcome = await streamAnswer(
      question,
      history,
      cancelToken,
      conversationId,
      (delta, meta) => {
        if (!assistantTurn) {
          assistantTurn = reactive<Turn>({ id: nextId++, role: 'assistant', text: '' })
          turns.value.push(assistantTurn)
          pending.value = false
        }
        assistantTurn.text += delta
        if (meta?.latency_ms !== undefined) {
          assistantTurn.latency_ms = meta.latency_ms
        }
        // Keep the transcript pinned to the bottom while text streams in —
        // without this, long answers scroll off-screen and the operator has
        // to chase them by hand. Fire-and-forget the nextTick so we don't
        // block the next delta.
        void scrollToBottom()
      },
    )
    // TS's control-flow analysis narrows `assistantTurn` back to its
    // initial `null` after the await — it can't see the closure mutation.
    // Re-widen explicitly so the post-stream branches type-check.
    const settled = assistantTurn as Turn | null
    // Skip the empty/incomplete fallback bubbles when WE cancelled this
    // stream (the user re-submitted or navigated away). Otherwise the
    // user's brand-new question would be preceded by a spurious "no
    // answer" / "incomplete answer" bubble from the cancelled run.
    if (cancelToken.v) {
      // Drop the partial assistant turn we created — it's a torso
      // without a head, and the new stream is about to add a fresh one.
      if (settled) {
        const idx = turns.value.indexOf(settled)
        if (idx >= 0) turns.value.splice(idx, 1)
      }
    } else if (!settled) {
      // Stream completed with zero deltas — surface as a one-liner so the
      // operator doesn't sit on an empty chat.
      turns.value.push(
        reactive<Turn>({ id: nextId++, role: 'assistant', text: t('ai.askView.emptyAnswer') }),
      )
    } else if (!outcome.completed) {
      // We got deltas but the server never sent the `done` frame — most
      // commonly the model hit a non-STOP finish_reason (Gemini SAFETY,
      // OpenAI content_filter, Anthropic refusal). Append a marker so the
      // operator knows the bubble is partial, not the model's final word.
      settled.text += `\n\n${t('ai.askView.incompleteAnswer')}`
    }
  } catch (err) {
    if (!cancelToken.v) toastError(describe(err))
  } finally {
    if (activeCancelToken === cancelToken) activeCancelToken = null
    pending.value = false
    await scrollToBottom()
    // Refresh the sidebar so the active conversation moves to the top
    // and the title (derived server-side from the first user prompt)
    // shows up after the very first exchange. Fire-and-forget — a
    // failure here doesn't affect the just-rendered answer.
    if (conversationId !== null && !cancelToken.v) {
      void loadConversations()
    }
  }
}

interface DeltaMeta {
  latency_ms?: number
}
type DeltaCallback = (delta: string, meta?: DeltaMeta) => void

interface StreamOutcome {
  deltas: number
  /** True when the server emitted a terminal `done` frame. False if the
   *  stream closed after deltas but before `done` — caller surfaces this
   *  as "interrupted answer" so the operator knows the bubble is partial. */
  completed: boolean
}

/**
 * Consume the SSE stream from `/api/ai/query/stream`. We parse the wire
 * format inline — there's no standard "event source for POST" in the
 * browser yet, so a tiny reader over the response body is the simplest
 * option. The callback receives one chunk at a time; the `done` frame
 * arrives as an empty-string delta carrying the latency metadata.
 *
 * Returns an outcome so the caller can tell a clean completion from a
 * mid-stream disconnect (the server closes the socket without `done`
 * when, e.g., uvicorn is killed or the upstream proxy times out).
 */
async function streamAnswer(
  question: string,
  history: QueryHistoryTurn[],
  cancelToken: CancelToken,
  conversationId: number | null,
  onDelta: DeltaCallback,
): Promise<StreamOutcome> {
  const resp = await aiApi.askStream(question, history, {
    liteContext: liteContext.value,
    conversationId,
  })
  if (!resp.ok || !resp.body) {
    throw new Error(`stream rejected: HTTP ${resp.status}`)
  }
  const reader = resp.body.getReader()
  activeReader = reader
  const decoder = new TextDecoder('utf-8')
  let buffer = ''
  let streamError: string | null = null
  const outcome: StreamOutcome = { deltas: 0, completed: false }
  while (true) {
    if (cancelToken.v) break
    const { value, done } = await reader.read()
    if (done) break
    if (cancelToken.v) break
    buffer += decoder.decode(value, { stream: true })
    // SSE frames are separated by blank lines (\n\n). Split, leaving any
    // trailing partial frame in `buffer` for the next iteration.
    let separator: number
    while ((separator = buffer.indexOf('\n\n')) !== -1) {
      const rawFrame = buffer.slice(0, separator)
      buffer = buffer.slice(separator + 2)
      const result = handleFrame(rawFrame, onDelta, outcome)
      if (result?.error) {
        streamError = result.error
      }
    }
  }
  // Flush any trailing bytes — the server always terminates each frame
  // with \n\n, but a buggy/missing terminator on the very last one would
  // otherwise silently drop the `done` payload.
  buffer += decoder.decode()
  if (buffer.trim().length > 0) {
    const result = handleFrame(buffer.trim(), onDelta, outcome)
    if (result?.error) streamError = result.error
  }
  // Drop the reader handle whether we exited cleanly or via cancellation
  // so a subsequent send() doesn't double-cancel a finished stream.
  if (activeReader === reader) {
    activeReader = null
  }
  if (streamError) throw new Error(streamError)
  return outcome
}

function handleFrame(
  rawFrame: string,
  onDelta: DeltaCallback,
  outcome: StreamOutcome,
): { error?: string } | undefined {
  let eventName = 'message'
  let dataLine = ''
  for (const line of rawFrame.split('\n')) {
    if (line.startsWith('event:')) eventName = line.slice(6).trim()
    else if (line.startsWith('data:')) dataLine += line.slice(5).trim()
  }
  if (!dataLine) return undefined
  let payload: { text?: string; message?: string; latency_ms?: number }
  try {
    payload = JSON.parse(dataLine)
  } catch {
    return undefined
  }
  if (eventName === 'delta' && payload.text) {
    outcome.deltas += 1
    onDelta(payload.text)
  } else if (eventName === 'done') {
    outcome.completed = true
    onDelta('', { latency_ms: payload.latency_ms })
  } else if (eventName === 'error') {
    return { error: payload.message || 'stream error' }
  }
  return undefined
}

function newChat() {
  cancelActiveStream()
  turns.value = []
  input.value = ''
  activeConversationId.value = null
}

async function loadConversations(): Promise<void> {
  conversationsLoading.value = true
  conversationsError.value = null
  try {
    conversations.value = await aiApi.listConversations()
  } catch (err) {
    conversationsError.value = describe(err)
    conversations.value = []
  } finally {
    conversationsLoading.value = false
  }
}

/**
 * Open one of the persisted threads in the transcript. Cancels any
 * in-flight stream first to avoid the old answer landing in the
 * newly-loaded thread.
 */
async function openConversation(id: number): Promise<void> {
  if (id === activeConversationId.value) return
  cancelActiveStream()
  try {
    const detail = await aiApi.getConversation(id)
    activeConversationId.value = detail.id
    nextId = 1
    turns.value = detail.turns.map((t) => ({
      id: nextId++,
      role: t.role,
      text: t.text,
      entities: t.entities,
      latency_ms: t.latency_ms ?? undefined,
    }))
    input.value = ''
    await scrollToBottom()
  } catch (err) {
    toastError(describe(err))
  }
}

/**
 * Drawer-picked conversation: load it then close the drawer so the
 * user can read the transcript without an overlay in the way.
 */
async function onPickConversation(id: number): Promise<void> {
  await openConversation(id)
  historyOpen.value = false
}

async function removeConversation(id: number, e?: Event): Promise<void> {
  e?.stopPropagation()
  try {
    await aiApi.deleteConversation(id)
    conversations.value = conversations.value.filter((c) => c.id !== id)
    if (id === activeConversationId.value) newChat()
  } catch (err) {
    toastError(describe(err))
  }
}

/**
 * Lazily create a server-side conversation on the first user prompt.
 * Stateless one-off questions (no sidebar interaction) still work; the
 * thread is created the moment the user actually sends a message so
 * empty conversations don't litter the sidebar.
 */
async function ensureConversation(): Promise<number | null> {
  if (activeConversationId.value !== null) return activeConversationId.value
  try {
    const conv = await aiApi.createConversation()
    activeConversationId.value = conv.id
    // Optimistically prepend so the new thread shows in the sidebar
    // before the next loadConversations() round-trip.
    conversations.value = [conv, ...conversations.value]
    return conv.id
  } catch {
    // Persistence is best-effort: if the create call fails, fall back
    // to stateless one-shot mode. The user still sees the answer; only
    // history is lost.
    return null
  }
}

const hasConversation = computed(() => turns.value.length > 0)

async function scrollToBottom() {
  await nextTick()
  const el = transcriptRef.value
  if (el) el.scrollTop = el.scrollHeight
}

function onEnter(ev: KeyboardEvent) {
  // Enter sends; Shift+Enter inserts a newline (textarea default).
  if (ev.key === 'Enter' && !ev.shiftKey) {
    ev.preventDefault()
    send()
  }
}

const suggestions = [
  'ai.askView.example1',
  'ai.askView.example2',
  'ai.askView.example3',
  'ai.askView.example4',
]

function useSuggestion(key: string) {
  input.value = t(key)
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

const entityIcon: Record<string, typeof Server> = {
  switch: RouterIcon,
  port: RouterIcon,
  device: Server,
  vlan: Tags,
  subnet: Network,
}

function entityRoute(e: QueryEntityRef): string | null {
  switch (e.type) {
    case 'switch':
      return `/switches/${e.id}`
    case 'subnet':
      return `/subnets/${e.id}`
    case 'vlan':
      return '/vlans'
    case 'device':
      return '/devices'
    default:
      return null
  }
}

function entityLabel(e: QueryEntityRef): string {
  return e.name || `${e.type} #${e.id}`
}

const composerDisabled = computed(() => !status.value?.enabled)

onMounted(() => {
  void loadStatus()
  void loadConversations()
})
</script>

<template>
  <div class="px-4 py-8 sm:px-8 max-w-[1400px] mx-auto nf-stagger">
    <PageHeader :title="t('ai.askView.title')" :subtitle="t('ai.askView.subtitle')">
      <template #help>
        <HelpTooltip :text="t('ai.askView.help')" placement="bottom" />
      </template>
      <template #actions>
        <Button
          variant="ghost"
          size="sm"
          :aria-label="t('ai.askView.historyTitle')"
          @click="historyOpen = true"
        >
          <History class="w-4 h-4" aria-hidden="true" />
          {{ t('ai.askView.historyTitle') }}
          <span
            v-if="conversations.length > 0"
            class="ml-1 px-1.5 py-0.5 rounded bg-muted text-2xs tabular-nums leading-none"
          >
            {{ conversations.length }}
          </span>
        </Button>
        <Button
          v-if="hasConversation"
          variant="secondary"
          size="sm"
          :disabled="pending"
          @click="newChat"
        >
          <Plus class="w-4 h-4" aria-hidden="true" />
          {{ t('ai.askView.newChat') }}
        </Button>
      </template>
    </PageHeader>

    <!-- The conversation column. Narrower than the page so answer text keeps
         a comfortable measure; the prose itself is capped at 70ch below. -->
    <section class="mx-auto w-full max-w-4xl">
      <!-- Provider off: say so once, at the top, with the fix. -->
      <div
        v-if="status && !status.enabled"
        class="nf-card border-l-[3px] border-l-warning p-4 mb-4 flex items-start gap-3"
      >
        <AlertTriangle
          class="w-4 h-4 text-warning flex-shrink-0 mt-0.5"
          :stroke-width="1.9"
          aria-hidden="true"
        />
        <div class="min-w-0">
          <p class="text-base font-medium text-fg">{{ t('ai.askView.disabledTitle') }}</p>
          <p class="text-sm text-fg-muted mt-0.5">{{ t('ai.askView.disabledHint') }}</p>
        </div>
      </div>

      <!-- Transcript. Its own scroll region so a long answer stays pinned to
           the bottom without dragging the composer off screen. -->
      <div
        ref="transcriptRef"
        class="nf-card overflow-y-auto min-h-[18rem] max-h-[min(60vh,42rem)] mb-3"
      >
        <!-- Empty: explain + one-click examples -->
        <EmptyState
          v-if="turns.length === 0"
          :icon="Sparkles"
          :title="t('ai.askView.emptyTitle')"
          :description="t('ai.askView.emptyDescription')"
        >
          <template #action>
            <div class="grid sm:grid-cols-2 gap-2 max-w-xl text-left">
              <button
                v-for="key in suggestions"
                :key="key"
                type="button"
                class="group nf-card nf-interactive flex items-start gap-2 px-3 py-2.5 text-left"
                @click="useSuggestion(key)"
              >
                <span class="text-base text-fg leading-snug flex-1">{{ t(key) }}</span>
                <ArrowRight
                  class="w-3.5 h-3.5 text-fg-subtle flex-shrink-0 mt-0.5 opacity-0 -translate-x-1 group-hover:opacity-100 group-hover:translate-x-0 transition-all duration-200 ease-soft"
                  aria-hidden="true"
                />
              </button>
            </div>
          </template>
        </EmptyState>

        <!-- Thread. One hairline per turn boundary — the cheapest way to say
             "this is where the answer starts". -->
        <div v-else class="divide-y divide-border">
          <article
            v-for="turn in turns"
            :key="turn.id"
            class="flex gap-3 px-4 py-4 sm:px-5 sm:py-5"
          >
            <span
              v-if="turn.role === 'assistant'"
              class="flex-shrink-0 inline-flex items-center justify-center w-7 h-7 rounded-md bg-primary-600 text-white"
              aria-hidden="true"
            >
              <Bot class="w-4 h-4" />
            </span>
            <span
              v-else
              class="flex-shrink-0 inline-flex items-center justify-center w-7 h-7 rounded-md bg-muted text-fg-muted border border-border"
              aria-hidden="true"
            >
              <UserIcon class="w-4 h-4" />
            </span>

            <div class="min-w-0 flex-1">
              <div class="flex items-baseline gap-2 mb-1.5">
                <span class="text-sm font-semibold text-fg">
                  {{ turn.role === 'assistant' ? t('ai.askView.assistant') : t('ai.askView.you') }}
                </span>
                <span
                  v-if="turn.latency_ms !== undefined"
                  class="text-xs text-fg-subtle tabular-nums"
                >
                  {{ t('ai.askView.latency', { ms: turn.latency_ms }) }}
                </span>
              </div>

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
                  turn.role === 'assistant'
                    ? 'text-fg'
                    : 'text-fg rounded-lg bg-muted px-3.5 py-2.5 inline-block',
                ]"
                @click="onInlineClick"
                v-html="renderMarkdown(turn.text)"
              />
              <!-- eslint-enable vue/no-v-html -->

              <div v-if="turn.entities && turn.entities.length" class="mt-3 max-w-[70ch]">
                <p class="nf-label mb-1.5">{{ t('ai.askView.sourcesTitle') }}</p>
                <div class="flex flex-wrap gap-1.5">
                  <RouterLink
                    v-for="(e, idx) in turn.entities"
                    :key="`${e.type}-${e.id}-${idx}`"
                    v-slot="{ href, navigate }"
                    :to="entityRoute(e) ?? ''"
                    custom
                  >
                    <a
                      :href="entityRoute(e) ? href : undefined"
                      :class="[
                        'inline-flex items-center gap-1.5 h-7 px-2.5 rounded-md border text-xs font-medium',
                        'transition-colors duration-150 ease-soft',
                        entityRoute(e)
                          ? 'border-border bg-surface text-fg hover:border-primary-500 hover:text-primary-600 dark:hover:text-primary-400 cursor-pointer'
                          : 'border-transparent bg-muted text-fg-subtle cursor-default',
                      ]"
                      @click="entityRoute(e) ? navigate($event) : null"
                    >
                      <component
                        :is="entityIcon[e.type] ?? Server"
                        class="w-3 h-3 flex-shrink-0"
                        aria-hidden="true"
                      />
                      {{ entityLabel(e) }}
                    </a>
                  </RouterLink>
                </div>
              </div>
            </div>
          </article>

          <!-- Thinking indicator. Opacity-only CSS animation, removed the
               instant the first token lands (`pending` flips on delta #1). -->
          <div v-if="pending" class="flex gap-3 px-4 py-4 sm:px-5 sm:py-5" aria-busy="true">
            <span
              class="flex-shrink-0 inline-flex items-center justify-center w-7 h-7 rounded-md bg-primary-600 text-white"
              aria-hidden="true"
            >
              <Bot class="w-4 h-4" />
            </span>
            <div class="min-w-0 flex-1">
              <p class="text-sm font-semibold text-fg mb-1.5">{{ t('ai.askView.assistant') }}</p>
              <p class="inline-flex items-center gap-2 text-base text-fg-muted">
                <span class="inline-flex gap-1" aria-hidden="true">
                  <span class="w-1.5 h-1.5 rounded-full bg-primary-500 animate-pulse" />
                  <span
                    class="w-1.5 h-1.5 rounded-full bg-primary-500 animate-pulse"
                    style="animation-delay: 160ms"
                  />
                  <span
                    class="w-1.5 h-1.5 rounded-full bg-primary-500 animate-pulse"
                    style="animation-delay: 320ms"
                  />
                </span>
                {{ t('ai.askView.thinking') }}
              </p>
            </div>
          </div>
        </div>
      </div>

      <!-- Composer — the one place on the page that takes input. -->
      <form class="nf-card p-3 space-y-2.5" @submit.prevent="send">
        <textarea
          v-model="input"
          rows="3"
          class="nf-input resize-none"
          :placeholder="t('ai.askView.placeholder')"
          :disabled="composerDisabled || pending"
          :aria-label="t('ai.askView.placeholder')"
          @keydown="onEnter"
        />
        <div class="flex flex-wrap items-center justify-between gap-x-4 gap-y-2">
          <label
            class="flex items-center gap-2 text-xs text-fg-muted cursor-pointer select-none"
            :title="t('ai.askView.liteContextHint')"
          >
            <input
              v-model="liteContext"
              type="checkbox"
              class="rounded border-border-strong accent-primary-600"
              :disabled="pending"
            />
            <span>{{ t('ai.askView.liteContextLabel') }}</span>
          </label>
          <div class="flex items-center gap-3 ml-auto">
            <span class="text-xs text-fg-subtle hidden sm:inline">
              {{ t('ai.askView.composerHint') }}
            </span>
            <Button
              type="submit"
              variant="primary"
              :loading="pending"
              :disabled="!input.trim() || composerDisabled"
            >
              <Send class="w-4 h-4" aria-hidden="true" />
              {{ t('ai.askView.send') }}
            </Button>
          </div>
        </div>
      </form>
    </section>

    <!-- History drawer: shows the persisted conversation list on demand
         (PageHeader "Historique" button). Re-uses the project Modal so
         it inherits scroll-lock + focus-trap + topmost-stack handling. -->
    <Modal
      :open="historyOpen"
      :title="t('ai.askView.historyTitle')"
      size="md"
      @close="historyOpen = false"
    >
      <p v-if="conversationsLoading" class="text-base text-fg-muted">
        {{ t('common.loading') }}
      </p>
      <div v-else-if="conversationsError" class="space-y-3">
        <p class="text-base text-danger break-words">{{ conversationsError }}</p>
        <p class="text-sm text-fg-muted">{{ t('ai.askView.historyErrorHint') }}</p>
        <Button variant="secondary" size="sm" @click="loadConversations">
          {{ t('common.refresh') }}
        </Button>
      </div>
      <EmptyState
        v-else-if="conversations.length === 0"
        :icon="History"
        :title="t('ai.askView.historyEmpty')"
        :description="t('ai.askView.historyEmptyHint')"
        size="sm"
      />
      <ul v-else class="-mx-2 max-h-[60vh] overflow-y-auto space-y-1">
        <li
          v-for="c in conversations"
          :key="c.id"
          :class="[
            'group flex items-start gap-1 rounded-md pr-1',
            c.id === activeConversationId
              ? 'bg-primary-50 dark:bg-primary-500/15'
              : 'hover:bg-surface-hover',
            'transition-colors duration-150 ease-soft',
          ]"
        >
          <button
            type="button"
            :class="[
              'flex-1 min-w-0 text-left px-3 py-2 rounded-md text-base leading-snug',
              c.id === activeConversationId
                ? 'text-primary-700 dark:text-primary-300 font-medium'
                : 'text-fg',
            ]"
            :aria-current="c.id === activeConversationId ? 'true' : undefined"
            @click="onPickConversation(c.id)"
          >
            <span class="line-clamp-2 break-words block">
              {{ c.title || c.preview || t('ai.askView.untitledConversation') }}
            </span>
            <span v-if="c.turn_count" class="nf-label block mt-0.5">
              {{ c.turn_count }} {{ t('ai.askView.turnsLabel') }}
            </span>
          </button>
          <button
            type="button"
            class="flex-shrink-0 mt-1.5 inline-flex items-center justify-center w-7 h-7 rounded-md text-fg-subtle opacity-0 group-hover:opacity-100 focus-visible:opacity-100 hover:text-danger hover:bg-surface-hover transition-colors duration-150 ease-soft"
            :aria-label="t('common.delete')"
            @click="removeConversation(c.id, $event)"
          >
            <Trash2 class="w-3.5 h-3.5" aria-hidden="true" />
          </button>
        </li>
      </ul>
    </Modal>
  </div>
</template>

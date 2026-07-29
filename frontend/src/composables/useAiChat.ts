import { computed, onBeforeUnmount, onMounted, reactive, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import {
  aiApi,
  type AIStatus,
  type Conversation,
  type QueryEntityRef,
  type QueryHistoryTurn,
} from '@/api'
import { useApiErrorMessage } from '@/composables/useApiErrorMessage'
import { useAiStream } from '@/composables/useAiStream'
import { useToast } from '@/composables/useToast'

export interface AiTurn {
  id: number
  role: 'user' | 'assistant'
  text: string
  entities?: QueryEntityRef[]
  latency_ms?: number
}

export interface UseAiChatOptions {
  /** Pin the transcript to the bottom. Awaited at the same points the view
   *  used to await it, so a streaming answer never scrolls off screen. */
  scrollToBottom: () => Promise<void>
}

// History capped to the last 10 turns to match the server-side schema cap.
// The newest user message is NOT part of the history we send — it goes in the
// `question` field, so we only need to forward the prior turns.
const HISTORY_CAP = 10

/**
 * Ask-AI chat state: the transcript, the streaming exchange and the
 * persisted conversation list behind the history drawer.
 */
export function useAiChat(options: UseAiChatOptions) {
  const { t } = useI18n()
  const { describe } = useApiErrorMessage()
  const { error: toastError } = useToast()
  const { beginStream, releaseStream, cancelActiveStream, streamAnswer } = useAiStream()
  const { scrollToBottom } = options

  const status = ref<AIStatus | null>(null)
  const turns = ref<AiTurn[]>([])
  const input = ref('')
  const pending = ref(false)
  // Lite-context toggle: ask the backend to send a stripped snapshot
  // (identifiers only — no vendor / model / serial / notes / descriptions /
  // MACs / addresses). Cuts tokens ~10× and keeps free-text out of the
  // outbound request, at the cost of any answer that needs free-text.
  // Off by default — the verbose mode is the right default for a fresh
  // session, and operators who care opt-in per session.
  const liteContext = ref(false)
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

  async function loadStatus() {
    try {
      status.value = await aiApi.status()
    } catch {
      status.value = null
    }
  }

  function historyForBackend(): QueryHistoryTurn[] {
    // Take the most recent turns up to the cap; preserve order.
    const previous = turns.value.slice(-HISTORY_CAP)
    return previous.map((t) => ({
      role: t.role,
      text: t.text,
    }))
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
    const cancelToken = beginStream()
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
    const userTurn: AiTurn = { id: nextId++, role: 'user', text: question }
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
    let assistantTurn: AiTurn | null = null
    try {
      const outcome = await streamAnswer(
        {
          question,
          history,
          cancelToken,
          conversationId,
          liteContext: liteContext.value,
        },
        (delta, meta) => {
          if (!assistantTurn) {
            assistantTurn = reactive<AiTurn>({ id: nextId++, role: 'assistant', text: '' })
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
      const settled = assistantTurn as AiTurn | null
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
          reactive<AiTurn>({ id: nextId++, role: 'assistant', text: t('ai.askView.emptyAnswer') }),
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
      releaseStream(cancelToken)
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

  async function removeConversation(id: number): Promise<void> {
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
  const composerDisabled = computed(() => !status.value?.enabled)

  onMounted(() => {
    void loadStatus()
    void loadConversations()
  })

  return {
    status,
    turns,
    input,
    pending,
    liteContext,
    activeConversationId,
    conversations,
    conversationsLoading,
    conversationsError,
    hasConversation,
    composerDisabled,
    send,
    newChat,
    loadConversations,
    openConversation,
    removeConversation,
  }
}

import { aiApi, type QueryHistoryTurn } from '@/api'

/**
 * Per-stream cancellation token. Each `send()` captures a fresh
 * `{ v: false }` object in its closure and passes it into `streamAnswer`;
 * the read loop checks the LOCAL flag. The composable-level `activeReader`
 * handle still satisfies the cancel-on-resubmit / cancel-on-unmount
 * contract — when send() runs again we cancel the current reader (which
 * also flips its own token to true so the OLD send's finally branch
 * knows the stream was cancelled by us, not by the server, and skips
 * the "empty answer" / "incomplete answer" fallback messages that
 * would otherwise drop spurious bubbles into the chat).
 */
export interface CancelToken {
  v: boolean
}

export interface DeltaMeta {
  latency_ms?: number
}
export type DeltaCallback = (delta: string, meta?: DeltaMeta) => void

export interface StreamOutcome {
  deltas: number
  /** True when the server emitted a terminal `done` frame. False if the
   *  stream closed after deltas but before `done` — caller surfaces this
   *  as "interrupted answer" so the operator knows the bubble is partial. */
  completed: boolean
}

export interface StreamRequest {
  question: string
  history: QueryHistoryTurn[]
  cancelToken: CancelToken
  conversationId: number | null
  liteContext: boolean
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

/**
 * SSE plumbing for `/api/ai/query/stream`, plus the single-inflight-stream
 * bookkeeping (cancel on resubmit, cancel on unmount).
 */
export function useAiStream() {
  let activeReader: ReadableStreamDefaultReader<Uint8Array> | null = null
  let activeCancelToken: CancelToken | null = null

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

  /**
   * Cancel whatever is inflight and register the token for the stream that
   * is about to start.
   */
  function beginStream(): CancelToken {
    cancelActiveStream()
    const token: CancelToken = { v: false }
    activeCancelToken = token
    return token
  }

  /** Forget `token` iff it is still the current one (a newer send() may
   *  already have taken over). */
  function releaseStream(token: CancelToken): void {
    if (activeCancelToken === token) activeCancelToken = null
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
  async function streamAnswer(req: StreamRequest, onDelta: DeltaCallback): Promise<StreamOutcome> {
    const { cancelToken } = req
    const resp = await aiApi.askStream(req.question, req.history, {
      liteContext: req.liteContext,
      conversationId: req.conversationId,
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

  return { beginStream, releaseStream, cancelActiveStream, streamAnswer }
}

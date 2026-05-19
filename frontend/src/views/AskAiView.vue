<script setup lang="ts">
import { nextTick, onMounted, ref } from 'vue'
import { RouterLink } from 'vue-router'
import { useI18n } from 'vue-i18n'
import {
  Bot,
  MessageSquare,
  Network,
  Send,
  Server,
  Sparkles,
  Tags,
  User as UserIcon,
  Router as RouterIcon,
} from 'lucide-vue-next'
import PageHeader from '@/components/PageHeader.vue'
import Button from '@/components/ui/Button.vue'
import EmptyState from '@/components/EmptyState.vue'
import { aiApi, type AIStatus, type QueryEntityRef } from '@/api'
import { useApiErrorMessage } from '@/composables/useApiErrorMessage'
import { useToast } from '@/composables/useToast'

const { t } = useI18n()
const { describe } = useApiErrorMessage()
const { error: toastError } = useToast()

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
const transcriptRef = ref<HTMLDivElement | null>(null)
let nextId = 1

async function loadStatus() {
  try {
    status.value = await aiApi.status()
  } catch {
    status.value = null
  }
}

async function send() {
  const question = input.value.trim()
  if (!question || pending.value) return
  input.value = ''
  const userTurn: Turn = { id: nextId++, role: 'user', text: question }
  turns.value.push(userTurn)
  await scrollToBottom()

  pending.value = true
  try {
    const ans = await aiApi.ask(question)
    turns.value.push({
      id: nextId++,
      role: 'assistant',
      text: ans.answer,
      entities: ans.referenced_entities,
      latency_ms: ans.latency_ms,
    })
  } catch (err) {
    toastError(describe(err))
  } finally {
    pending.value = false
    await scrollToBottom()
  }
}

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
function renderMarkdown(src: string): string {
  const esc = src.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
  return esc
    .replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>')
    .replace(
      /`([^`]+)`/g,
      '<code class="px-1 py-0.5 rounded bg-muted/80 font-mono text-[0.85em]">$1</code>',
    )
    .replace(/\n/g, '<br>')
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

onMounted(loadStatus)
</script>

<template>
  <div class="p-4 sm:p-8 max-w-4xl mx-auto h-full flex flex-col">
    <PageHeader :title="t('ai.askView.title')" :subtitle="t('ai.askView.subtitle')" />

    <!-- Transcript scroll -->
    <div ref="transcriptRef" class="flex-1 min-h-0 overflow-y-auto space-y-4 pb-6">
      <!-- Empty: explain + suggestions -->
      <EmptyState
        v-if="turns.length === 0"
        :icon="Sparkles"
        :title="t('ai.askView.emptyTitle')"
        :description="t('ai.askView.emptyDescription')"
      >
        <template #action>
          <div class="flex flex-wrap justify-center gap-2 max-w-2xl mt-2">
            <button
              v-for="key in suggestions"
              :key="key"
              type="button"
              class="nf-pill bg-muted/70 hover:bg-primary-50 hover:text-primary-700 cursor-pointer text-left"
              @click="useSuggestion(key)"
            >
              <MessageSquare class="w-3 h-3" aria-hidden="true" />
              {{ t(key) }}
            </button>
          </div>
        </template>
      </EmptyState>

      <!-- Chat turns -->
      <div v-for="turn in turns" :key="turn.id" class="flex gap-3">
        <span
          v-if="turn.role === 'assistant'"
          class="flex-shrink-0 inline-flex items-center justify-center w-8 h-8 rounded-2xl bg-gradient-to-br from-primary-500 to-primary-700 text-white"
          aria-hidden="true"
        >
          <Bot class="w-4 h-4" />
        </span>
        <span
          v-else
          class="flex-shrink-0 inline-flex items-center justify-center w-8 h-8 rounded-2xl bg-muted text-fg-muted"
          aria-hidden="true"
        >
          <UserIcon class="w-4 h-4" />
        </span>
        <div class="min-w-0 flex-1">
          <p class="text-[11px] uppercase tracking-wider text-fg-muted font-semibold mb-1">
            {{ turn.role === 'assistant' ? t('ai.askView.assistant') : t('ai.askView.you') }}
          </p>
          <div
            class="rounded-lg px-4 py-3 text-sm leading-relaxed"
            :class="
              turn.role === 'assistant'
                ? 'bg-surface border border-border/70 dark:border-border/40'
                : 'bg-primary-50 dark:bg-primary-400/10'
            "
          >
            <!-- renderMarkdown escapes HTML before applying the bold/code/br
                 transforms, so the input is safe even if the LLM returns
                 raw markup. -->
            <!-- eslint-disable-next-line vue/no-v-html -->
            <div class="prose-sm" v-html="renderMarkdown(turn.text)" />
            <div
              v-if="turn.entities && turn.entities.length"
              class="mt-3 pt-3 border-t border-border/50 flex flex-wrap gap-1.5"
            >
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
                    'nf-pill bg-muted/70',
                    entityRoute(e)
                      ? 'hover:bg-primary-50 hover:text-primary-700 cursor-pointer'
                      : 'cursor-default text-fg-muted',
                  ]"
                  @click="entityRoute(e) ? navigate($event) : null"
                >
                  <component
                    :is="entityIcon[e.type] ?? Server"
                    class="w-3 h-3"
                    aria-hidden="true"
                  />
                  {{ entityLabel(e) }}
                </a>
              </RouterLink>
            </div>
            <p
              v-if="turn.latency_ms !== undefined"
              class="text-[11px] text-fg-muted mt-2 tabular-nums"
            >
              {{ t('ai.askView.latency', { ms: turn.latency_ms }) }}
            </p>
          </div>
        </div>
      </div>

      <!-- Pending bubble -->
      <div v-if="pending" class="flex gap-3" aria-busy="true">
        <span
          class="flex-shrink-0 inline-flex items-center justify-center w-8 h-8 rounded-2xl bg-gradient-to-br from-primary-500 to-primary-700 text-white"
          aria-hidden="true"
        >
          <Bot class="w-4 h-4" />
        </span>
        <div class="min-w-0 flex-1">
          <p class="text-[11px] uppercase tracking-wider text-fg-muted font-semibold mb-1">
            {{ t('ai.askView.assistant') }}
          </p>
          <div class="rounded-lg px-4 py-3 bg-surface border border-border/70 inline-flex gap-1.5">
            <span class="w-2 h-2 bg-fg-muted rounded-full animate-bounce" />
            <span
              class="w-2 h-2 bg-fg-muted rounded-full animate-bounce"
              style="animation-delay: 0.15s"
            />
            <span
              class="w-2 h-2 bg-fg-muted rounded-full animate-bounce"
              style="animation-delay: 0.3s"
            />
          </div>
        </div>
      </div>
    </div>

    <!-- Composer -->
    <form class="nf-card p-3 flex items-end gap-2 mt-auto" @submit.prevent="send">
      <textarea
        v-model="input"
        rows="2"
        class="flex-1 resize-none bg-transparent text-sm px-2 py-1.5 focus:outline-none placeholder:text-fg-muted"
        :placeholder="t('ai.askView.placeholder')"
        :disabled="!status?.enabled || pending"
        :aria-label="t('ai.askView.placeholder')"
        @keydown="onEnter"
      />
      <Button
        type="submit"
        variant="primary"
        shape="pill"
        :loading="pending"
        :disabled="!input.trim() || !status?.enabled"
      >
        <Send class="w-4 h-4" aria-hidden="true" />
        {{ t('ai.askView.send') }}
      </Button>
    </form>

    <p v-if="status && !status.enabled" class="text-xs text-fg-muted mt-2 text-center">
      {{ t('ai.askView.disabledHint') }}
    </p>
  </div>
</template>

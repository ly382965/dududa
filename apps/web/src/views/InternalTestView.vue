<script setup lang="ts">
import {
  AlertTriangle,
  Bot,
  CheckCircle2,
  ChevronLeft,
  ChevronRight,
  FlaskConical,
  LoaderCircle,
  MessageSquareText,
  RefreshCw,
  Search,
  SendHorizontal,
  ShieldCheck,
  Sparkles,
  ThumbsDown,
  ThumbsUp,
  Wrench,
} from '@lucide/vue'
import { computed, onMounted, reactive, ref } from 'vue'

import {
  internalTestAdapter,
  type InternalTestAdapter,
} from '../services/internal-test'
import type {
  InternalTestAnswerProfile,
  InternalTestCandidate,
  InternalTestFeedback,
  InternalTestProgress,
  InternalTestSample,
  InternalTestStatus,
  InternalTestTier,
  InternalTestVerdict,
} from '../types/internal-test'

const props = withDefaults(defineProps<{
  adapter?: InternalTestAdapter
}>(), {
  adapter: () => internalTestAdapter,
})

const status = ref<InternalTestStatus>()
const progress = ref<InternalTestProgress>({
  total: 0,
  evaluated: 0,
  pending: 0,
  accepted: 0,
  rejected: 0,
  needsReview: 0,
})
const samples = ref<InternalTestSample[]>([])
const total = ref(0)
const offset = ref(0)
const pageSize = 40
const selectedWindowId = ref('')
const candidate = ref<InternalTestCandidate>()
const loading = ref(true)
const listLoading = ref(false)
const generating = ref(false)
const submitting = ref(false)
const error = ref('')
const notice = ref('')
const generatedCount = ref(0)

const filters = reactive({
  q: '',
  bucket: 'all',
  complexity: 'all',
  profile: 'all',
  tools: 'all',
})

const form = reactive({
  verdict: 'accepted' as InternalTestVerdict,
  shouldReply: 'yes' as InternalTestFeedback['evaluation']['shouldReply'],
  routingReasonable: 4,
  correctness: 4,
  naturalness: 4,
  groupFit: 4,
  lengthFit: 4,
  correctedComplexity: '',
  correctedAnswerProfile: '' as '' | InternalTestAnswerProfile,
  note: '',
})

const selected = computed(() => samples.value.find((item) => item.window_id === selectedWindowId.value))
const reviewed = computed(() => progress.value.evaluated)
const pending = computed(() => progress.value.pending)
const currentPage = computed(() => Math.floor(offset.value / pageSize) + 1)
const pageCount = computed(() => Math.max(1, Math.ceil(total.value / pageSize)))
const canPrevious = computed(() => offset.value > 0)
const canNext = computed(() => offset.value + pageSize < total.value)

const tierModels: Record<InternalTestTier, string> = {
  haiku: 'GPT-5.6 Luna',
  sonnet: 'GPT-5.6 Terra',
  opus: 'GPT-5.6 Sol',
}

function modelForTier(tier: InternalTestTier): string {
  const configured = status.value?.modelMapping?.[tier]
  return configured ? `${tierModels[tier]} · ${configured}` : tierModels[tier]
}

const tierLabels: Record<InternalTestTier, string> = {
  haiku: '轻量 / Haiku',
  sonnet: '中等 / Sonnet',
  opus: '专业 / Opus',
}

const profileLabels: Record<InternalTestAnswerProfile, string> = {
  short: '短回答',
  medium: '中回答',
  long: '长回答',
}

function predictionLabel(value: { label: unknown; confidence: number } | undefined): string {
  if (!value) return '—'
  const label = typeof value.label === 'boolean' ? (value.label ? '需要' : '不需要') : String(value.label)
  return `${label} · ${Math.round(value.confidence * 100)}%`
}

function selectedTier(sample: InternalTestSample | undefined): InternalTestTier {
  return sample?.tier_preview?.selected_tier ?? 'sonnet'
}

function selectedProfile(sample: InternalTestSample | undefined): InternalTestAnswerProfile {
  return sample?.silver?.answer_profile ?? sample?.student?.answer_profile?.label ?? 'medium'
}

function compactId(value: string): string {
  return value.length > 16 ? `${value.slice(0, 8)}…${value.slice(-5)}` : value
}

function formatTime(value?: string): string {
  if (!value) return '—'
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString('zh-CN', { hour12: false })
}

function resetEvaluation(): void {
  form.verdict = 'accepted'
  form.shouldReply = 'yes'
  form.routingReasonable = 4
  form.correctness = 4
  form.naturalness = 4
  form.groupFit = 4
  form.lengthFit = 4
  form.correctedComplexity = ''
  form.correctedAnswerProfile = ''
  form.note = ''
}

function selectSample(sample: InternalTestSample): void {
  selectedWindowId.value = sample.window_id
  candidate.value = undefined
  notice.value = ''
  resetEvaluation()
}

async function loadSamples(reset = false): Promise<void> {
  if (reset) offset.value = 0
  listLoading.value = true
  error.value = ''
  try {
    const page = await props.adapter.samples({
      ...filters,
      offset: offset.value,
      limit: pageSize,
    })
    samples.value = page.items
    total.value = page.total
    if (!page.items.some((item) => item.window_id === selectedWindowId.value)) {
      selectedWindowId.value = page.items[0]?.window_id ?? ''
      candidate.value = undefined
    }
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : '样本读取失败'
  } finally {
    listLoading.value = false
  }
}

async function load(): Promise<void> {
  loading.value = true
  error.value = ''
  try {
    const nextStatus = await props.adapter.status()
    status.value = nextStatus
    progress.value = await props.adapter.progress()
    if (nextStatus.available) await loadSamples(true)
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : '内测台加载失败'
  } finally {
    loading.value = false
  }
}

async function generate(): Promise<void> {
  if (!selected.value) return
  generating.value = true
  error.value = ''
  notice.value = ''
  try {
    candidate.value = await props.adapter.generate(selected.value.window_id)
    generatedCount.value += 1
    notice.value = '候选回答已生成；仍处于 NO SEND，不会进入 QQ Output。'
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : '候选回答生成失败'
  } finally {
    generating.value = false
  }
}

async function submitFeedback(): Promise<void> {
  if (!selected.value || !candidate.value) return
  submitting.value = true
  error.value = ''
  notice.value = ''
  try {
    const payload: InternalTestFeedback = {
      windowId: selected.value.window_id,
      runId: candidate.value.runId,
      verdict: form.verdict,
      note: form.note.trim() || undefined,
      evaluation: {
        shouldReply: form.shouldReply,
        routingReasonable: form.routingReasonable,
        correctness: form.correctness,
        naturalness: form.naturalness,
        groupFit: form.groupFit,
        lengthFit: form.lengthFit,
      },
      corrected: {
        semanticComplexity: form.correctedComplexity || undefined,
        answerProfile: form.correctedAnswerProfile || undefined,
      },
    }
    const result = await props.adapter.feedback(payload)
    progress.value = result.progress
    notice.value = '人工评价已追加到仓库外 JSONL。'
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : '人工评价提交失败'
  } finally {
    submitting.value = false
  }
}

async function movePage(direction: -1 | 1): Promise<void> {
  offset.value = Math.max(0, offset.value + direction * pageSize)
  await loadSamples()
}

onMounted(load)
</script>

<template>
  <main class="internal-test-view">
    <header class="test-header">
      <div>
        <p class="eyebrow"><FlaskConical :size="15" /> S23 · 人工内测工作台</p>
        <h1>脱敏历史样本与模型候选评测</h1>
        <p>浏览 Silver / Student 投影，核对静态路由，并显式生成一条真实 Provider 候选。</p>
      </div>
      <button class="icon-button" type="button" title="刷新" :disabled="loading" @click="load">
        <RefreshCw :size="17" :class="{ spinning: loading }" />
      </button>
    </header>

    <section class="boundary-banner" aria-label="内测边界">
      <strong>PRIVATE DEVELOPMENT DATA</strong>
      <span>SILVER NOT GOLD</span>
      <span>NO SEND</span>
      <span>NO MEMORY WRITE</span>
      <span>NO TOOL CALL</span>
      <span>NO BANDIT</span>
    </section>

    <section v-if="loading" class="state-card">
      <LoaderCircle class="spinning" :size="24" /> 正在读取内测投影…
    </section>

    <section v-else-if="!status?.available" class="state-card unavailable">
      <AlertTriangle :size="25" />
      <div>
        <strong>内测数据尚未配置</strong>
        <p>{{ status?.warnings.join(' · ') || error || '请配置仓库外 S23E Demo 数据根。' }}</p>
      </div>
    </section>

    <template v-else>
      <section class="metrics-grid">
        <article><span>脱敏样本</span><strong>{{ status.sampleCount }}</strong></article>
        <article><span>已评价</span><strong>{{ reviewed }}</strong></article>
        <article><span>待评价</span><strong>{{ pending }}</strong></article>
        <article><span>本次生成</span><strong>{{ generatedCount }}</strong></article>
        <article><span>Provider</span><strong :class="status.providerConfigured ? 'ok' : 'warn'">{{ status.providerConfigured ? '已配置' : '未配置' }}</strong></article>
      </section>

      <form class="filters" @submit.prevent="loadSamples(true)">
        <label class="search-field">
          <Search :size="15" />
          <input v-model="filters.q" type="search" placeholder="搜索脱敏消息、主题或标签" />
        </label>
        <select v-model="filters.bucket" aria-label="场景分类">
          <option value="all">全部场景</option>
          <option value="short_chat">短聊天</option>
          <option value="ordinary_qa">普通问答</option>
          <option value="long_complex">复杂长问题</option>
          <option value="campus_retrieval">校园检索</option>
          <option value="programming">编程</option>
          <option value="multi_speaker">多人对话</option>
          <option value="ambiguous_reference">指代歧义</option>
          <option value="media_emoji_boundary">媒体边界</option>
          <option value="ordinary_group_negative">无需回复</option>
          <option value="tool_candidate">工具候选</option>
        </select>
        <select v-model="filters.complexity" aria-label="难度">
          <option value="all">全部难度</option>
          <option value="low">低</option>
          <option value="medium">中</option>
          <option value="high">高</option>
        </select>
        <select v-model="filters.profile" aria-label="回答长度">
          <option value="all">全部回答档位</option>
          <option value="short">短回答</option>
          <option value="medium">中回答</option>
          <option value="long">长回答</option>
        </select>
        <select v-model="filters.tools" aria-label="工具需求">
          <option value="all">全部工具需求</option>
          <option value="false">不需要工具</option>
          <option value="true">需要工具</option>
        </select>
        <button type="submit" :disabled="listLoading"><Search :size="15" />筛选</button>
      </form>

      <p v-if="error" class="inline-alert error"><AlertTriangle :size="15" />{{ error }}</p>
      <p v-if="notice" class="inline-alert success"><CheckCircle2 :size="15" />{{ notice }}</p>

      <section class="workspace-grid">
        <aside class="sample-pane">
          <div class="pane-heading">
            <div><strong>样本窗口</strong><span>{{ total }} 条匹配</span></div>
            <LoaderCircle v-if="listLoading" class="spinning" :size="16" />
          </div>
          <div class="sample-list">
            <button
              v-for="sample in samples"
              :key="sample.window_id"
              type="button"
              class="sample-card"
              :class="{ active: sample.window_id === selectedWindowId }"
              @click="selectSample(sample)"
            >
              <span class="sample-topline"><b>{{ sample.primary_bucket || '未分类' }}</b><small>{{ compactId(sample.window_id) }}</small></span>
              <span class="sample-preview">{{ sample.messages.at(-1)?.text || '（无文本）' }}</span>
              <span class="sample-meta">
                {{ sample.message_count ?? sample.messages.length }} 条 · {{ sample.speaker_count ?? '—' }} 人
                · {{ tierLabels[selectedTier(sample)] }}
              </span>
            </button>
            <p v-if="!samples.length" class="empty-state">当前筛选没有样本。</p>
          </div>
          <footer class="pagination">
            <button type="button" :disabled="!canPrevious || listLoading" @click="movePage(-1)"><ChevronLeft :size="15" /></button>
            <span>{{ currentPage }} / {{ pageCount }}</span>
            <button type="button" :disabled="!canNext || listLoading" @click="movePage(1)"><ChevronRight :size="15" /></button>
          </footer>
        </aside>

        <section class="conversation-pane">
          <div class="pane-heading">
            <div><strong>匿名群聊上下文</strong><span>{{ selected ? compactId(selected.window_id) : '未选择' }}</span></div>
            <span class="no-send-pill"><ShieldCheck :size="13" /> NO SEND</span>
          </div>
          <div v-if="selected" class="message-list">
            <article
              v-for="(message, index) in selected.messages"
              :key="message.message_ref"
              class="message-row"
              :class="{ current: index === selected.messages.length - 1, self: message.self_authored }"
            >
              <div class="avatar">{{ message.sender_ref.slice(-2).toUpperCase() }}</div>
              <div>
                <p class="sender">{{ message.sender_ref }} <span v-if="index === selected.messages.length - 1">当前消息</span></p>
                <p class="message-text">{{ message.text || '（仅包含附件或表情）' }}</p>
                <p v-if="message.attachment_kinds?.length" class="attachments">附件：{{ message.attachment_kinds.join('、') }}</p>
              </div>
            </article>
          </div>
          <div v-else class="empty-state large"><MessageSquareText :size="28" />选择一个样本开始检查。</div>
        </section>

        <aside class="review-pane">
          <template v-if="selected">
            <section class="review-section">
              <h2><Sparkles :size="16" /> 路由投影</h2>
              <dl class="route-grid">
                <div><dt>Silver 难度</dt><dd>{{ selected.silver?.semantic_complexity ?? '—' }}</dd></div>
                <div><dt>Student 难度</dt><dd>{{ predictionLabel(selected.student?.semantic_complexity) }}</dd></div>
                <div><dt>Silver 工具</dt><dd>{{ selected.silver?.need_tools ? '需要' : '不需要' }}</dd></div>
                <div><dt>Student 工具</dt><dd>{{ predictionLabel(selected.student?.need_tools) }}</dd></div>
                <div><dt>AnswerProfile</dt><dd>{{ profileLabels[selectedProfile(selected)] }}</dd></div>
                <div><dt>Static Tier</dt><dd>{{ tierLabels[selectedTier(selected)] }}</dd></div>
              </dl>
              <div class="model-card">
                <Bot :size="20" />
                <div><span>本样本映射</span><strong>{{ modelForTier(selectedTier(selected)) }}</strong></div>
                <small>后端返回最终模型；前端不参与路由决策</small>
              </div>
              <div class="tier-map">
                <span>Haiku → Luna</span><span>Sonnet → Terra</span><span>Opus → Sol</span>
              </div>
            </section>

            <section class="review-section generation-section">
              <h2><SendHorizontal :size="16" /> 候选回答</h2>
              <button
                class="generate-button"
                data-testid="generate-candidate"
                type="button"
                :disabled="generating || !status.providerConfigured"
                @click="generate"
              >
                <LoaderCircle v-if="generating" class="spinning" :size="16" />
                <Sparkles v-else :size="16" />
                {{ generating ? 'Provider 生成中…' : '生成 NO SEND 候选' }}
              </button>
              <p v-if="!status.providerConfigured" class="provider-hint">Provider 未配置，仍可浏览和评价标签。</p>
              <article v-if="candidate" class="candidate-card" data-testid="candidate-answer">
                <p>{{ candidate.candidate }}</p>
                <footer>
                  <span>{{ candidate.model }}</span>
                  <span>{{ candidate.latencyMs }} ms</span>
                  <span>{{ profileLabels[candidate.answerProfile] }}</span>
                  <b>Output {{ candidate.outputCalls }}</b>
                </footer>
              </article>
              <p v-else class="candidate-placeholder">由操作员显式触发。不会调用 QQ Output、Tool、Memory 或 Bandit。</p>
            </section>

            <form class="review-section evaluation-form" @submit.prevent="submitFeedback">
              <h2><ThumbsUp :size="16" /> 人工评价</h2>
              <div class="verdict-group">
                <label><input v-model="form.verdict" type="radio" value="accepted" /><ThumbsUp :size="14" />可接受</label>
                <label><input v-model="form.verdict" type="radio" value="needs_review" /><Wrench :size="14" />需修改</label>
                <label><input v-model="form.verdict" type="radio" value="rejected" /><ThumbsDown :size="14" />拒绝</label>
              </div>
              <label>是否应该回复
                <select v-model="form.shouldReply"><option value="yes">应该</option><option value="no">不应该</option><option value="uncertain">不确定</option></select>
              </label>
              <div class="rating-grid">
                <label>路由合理 <input v-model.number="form.routingReasonable" type="number" min="1" max="5" /></label>
                <label>事实正确 <input v-model.number="form.correctness" type="number" min="1" max="5" /></label>
                <label>自然程度 <input v-model.number="form.naturalness" type="number" min="1" max="5" /></label>
                <label>群聊适配 <input v-model.number="form.groupFit" type="number" min="1" max="5" /></label>
                <label>长度合适 <input v-model.number="form.lengthFit" type="number" min="1" max="5" /></label>
              </div>
              <div class="correction-grid">
                <label>修正难度<select v-model="form.correctedComplexity"><option value="">不修正</option><option value="low">低</option><option value="medium">中</option><option value="high">高</option></select></label>
                <label>修正长度<select v-model="form.correctedAnswerProfile"><option value="">不修正</option><option value="short">短回答</option><option value="medium">中回答</option><option value="long">长回答</option></select></label>
              </div>
              <label>备注<textarea v-model="form.note" rows="3" maxlength="2000" placeholder="记录错误、风格问题或更合适的回答方向" /></label>
              <button data-testid="submit-feedback" type="submit" :disabled="!candidate || submitting">
                <LoaderCircle v-if="submitting" class="spinning" :size="15" />
                <CheckCircle2 v-else :size="15" />
                {{ submitting ? '保存中…' : '保存仓库外评价' }}
              </button>
            </form>
          </template>
        </aside>
      </section>

      <footer class="data-footer">投影生成于 {{ formatTime(status.generatedAt) }} · {{ status.evidenceMode }} · 本页不是当前 Bot 实时流量</footer>
    </template>
  </main>
</template>

<style scoped>
.internal-test-view { min-height: 100%; padding: 22px; color: var(--text); background: radial-gradient(circle at 15% 0%, color-mix(in srgb, var(--brand) 10%, transparent), transparent 30%), var(--surface-muted); overflow: auto; }
.test-header { display: flex; justify-content: space-between; gap: 20px; align-items: flex-start; max-width: 1680px; margin: 0 auto 14px; }
.eyebrow { display: flex; align-items: center; gap: 7px; margin: 0 0 6px; color: var(--brand-strong); font-size: 12px; font-weight: 800; letter-spacing: .08em; text-transform: uppercase; }
.test-header h1 { margin: 0; font-size: clamp(23px, 2.5vw, 34px); letter-spacing: -.035em; }
.test-header p:not(.eyebrow) { margin: 7px 0 0; color: var(--text-secondary); }
.icon-button { display: grid; place-items: center; width: 39px; height: 39px; border: 1px solid var(--border); border-radius: 12px; color: var(--text-secondary); background: var(--surface); cursor: pointer; }
.boundary-banner { display: flex; flex-wrap: wrap; align-items: center; gap: 8px; max-width: 1680px; margin: 0 auto 14px; padding: 10px 12px; border: 1px solid color-mix(in srgb, #e09b28 42%, var(--border)); border-radius: 12px; background: color-mix(in srgb, #e09b28 9%, var(--surface)); }
.boundary-banner strong, .boundary-banner span { padding: 4px 8px; border-radius: 7px; font-size: 11px; font-weight: 800; letter-spacing: .035em; }
.boundary-banner strong { color: #fff; background: #9a4f14; }.boundary-banner span { color: #7e4a17; background: color-mix(in srgb, #e09b28 15%, var(--surface)); }
.state-card { display: flex; align-items: center; justify-content: center; gap: 12px; min-height: 260px; max-width: 900px; margin: 30px auto; border: 1px solid var(--border); border-radius: 18px; background: var(--surface); }
.state-card.unavailable { justify-content: flex-start; min-height: 150px; padding: 24px; }.state-card p { margin: 5px 0 0; color: var(--text-secondary); }
.metrics-grid { display: grid; grid-template-columns: repeat(5, minmax(0, 1fr)); gap: 10px; max-width: 1680px; margin: 0 auto 12px; }
.metrics-grid article { padding: 12px 14px; border: 1px solid var(--border); border-radius: 12px; background: var(--surface); box-shadow: 0 7px 24px rgb(0 0 0 / 3%); }.metrics-grid span { display: block; color: var(--text-muted); font-size: 11px; }.metrics-grid strong { display: block; margin-top: 3px; font-size: 21px; }.metrics-grid strong.ok { color: #16835a; font-size: 15px; }.metrics-grid strong.warn { color: #b96b18; font-size: 15px; }
.filters { display: grid; grid-template-columns: minmax(250px, 1.4fr) repeat(4, minmax(130px, .55fr)) auto; gap: 8px; max-width: 1680px; margin: 0 auto 12px; }.filters input, .filters select, .evaluation-form select, .evaluation-form textarea, .evaluation-form input[type="number"] { width: 100%; border: 1px solid var(--border); border-radius: 9px; color: var(--text); background: var(--surface); outline: none; }.filters input, .filters select { min-height: 38px; padding: 0 10px; }.search-field { display: flex; align-items: center; gap: 7px; padding-left: 11px; border: 1px solid var(--border); border-radius: 9px; background: var(--surface); }.search-field input { padding-left: 0; border: 0; background: transparent; }.filters button, .evaluation-form > button { display: inline-flex; align-items: center; justify-content: center; gap: 7px; border: 0; border-radius: 9px; padding: 0 15px; color: #fff; font-weight: 700; background: var(--brand); cursor: pointer; }
.inline-alert { display: flex; align-items: center; gap: 7px; max-width: 1680px; margin: 0 auto 9px; padding: 9px 11px; border-radius: 9px; font-size: 13px; }.inline-alert.error { color: #a33a31; background: #fff0ee; }.inline-alert.success { color: #166c4d; background: #eaf8f1; }
.workspace-grid { display: grid; grid-template-columns: minmax(240px, .78fr) minmax(360px, 1.35fr) minmax(330px, 1fr); gap: 10px; max-width: 1680px; height: min(820px, calc(100vh - 265px)); min-height: 560px; margin: 0 auto; }
.sample-pane, .conversation-pane, .review-pane { min-width: 0; border: 1px solid var(--border); border-radius: 14px; background: var(--surface); box-shadow: 0 9px 30px rgb(0 0 0 / 4%); overflow: hidden; }.sample-pane, .conversation-pane { display: flex; flex-direction: column; }.review-pane { overflow-y: auto; }
.pane-heading { display: flex; align-items: center; justify-content: space-between; min-height: 55px; padding: 10px 13px; border-bottom: 1px solid var(--border); }.pane-heading strong, .pane-heading span { display: block; }.pane-heading span { margin-top: 2px; color: var(--text-muted); font-size: 11px; }.no-send-pill { display: inline-flex !important; align-items: center; gap: 4px; margin: 0 !important; padding: 5px 7px; border-radius: 999px; color: #166c4d !important; font-weight: 800; background: #eaf8f1; }
.sample-list { flex: 1; overflow-y: auto; }.sample-card { display: block; width: 100%; padding: 11px 12px; border: 0; border-bottom: 1px solid var(--border); color: inherit; text-align: left; background: transparent; cursor: pointer; }.sample-card:hover { background: var(--surface-muted); }.sample-card.active { box-shadow: inset 3px 0 var(--brand); background: color-mix(in srgb, var(--brand) 8%, var(--surface)); }.sample-topline { display: flex; justify-content: space-between; gap: 7px; }.sample-topline b { font-size: 12px; }.sample-topline small { color: var(--text-muted); }.sample-preview { display: -webkit-box; margin: 6px 0; overflow: hidden; color: var(--text-secondary); font-size: 12px; -webkit-box-orient: vertical; -webkit-line-clamp: 2; }.sample-meta { color: var(--text-muted); font-size: 10px; }.pagination { display: flex; align-items: center; justify-content: center; gap: 12px; min-height: 42px; border-top: 1px solid var(--border); }.pagination button { display: grid; place-items: center; width: 28px; height: 28px; border: 1px solid var(--border); border-radius: 8px; color: inherit; background: var(--surface); cursor: pointer; }.pagination span { font-size: 12px; color: var(--text-secondary); }
.message-list { flex: 1; padding: 15px; overflow-y: auto; }.message-row { display: grid; grid-template-columns: 34px 1fr; gap: 9px; padding: 9px; border-radius: 10px; }.message-row.current { border: 1px solid color-mix(in srgb, var(--brand) 32%, var(--border)); background: color-mix(in srgb, var(--brand) 6%, var(--surface)); }.message-row.self { margin-left: 24px; }.avatar { display: grid; place-items: center; width: 32px; height: 32px; border-radius: 10px; color: var(--brand-strong); font-size: 10px; font-weight: 800; background: color-mix(in srgb, var(--brand) 12%, var(--surface-muted)); }.sender { margin: 0 0 4px; color: var(--text-secondary); font-size: 11px; font-weight: 700; }.sender span { margin-left: 6px; color: var(--brand-strong); }.message-text { margin: 0; white-space: pre-wrap; overflow-wrap: anywhere; line-height: 1.55; }.attachments { margin: 5px 0 0; color: var(--text-muted); font-size: 11px; }
.review-section { padding: 14px; border-bottom: 1px solid var(--border); }.review-section h2 { display: flex; align-items: center; gap: 7px; margin: 0 0 11px; font-size: 14px; }.route-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 7px; margin: 0; }.route-grid div { padding: 8px; border-radius: 8px; background: var(--surface-muted); }.route-grid dt { color: var(--text-muted); font-size: 10px; }.route-grid dd { margin: 3px 0 0; font-size: 12px; font-weight: 700; }.model-card { display: grid; grid-template-columns: auto 1fr; gap: 8px 10px; align-items: center; margin-top: 10px; padding: 10px; border: 1px solid color-mix(in srgb, var(--brand) 22%, var(--border)); border-radius: 10px; background: color-mix(in srgb, var(--brand) 5%, var(--surface)); }.model-card span, .model-card strong { display: block; }.model-card span { color: var(--text-muted); font-size: 10px; }.model-card small { grid-column: 1 / -1; color: var(--text-muted); }.tier-map { display: flex; flex-wrap: wrap; gap: 5px; margin-top: 8px; }.tier-map span { padding: 4px 6px; border-radius: 6px; color: var(--text-secondary); font-size: 10px; background: var(--surface-muted); }
.generate-button { display: flex; align-items: center; justify-content: center; gap: 7px; width: 100%; min-height: 39px; border: 0; border-radius: 9px; color: #fff; font-weight: 800; background: linear-gradient(135deg, var(--brand), var(--brand-strong)); cursor: pointer; }.candidate-placeholder, .provider-hint { color: var(--text-muted); font-size: 11px; line-height: 1.5; }.candidate-card { margin-top: 10px; padding: 11px; border: 1px solid color-mix(in srgb, #16835a 25%, var(--border)); border-radius: 10px; background: color-mix(in srgb, #16835a 5%, var(--surface)); }.candidate-card p { margin: 0; white-space: pre-wrap; line-height: 1.58; }.candidate-card footer { display: flex; flex-wrap: wrap; gap: 6px; margin-top: 10px; }.candidate-card footer span, .candidate-card footer b { padding: 3px 5px; border-radius: 5px; font-size: 9px; background: var(--surface-muted); }.candidate-card footer b { color: #166c4d; }
.evaluation-form { display: grid; gap: 10px; }.evaluation-form label { display: grid; gap: 5px; color: var(--text-secondary); font-size: 11px; }.evaluation-form select, .evaluation-form textarea, .evaluation-form input[type="number"] { padding: 7px 8px; }.evaluation-form textarea { resize: vertical; }.verdict-group { display: grid; grid-template-columns: repeat(3, 1fr); gap: 5px; }.verdict-group label { display: flex; align-items: center; justify-content: center; gap: 4px; min-height: 32px; border: 1px solid var(--border); border-radius: 8px; cursor: pointer; }.verdict-group input { accent-color: var(--brand); }.rating-grid, .correction-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 7px; }.evaluation-form > button { min-height: 39px; }.evaluation-form button:disabled, .generate-button:disabled, .filters button:disabled, .icon-button:disabled, .pagination button:disabled { opacity: .48; cursor: not-allowed; }
.empty-state { padding: 25px; color: var(--text-muted); text-align: center; }.empty-state.large { display: flex; flex: 1; flex-direction: column; align-items: center; justify-content: center; gap: 8px; }.data-footer { max-width: 1680px; margin: 10px auto 0; color: var(--text-muted); font-size: 10px; text-align: right; }.spinning { animation: spin .8s linear infinite; }
@keyframes spin { to { transform: rotate(360deg); } }
@media (max-width: 1180px) { .metrics-grid { grid-template-columns: repeat(3, 1fr); }.filters { grid-template-columns: 1fr 1fr 1fr; }.search-field { grid-column: 1 / -1; }.workspace-grid { grid-template-columns: 270px 1fr; height: auto; min-height: 0; }.review-pane { grid-column: 1 / -1; display: grid; grid-template-columns: repeat(3, 1fr); overflow: visible; }.review-section { border-right: 1px solid var(--border); } }
@media (max-width: 760px) { .internal-test-view { padding: 14px 10px 84px; }.metrics-grid { grid-template-columns: repeat(2, 1fr); }.filters { grid-template-columns: 1fr 1fr; }.filters button { min-height: 38px; }.workspace-grid { display: block; }.sample-pane, .conversation-pane, .review-pane { margin-bottom: 10px; }.sample-pane { height: 360px; }.conversation-pane { min-height: 520px; }.review-pane { display: block; }.boundary-banner span { font-size: 9px; }.test-header h1 { font-size: 23px; } }
</style>

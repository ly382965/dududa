<script setup lang="ts">
import {
  Activity,
  ArrowLeft,
  Bot,
  Check,
  ChevronDown,
  CircleStop,
  Clock3,
  FileSearch,
  Gauge,
  Hash,
  MessageSquareText,
  MoreHorizontal,
  Paperclip,
  Plus,
  Save,
  Search,
  SendHorizontal,
  Settings2,
  ShieldCheck,
  Sparkles,
  Wrench,
  Unplug,
  X,
} from '@lucide/vue'
import { nextTick, ref, watch } from 'vue'

import type {
  Account,
  AgentConfig,
  AgentMessage,
  AgentPart,
  AgentRun,
  AgentSession,
  AgentTab,
  Conversation,
  PermissionPart,
  ReplyDraftPart,
} from '../types/workspace'
import AgentPartView from './AgentPartView.vue'
import AppAvatar from './AppAvatar.vue'

const props = defineProps<{
  conversation?: Conversation
  account?: Account
  accounts: Account[]
  sessions: AgentSession[]
  selectedSession?: AgentSession
  messages: AgentMessage[]
  run?: AgentRun
  config: AgentConfig
  tab: AgentTab
  available: boolean
}>()

const emit = defineEmits<{
  setTab: [tab: AgentTab]
  selectSession: [id: string]
  newSession: []
  sendPrompt: [content: string]
  approveDraft: [part: ReplyDraftPart]
  discardDraft: [part: ReplyDraftPart]
  updateDraft: [part: ReplyDraftPart, content: string]
  respondPermission: [part: PermissionPart, allow: boolean]
  saveSettings: []
  back: []
  collapse: []
  notify: [message: string]
}>()

const prompt = ref('')
const sessionMenuOpen = ref(false)
const stream = ref<HTMLElement>()

const tabs = [
  { id: 'conversation', label: '对话', icon: MessageSquareText },
  { id: 'run', label: '运行', icon: Activity },
  { id: 'settings', label: '配置', icon: Settings2 },
] as const

function send(): void {
  const value = prompt.value.trim()
  if (!value) return
  emit('sendPrompt', value)
  prompt.value = ''
}

function handleKeydown(event: KeyboardEvent): void {
  if (event.key !== 'Enter' || event.shiftKey || event.isComposing) return
  event.preventDefault()
  send()
}

function chooseSession(id: string): void {
  emit('selectSession', id)
  sessionMenuOpen.value = false
}

function selectQuickPrompt(value: string): void {
  prompt.value = value
  void nextTick(() => document.querySelector<HTMLTextAreaElement>('.agent-composer textarea')?.focus())
}

function partKey(message: AgentMessage, part: AgentPart, index: number): string {
  if ('id' in part) return `${message.id}-${part.id}`
  return `${message.id}-${part.type}-${index}`
}

watch(
  () => props.messages.length,
  () => {
    void nextTick(() => {
      if (stream.value) stream.value.scrollTop = stream.value.scrollHeight
    })
  },
)
</script>

<template>
  <aside class="agent-console" aria-label="Agent Console">
    <header class="agent-header">
      <button class="icon-button mobile-back" type="button" title="返回聊天" aria-label="返回聊天" @click="emit('back')">
        <ArrowLeft :size="20" />
      </button>
      <span class="agent-logo"><Sparkles :size="17" /></span>
      <div class="agent-heading">
        <div><strong>Dududa Agent</strong><span class="runtime-dot" :class="{ online: available }" /> <small>{{ available ? '已连接' : '未连接' }}</small></div>
        <p>{{ conversation?.name ?? '未选择会话' }}</p>
      </div>
      <button class="icon-button desktop-collapse" type="button" title="收起 Agent Console" aria-label="收起 Agent Console" @click="emit('collapse')">
        <X :size="17" />
      </button>
    </header>

    <div class="agent-context-bar">
      <div class="session-picker">
        <button type="button" :disabled="!available" :aria-expanded="sessionMenuOpen" @click="sessionMenuOpen = !sessionMenuOpen">
          <span class="session-status" :class="`session-status--${selectedSession?.status ?? 'idle'}`" />
          <span>{{ selectedSession?.title ?? '新对话' }}</span>
          <ChevronDown :size="14" />
        </button>
        <div v-if="sessionMenuOpen" class="session-menu">
          <button
            v-for="session in sessions"
            :key="session.id"
            type="button"
            :class="{ active: session.id === selectedSession?.id }"
            @click="chooseSession(session.id)"
          >
            <span><strong>{{ session.title }}</strong><small>{{ session.model }} · {{ session.updatedAt }}</small></span>
            <Check v-if="session.id === selectedSession?.id" :size="14" />
          </button>
          <button class="new-session-row" type="button" @click="emit('newSession'); sessionMenuOpen = false">
            <Plus :size="14" />新建对话
          </button>
        </div>
      </div>
      <label class="model-picker">
        <span>MODEL</span>
        <select :value="config.model" aria-label="选择模型" disabled>
          <option>GPT-5</option>
          <option>Claude Sonnet 4</option>
          <option>DeepSeek V3</option>
          <option>Qwen3 235B</option>
        </select>
      </label>
      <button class="icon-button" type="button" title="新建 Agent 对话" aria-label="新建 Agent 对话" :disabled="!available" @click="emit('newSession')">
        <Plus :size="17" />
      </button>
    </div>

    <nav class="agent-tabs" aria-label="Agent Console 视图">
      <button v-for="item in tabs" :key="item.id" :class="{ active: tab === item.id }" type="button" :disabled="!available && item.id !== 'conversation'" @click="emit('setTab', item.id)">
        <component :is="item.icon" :size="14" />
        <span>{{ item.label }}</span>
        <b v-if="item.id === 'run' && run?.status === 'waiting_approval'">1</b>
      </button>
    </nav>

    <template v-if="tab === 'conversation'">
      <section ref="stream" class="agent-stream" aria-label="Agent 对话消息">
        <div class="scope-line">
          <span><Hash :size="12" />{{ conversation?.name }}</span>
          <span>{{ config.contextMessages }} 条上下文</span>
        </div>

        <div v-if="!available" class="runtime-unavailable">
          <span><Unplug :size="18" /></span>
          <div><strong>Agent Runtime 未连接</strong><small>QQ 消息与历史已由 NapCat 实时提供</small></div>
        </div>

        <article v-for="message in messages" :key="message.id" class="agent-message" :class="`agent-message--${message.role}`">
          <header>
            <span v-if="message.role === 'assistant'" class="assistant-avatar"><Sparkles :size="13" /></span>
            <AppAvatar
              v-else-if="message.role === 'operator' && account"
              :src="account.avatar"
              name="你"
              size="xs"
            />
            <span v-else class="system-avatar"><Bot :size="12" /></span>
            <strong>{{ message.author }}</strong>
            <time>{{ message.timestamp }}</time>
          </header>
          <div class="agent-parts">
            <AgentPartView
              v-for="(part, index) in message.parts"
              :key="partKey(message, part, index)"
              :part="part"
              :accounts="accounts"
              @approve-draft="emit('approveDraft', $event)"
              @discard-draft="emit('discardDraft', $event)"
              @update-draft="(part, content) => emit('updateDraft', part, content)"
              @respond-permission="(part, allow) => emit('respondPermission', part, allow)"
            />
          </div>
        </article>

        <div v-if="selectedSession?.status === 'running'" class="agent-thinking">
          <span class="assistant-avatar"><Sparkles :size="13" /></span>
          <span><i /><i /><i /></span>
          <small>Agent 正在处理</small>
        </div>

        <div v-if="!messages.length && selectedSession?.status !== 'running'" class="agent-empty">
          <Sparkles :size="27" />
          <strong>{{ selectedSession?.title ?? '新对话' }}</strong>
          <div class="quick-prompts">
            <button type="button" @click="selectQuickPrompt('总结这个群今天的讨论')">生成今日摘要</button>
            <button type="button" @click="selectQuickPrompt('检查 Bot 上一条回复是否准确')">检查上一条回复</button>
          </div>
        </div>
      </section>

      <footer class="agent-composer">
        <div class="context-chip"><Hash :size="12" />{{ conversation?.name }}<span>最近 {{ config.contextMessages }} 条</span></div>
        <textarea
          v-model="prompt"
          rows="3"
          placeholder="给 Agent 分配任务"
          aria-label="Agent 指令输入"
          :disabled="!available"
          @keydown="handleKeydown"
        />
        <div class="agent-composer-footer">
          <div>
            <button class="icon-button" type="button" title="添加附件" aria-label="添加附件" @click="emit('notify', '请选择附件')">
              <Paperclip :size="16" />
            </button>
            <button class="icon-button" type="button" title="更多指令" aria-label="更多指令" @click="emit('notify', '指令菜单已打开')">
              <MoreHorizontal :size="16" />
            </button>
          </div>
          <button
            v-if="selectedSession?.status === 'running'"
            class="stop-button"
            type="button"
            title="中止运行"
            aria-label="中止运行"
            @click="emit('notify', '已请求中止当前运行')"
          >
            <CircleStop :size="17" />
          </button>
          <button v-else class="prompt-send" type="button" title="发送给 Agent" aria-label="发送给 Agent" :disabled="!available || !prompt.trim()" @click="send">
            <SendHorizontal :size="17" />
          </button>
        </div>
      </footer>
    </template>

    <section v-else-if="tab === 'run'" class="run-view">
      <template v-if="run">
        <header class="run-heading">
          <div>
            <span>AGENT RUN</span>
            <h3>{{ run.id }}</h3>
          </div>
          <span class="run-status" :class="`run-status--${run.status}`">
            <span />{{ run.status === 'waiting_approval' ? '等待审核' : run.status === 'running' ? '运行中' : '已完成' }}
          </span>
        </header>

        <div class="run-metrics">
          <div><Clock3 :size="14" /><span><small>耗时</small><strong>{{ run.duration }}</strong></span></div>
          <div><Gauge :size="14" /><span><small>Tokens</small><strong>{{ run.tokens }}</strong></span></div>
          <div><MessageSquareText :size="14" /><span><small>上下文</small><strong>{{ run.contextMessages }} 条</strong></span></div>
          <div><Activity :size="14" /><span><small>费用</small><strong>{{ run.cost }}</strong></span></div>
        </div>

        <section class="run-section">
          <div class="section-label">触发消息</div>
          <div class="trigger-message">
            <AppAvatar :src="run.triggerAvatar" :name="run.triggerSender" size="sm" />
            <div><strong>{{ run.triggerSender }}</strong><p>{{ run.triggerContent }}</p></div>
          </div>
        </section>

        <section class="run-section run-details">
          <div class="section-label">运行信息</div>
          <dl>
            <div><dt>模型</dt><dd>{{ run.model }}</dd></div>
            <div><dt>开始于</dt><dd>{{ run.startedAt }}</dd></div>
            <div><dt>回复账号</dt><dd>{{ account?.name }}</dd></div>
            <div><dt>发送权限</dt><dd>人工审核</dd></div>
          </dl>
        </section>

        <section class="run-section">
          <div class="section-label">执行过程</div>
          <ol class="run-timeline">
            <li v-for="step in run.steps" :key="step.id" :class="`step--${step.status}`">
              <span class="step-marker"><Check v-if="step.status === 'completed'" :size="11" /><span v-else /></span>
              <div><strong>{{ step.label }}</strong><p>{{ step.detail }}</p></div>
              <time v-if="step.duration">{{ step.duration }}</time>
            </li>
          </ol>
        </section>
      </template>
      <div v-else class="run-empty"><Activity :size="28" /><strong>当前对话还没有运行</strong></div>
    </section>

    <section v-else class="settings-view">
      <div class="settings-intro">
        <div><span>会话配置</span><h3>{{ conversation?.name }}</h3></div>
        <label class="switch-control">
          <input :checked="config.enabled" type="checkbox" disabled />
          <span />
        </label>
      </div>

      <section class="settings-section">
        <div class="section-heading"><Bot :size="15" /><span><strong>Agent 与模型</strong><small>CONVERSATION DEFAULT</small></span></div>
        <label class="form-row"><span>Agent</span><select :value="config.agent" disabled><option>群聊助手 v2</option><option>课程信息助手</option><option>回复审校</option></select></label>
        <label class="form-row"><span>模型</span><select :value="config.model" disabled><option>GPT-5</option><option>Claude Sonnet 4</option><option>DeepSeek V3</option><option>Qwen3 235B</option></select></label>
        <div class="form-row"><span>推理强度</span><div class="segmented-control"><button v-for="level in (['low', 'medium', 'high'] as const)" :key="level" type="button" :class="{ active: config.reasoning === level }" disabled>{{ { low: '低', medium: '中', high: '高' }[level] }}</button></div></div>
      </section>

      <section class="settings-section">
        <div class="section-heading"><Activity :size="15" /><span><strong>触发与上下文</strong><small>SOCIAL POLICY</small></span></div>
        <label class="form-row"><span>触发策略</span><select :value="config.trigger" disabled><option value="mention">被 @ 时</option><option value="keyword">关键词触发</option><option value="manual">仅手动</option><option value="observe">Shadow Mode</option></select></label>
        <label class="range-row"><span><span>上下文消息</span><strong>{{ config.contextMessages }} 条</strong></span><input :value="config.contextMessages" type="range" min="10" max="100" step="10" disabled /></label>
        <label class="toggle-row"><span><strong>包含回复链</strong><small>读取引用消息的关联上下文</small></span><input :checked="config.includeReplyChain" type="checkbox" disabled /></label>
        <label class="toggle-row"><span><strong>包含图片摘要</strong><small>只传递经过处理的图片描述</small></span><input :checked="config.includeImages" type="checkbox" disabled /></label>
        <label class="toggle-row"><span><strong>长期群记忆</strong><small>按账号与群聊作用域隔离</small></span><input :checked="config.longTermMemory" type="checkbox" disabled /></label>
      </section>

      <section class="settings-section">
        <div class="section-heading"><Wrench :size="15" /><span><strong>工具</strong><small>CAPABILITY SCOPE</small></span></div>
        <div class="tool-grid">
          <button type="button" disabled :class="{ active: config.tools.course }"><FileSearch :size="15" /><span><strong>校园课程</strong><small>iCourse MCP</small></span><Check v-if="config.tools.course" :size="13" /></button>
          <button type="button" disabled :class="{ active: config.tools.web }"><Search :size="15" /><span><strong>网络搜索</strong><small>受限域名</small></span><Check v-if="config.tools.web" :size="13" /></button>
          <button type="button" disabled :class="{ active: config.tools.groupFiles }"><FileSearch :size="15" /><span><strong>群文件</strong><small>只读</small></span><Check v-if="config.tools.groupFiles" :size="13" /></button>
          <button type="button" disabled :class="{ active: config.tools.shell }"><Bot :size="15" /><span><strong>Shell</strong><small>默认禁止</small></span><Check v-if="config.tools.shell" :size="13" /></button>
        </div>
      </section>

      <section class="settings-section permission-settings">
        <div class="section-heading"><ShieldCheck :size="15" /><span><strong>权限</strong><small>FAIL CLOSED</small></span></div>
        <label class="form-row"><span>工具调用</span><select :value="config.toolPermission" disabled><option value="ask">需要审核</option><option value="allow">自动允许</option><option value="deny">全部拒绝</option></select></label>
        <label class="form-row"><span>发送 QQ 消息</span><select :value="config.sendPermission" disabled><option value="ask">需要审核</option><option value="allow">自动允许</option><option value="deny">禁止发送</option></select></label>
      </section>

      <footer class="settings-footer">
        <span><ShieldCheck :size="13" />等待专用 Core Command</span>
        <button type="button" class="save-button" disabled><Save :size="14" />不可用</button>
      </footer>
    </section>
  </aside>
</template>

<style scoped>
.agent-console {
  position: relative;
  display: flex;
  min-width: 0;
  min-height: 0;
  flex-direction: column;
  border-left: 1px solid var(--border-strong);
  background: var(--agent-background);
}

.agent-header {
  display: flex;
  height: 64px;
  min-width: 0;
  flex: 0 0 auto;
  align-items: center;
  gap: 9px;
  border-bottom: 1px solid var(--border);
  background: var(--surface);
  padding: 0 12px;
}

.mobile-back {
  display: none;
}

.agent-logo,
.assistant-avatar,
.system-avatar {
  display: grid;
  flex: 0 0 auto;
  place-items: center;
  border-radius: 6px;
  color: #ffffff;
  background: var(--brand);
}

.agent-logo {
  width: 32px;
  height: 32px;
}

.agent-heading {
  min-width: 0;
  flex: 1;
}

.agent-heading > div {
  display: flex;
  align-items: center;
  gap: 5px;
}

.agent-heading strong {
  color: var(--text);
  font-size: 12px;
  font-weight: 720;
}

.agent-heading small,
.agent-heading p {
  color: var(--text-muted);
  font-size: 8px;
}

.agent-heading p {
  overflow: hidden;
  margin: 3px 0 0;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.runtime-dot {
  width: 6px;
  height: 6px;
  margin-left: 2px;
  border-radius: 50%;
  background: var(--warning);
}

.runtime-dot.online {
  background: var(--success);
}

.agent-context-bar {
  display: grid;
  height: 46px;
  flex: 0 0 auto;
  grid-template-columns: minmax(0, 1fr) auto 30px;
  align-items: center;
  gap: 7px;
  border-bottom: 1px solid var(--border);
  background: var(--surface-subtle);
  padding: 0 9px;
}

.session-picker {
  position: relative;
  min-width: 0;
}

.session-picker > button {
  display: grid;
  width: 100%;
  height: 30px;
  cursor: pointer;
  grid-template-columns: 7px minmax(0, 1fr) 14px;
  align-items: center;
  gap: 6px;
  border: 1px solid var(--border);
  border-radius: 6px;
  color: var(--text-secondary);
  background: var(--surface);
  padding: 0 7px;
  font: inherit;
  font-size: 9px;
  text-align: left;
}

.session-picker > button span:nth-child(2) {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.session-status {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: var(--text-muted);
}

.session-status--running {
  background: var(--brand);
  box-shadow: 0 0 0 3px var(--brand-soft);
}

.session-status--waiting_approval {
  background: var(--warning);
  box-shadow: 0 0 0 3px var(--warning-soft);
}

.session-menu {
  position: absolute;
  z-index: 50;
  top: 35px;
  left: 0;
  width: min(250px, 78vw);
  border: 1px solid var(--border-strong);
  border-radius: 7px;
  background: var(--surface);
  box-shadow: var(--floating-shadow);
  padding: 4px;
}

.session-menu button {
  display: flex;
  width: 100%;
  min-height: 43px;
  cursor: pointer;
  align-items: center;
  justify-content: space-between;
  gap: 7px;
  border: 0;
  border-radius: 5px;
  color: var(--text-secondary);
  background: transparent;
  padding: 6px 8px;
  text-align: left;
}

.session-menu button:hover,
.session-menu button.active {
  color: var(--brand-strong);
  background: var(--brand-soft);
}

.session-menu strong,
.session-menu small {
  display: block;
}

.session-menu strong {
  font-size: 10px;
}

.session-menu small {
  margin-top: 3px;
  color: var(--text-muted);
  font-size: 8px;
}

.session-menu .new-session-row {
  min-height: 32px;
  justify-content: flex-start;
  border-top: 1px solid var(--border);
  border-radius: 0 0 5px 5px;
  margin-top: 3px;
}

.model-picker {
  display: flex;
  height: 30px;
  align-items: center;
  gap: 5px;
  border: 1px solid var(--border);
  border-radius: 6px;
  background: var(--surface);
  padding: 0 6px;
}

.model-picker span {
  color: var(--text-muted);
  font-family: var(--font-mono);
  font-size: 7px;
}

.model-picker select {
  max-width: 88px;
  border: 0;
  color: var(--text-secondary);
  background: transparent;
  font: inherit;
  font-size: 8px;
  outline: 0;
}

.agent-tabs {
  display: grid;
  height: 40px;
  flex: 0 0 auto;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  border-bottom: 1px solid var(--border);
  background: var(--surface);
  padding: 0 8px;
}

.agent-tabs button {
  position: relative;
  display: flex;
  cursor: pointer;
  align-items: center;
  justify-content: center;
  gap: 5px;
  border: 0;
  color: var(--text-muted);
  background: transparent;
  font: inherit;
  font-size: 10px;
}

.agent-tabs button::after {
  position: absolute;
  right: 12px;
  bottom: -1px;
  left: 12px;
  height: 2px;
  border-radius: 2px 2px 0 0;
  background: transparent;
  content: '';
}

.agent-tabs button.active {
  color: var(--brand-strong);
  font-weight: 650;
}

.agent-tabs button.active::after {
  background: var(--brand);
}

.agent-tabs b {
  display: grid;
  width: 14px;
  height: 14px;
  place-items: center;
  border-radius: 7px;
  color: #ffffff;
  background: var(--warning);
  font-size: 8px;
}

.agent-stream {
  min-height: 0;
  flex: 1;
  overflow-y: auto;
  overscroll-behavior: contain;
  padding: 0 13px 22px;
}

.scope-line {
  display: flex;
  height: 35px;
  align-items: center;
  justify-content: space-between;
  border-bottom: 1px solid var(--border);
  color: var(--text-muted);
  font-size: 8px;
}

.scope-line span {
  display: flex;
  align-items: center;
  gap: 3px;
}

.runtime-unavailable {
  display: flex;
  align-items: center;
  gap: 9px;
  margin: 12px 0 4px;
  border: 1px solid var(--warning-border);
  border-radius: 7px;
  background: var(--warning-soft);
  padding: 9px;
}

.runtime-unavailable > span {
  display: grid;
  width: 30px;
  height: 30px;
  flex: 0 0 auto;
  place-items: center;
  border-radius: 6px;
  color: var(--warning-strong);
  background: var(--surface);
}

.runtime-unavailable strong,
.runtime-unavailable small {
  display: block;
}

.runtime-unavailable strong {
  color: var(--text);
  font-size: 10px;
}

.runtime-unavailable small {
  margin-top: 3px;
  color: var(--text-secondary);
  font-size: 8px;
}

button:disabled,
select:disabled,
textarea:disabled {
  cursor: not-allowed;
  opacity: 0.5;
}

.agent-message {
  border-bottom: 1px solid var(--border-soft);
  padding: 13px 0 11px;
}

.agent-message > header {
  display: flex;
  height: 24px;
  align-items: center;
  gap: 6px;
}

.assistant-avatar,
.system-avatar {
  width: 24px;
  height: 24px;
}

.system-avatar {
  color: var(--text-secondary);
  background: var(--surface-muted);
}

.agent-message > header strong {
  color: var(--text-secondary);
  font-size: 10px;
}

.agent-message > header time {
  margin-left: auto;
  color: var(--text-muted);
  font-size: 8px;
}

.agent-message--operator .agent-parts {
  margin-left: 30px;
  border-left: 2px solid var(--brand-border);
  padding-left: 9px;
}

.agent-parts {
  margin-top: 4px;
}

.agent-thinking {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 13px 0;
  color: var(--text-muted);
}

.agent-thinking > span:nth-child(2) {
  display: flex;
  gap: 3px;
}

.agent-thinking i {
  width: 4px;
  height: 4px;
  border-radius: 50%;
  background: var(--brand);
  animation: thinking 1.1s ease-in-out infinite;
}

.agent-thinking i:nth-child(2) {
  animation-delay: 120ms;
}

.agent-thinking i:nth-child(3) {
  animation-delay: 240ms;
}

.agent-thinking small {
  font-size: 9px;
}

.agent-empty,
.run-empty {
  display: flex;
  min-height: 240px;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 10px;
  color: var(--text-muted);
}

.agent-empty strong,
.run-empty strong {
  color: var(--text-secondary);
  font-size: 11px;
}

.quick-prompts {
  display: flex;
  gap: 6px;
}

.quick-prompts button {
  cursor: pointer;
  border: 1px solid var(--border);
  border-radius: 6px;
  color: var(--text-secondary);
  background: var(--surface);
  padding: 6px 8px;
  font-size: 9px;
}

.agent-composer {
  min-height: 120px;
  flex: 0 0 auto;
  border-top: 1px solid var(--border-strong);
  background: var(--surface);
  padding: 7px 10px 8px;
}

.context-chip {
  display: flex;
  width: fit-content;
  max-width: 100%;
  height: 20px;
  align-items: center;
  gap: 4px;
  border-radius: 4px;
  color: var(--brand-strong);
  background: var(--brand-soft);
  padding: 0 6px;
  font-size: 8px;
}

.context-chip span {
  margin-left: 3px;
  color: var(--text-muted);
}

.agent-composer textarea {
  display: block;
  width: 100%;
  height: 57px;
  resize: none;
  border: 0;
  color: var(--text);
  background: transparent;
  padding: 8px 3px 4px;
  font: inherit;
  font-size: 11px;
  line-height: 1.5;
  outline: 0;
}

.agent-composer textarea::placeholder {
  color: var(--text-muted);
}

.agent-composer-footer {
  display: flex;
  height: 27px;
  align-items: center;
  justify-content: space-between;
}

.agent-composer-footer > div {
  display: flex;
  gap: 2px;
}

.prompt-send,
.stop-button {
  display: grid;
  width: 34px;
  height: 28px;
  cursor: pointer;
  place-items: center;
  border: 0;
  border-radius: 6px;
}

.prompt-send {
  color: #ffffff;
  background: var(--brand);
}

.prompt-send:disabled {
  cursor: not-allowed;
  opacity: 0.4;
}

.stop-button {
  color: var(--danger);
  background: var(--danger-soft);
}

.run-view,
.settings-view {
  min-height: 0;
  flex: 1;
  overflow-y: auto;
}

.run-heading {
  display: flex;
  align-items: flex-end;
  justify-content: space-between;
  border-bottom: 1px solid var(--border);
  padding: 17px 15px 13px;
}

.run-heading > div > span,
.settings-intro > div > span {
  color: var(--brand-strong);
  font-family: var(--font-mono);
  font-size: 8px;
  font-weight: 700;
}

.run-heading h3,
.settings-intro h3 {
  margin: 4px 0 0;
  color: var(--text);
  font-size: 17px;
  font-weight: 720;
}

.run-status {
  display: inline-flex;
  height: 23px;
  align-items: center;
  gap: 5px;
  border-radius: 5px;
  color: var(--warning-strong);
  background: var(--warning-soft);
  padding: 0 7px;
  font-size: 9px;
  font-weight: 650;
}

.run-status > span {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: var(--warning);
}

.run-status--completed {
  color: var(--success-strong);
  background: var(--success-soft);
}

.run-status--completed > span {
  background: var(--success);
}

.run-metrics {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  border-bottom: 1px solid var(--border);
  background: var(--surface);
}

.run-metrics > div {
  display: flex;
  min-width: 0;
  height: 58px;
  align-items: center;
  gap: 6px;
  border-right: 1px solid var(--border);
  color: var(--brand);
  padding: 0 8px;
}

.run-metrics > div:last-child {
  border-right: 0;
}

.run-metrics small,
.run-metrics strong {
  display: block;
  white-space: nowrap;
}

.run-metrics small {
  color: var(--text-muted);
  font-size: 7px;
}

.run-metrics strong {
  margin-top: 2px;
  color: var(--text);
  font-size: 10px;
}

.run-section,
.settings-section {
  border-bottom: 1px solid var(--border);
  padding: 14px 15px;
}

.section-label {
  margin-bottom: 10px;
  color: var(--text-muted);
  font-size: 8px;
  font-weight: 720;
}

.trigger-message {
  display: flex;
  align-items: flex-start;
  gap: 9px;
  border-left: 2px solid var(--brand);
  background: var(--surface-subtle);
  padding: 9px;
}

.trigger-message > div {
  min-width: 0;
}

.trigger-message strong {
  color: var(--text-secondary);
  font-size: 10px;
}

.trigger-message p {
  margin: 4px 0 0;
  color: var(--text);
  font-size: 10px;
  line-height: 1.55;
}

.run-details dl {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 10px 16px;
  margin: 0;
}

.run-details dl div {
  min-width: 0;
}

.run-details dt {
  color: var(--text-muted);
  font-size: 8px;
}

.run-details dd {
  overflow: hidden;
  margin: 3px 0 0;
  color: var(--text-secondary);
  font-size: 10px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.run-timeline {
  margin: 0;
  padding: 0;
  list-style: none;
}

.run-timeline li {
  position: relative;
  display: grid;
  min-height: 51px;
  grid-template-columns: 22px minmax(0, 1fr) auto;
  gap: 7px;
}

.run-timeline li:not(:last-child)::before {
  position: absolute;
  top: 20px;
  bottom: -1px;
  left: 10px;
  width: 1px;
  background: var(--border-strong);
  content: '';
}

.step-marker {
  position: relative;
  z-index: 1;
  display: grid;
  width: 21px;
  height: 21px;
  place-items: center;
  border: 1px solid var(--success-border);
  border-radius: 50%;
  color: var(--success-strong);
  background: var(--success-soft);
}

.step-marker > span {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: var(--warning);
}

.step--waiting .step-marker {
  border-color: var(--warning-border);
  background: var(--warning-soft);
}

.run-timeline strong {
  display: block;
  color: var(--text);
  font-size: 10px;
}

.run-timeline p {
  margin: 3px 0 0;
  color: var(--text-muted);
  font-size: 8px;
}

.run-timeline time {
  color: var(--text-muted);
  font-family: var(--font-mono);
  font-size: 8px;
}

.settings-intro {
  display: flex;
  align-items: center;
  justify-content: space-between;
  border-bottom: 1px solid var(--border);
  padding: 16px 15px;
}

.switch-control input {
  position: absolute;
  opacity: 0;
}

.switch-control span {
  position: relative;
  display: block;
  width: 34px;
  height: 19px;
  cursor: pointer;
  border-radius: 10px;
  background: var(--border-strong);
  transition: background 150ms ease;
}

.switch-control span::after {
  position: absolute;
  top: 3px;
  left: 3px;
  width: 13px;
  height: 13px;
  border-radius: 50%;
  background: #ffffff;
  box-shadow: 0 1px 3px rgb(0 0 0 / 20%);
  content: '';
  transition: transform 150ms ease;
}

.switch-control input:checked + span {
  background: var(--brand);
}

.switch-control input:checked + span::after {
  transform: translateX(15px);
}

.section-heading {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 11px;
  color: var(--brand);
}

.section-heading strong,
.section-heading small {
  display: block;
}

.section-heading strong {
  color: var(--text);
  font-size: 10px;
}

.section-heading small {
  margin-top: 2px;
  color: var(--text-muted);
  font-family: var(--font-mono);
  font-size: 7px;
}

.form-row,
.range-row,
.toggle-row {
  display: flex;
  min-height: 38px;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  border-top: 1px solid var(--border-soft);
  color: var(--text-secondary);
  font-size: 9px;
}

.form-row select {
  max-width: 180px;
  height: 27px;
  border: 1px solid var(--border);
  border-radius: 5px;
  color: var(--text-secondary);
  background: var(--surface);
  padding: 0 6px;
  font: inherit;
  font-size: 9px;
}

.segmented-control {
  display: grid;
  width: 126px;
  height: 27px;
  grid-template-columns: repeat(3, 1fr);
  border: 1px solid var(--border);
  border-radius: 5px;
  background: var(--surface-muted);
  padding: 2px;
}

.segmented-control button {
  cursor: pointer;
  border: 0;
  border-radius: 3px;
  color: var(--text-muted);
  background: transparent;
  font-size: 8px;
}

.segmented-control button.active {
  color: var(--brand-strong);
  background: var(--surface);
  box-shadow: 0 1px 3px rgb(24 48 53 / 10%);
}

.range-row {
  display: block;
  padding: 9px 0;
}

.range-row > span {
  display: flex;
  justify-content: space-between;
}

.range-row strong {
  color: var(--brand-strong);
  font-size: 9px;
}

.range-row input {
  width: 100%;
  margin-top: 8px;
  accent-color: var(--brand);
}

.toggle-row {
  cursor: pointer;
}

.toggle-row > span strong,
.toggle-row > span small {
  display: block;
}

.toggle-row > span strong {
  color: var(--text-secondary);
  font-size: 9px;
}

.toggle-row > span small {
  margin-top: 2px;
  color: var(--text-muted);
  font-size: 8px;
}

.toggle-row input {
  width: 15px;
  height: 15px;
  accent-color: var(--brand);
}

.tool-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 6px;
}

.tool-grid button {
  display: grid;
  min-width: 0;
  min-height: 45px;
  cursor: pointer;
  grid-template-columns: 18px minmax(0, 1fr) 13px;
  align-items: center;
  gap: 6px;
  border: 1px solid var(--border);
  border-radius: 6px;
  color: var(--text-muted);
  background: var(--surface);
  padding: 6px 7px;
  text-align: left;
}

.tool-grid button.active {
  color: var(--brand-strong);
  border-color: var(--brand-border);
  background: var(--brand-soft);
}

.tool-grid strong,
.tool-grid small {
  display: block;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.tool-grid strong {
  color: var(--text-secondary);
  font-size: 9px;
}

.tool-grid small {
  margin-top: 2px;
  color: var(--text-muted);
  font-size: 7px;
}

.settings-footer {
  display: flex;
  height: 48px;
  align-items: center;
  justify-content: space-between;
  color: var(--text-muted);
  padding: 0 15px;
  font-size: 8px;
}

.settings-footer span,
.save-button {
  display: flex;
  align-items: center;
  gap: 5px;
}

.save-button {
  height: 29px;
  cursor: pointer;
  border: 0;
  border-radius: 5px;
  color: #ffffff;
  background: var(--brand);
  padding: 0 10px;
  font-size: 9px;
  font-weight: 650;
}

@keyframes thinking {
  0%,
  100% {
    opacity: 0.35;
    transform: translateY(0);
  }
  50% {
    opacity: 1;
    transform: translateY(-2px);
  }
}

@media (max-width: 1280px) {
  .model-picker span {
    display: none;
  }

  .model-picker select {
    max-width: 76px;
  }
}

@media (max-width: 860px) {
  .agent-console {
    border-left: 0;
  }

  .agent-header {
    height: 60px;
    padding: 0 10px;
  }

  .mobile-back {
    display: grid;
  }

  .desktop-collapse {
    display: none;
  }

  .agent-context-bar {
    height: 48px;
  }

  .agent-tabs {
    height: 43px;
  }

  .agent-stream {
    padding-right: 12px;
    padding-left: 12px;
  }

  .agent-composer {
    min-height: 116px;
    padding-bottom: max(8px, env(safe-area-inset-bottom));
  }

  .settings-view,
  .run-view {
    padding-bottom: 10px;
  }
}
</style>

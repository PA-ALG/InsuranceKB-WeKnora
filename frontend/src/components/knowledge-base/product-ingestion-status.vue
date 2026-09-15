<script setup lang="ts">
import { computed, onUnmounted, ref, watch } from 'vue'
import { getProductIngestion, listProductIngestions, retryProductFields, retryProductProcessing, type ProductIngestionRun } from '@/api/product-ingestion'

const props = defineProps<{ knowledgeBaseId: string; refreshToken?: number }>()
const runs = ref<ProductIngestionRun[]>([])
const loading = ref(false)
const error = ref('')
const selection = ref<Record<string, string[]>>({})
const retrying = ref<Record<string, boolean>>({})
const now = ref(Date.now())
let generation = 0
let pollTimer: ReturnType<typeof setTimeout> | undefined
let clockTimer: ReturnType<typeof setInterval> | undefined
const terminal = (state: string) => ['succeeded', 'partial_success', 'failed', 'needs_confirmation'].includes(state)
const active = computed(() => runs.value.filter(run => !terminal(run.state)))
const stateNames: Record<string, string> = { created: '已接收', uploading: '接收材料', accepting_uploads: '接收材料', waiting_sources: '等待材料解析', awaiting_sources: '等待材料解析', processing: '处理中', running: '处理中', succeeded: '已完成', partial_success: '部分完成', failed: '处理失败', needs_confirmation: '需要确认', queued: '等待处理', leased: '等待执行', retry_wait: '等待恢复', awaiting_human: '需要确认', blocked: '处理失败', dead_letter: '处理失败', pending: '等待处理', skipped: '已跳过' }
const stageNames: Record<string, string> = { uploads: '接收材料', identity: '归并产品', field_plan: '安排字段任务', synthesis: '整理已验证结果', verify: '检索与证据检查', upload: '接收材料', uploading: '接收材料', source: '解析材料', sources: '解析材料', parsing: '解析材料', routing: '识别产品', schema: '归并字段', extract: '抽取字段', extraction: '抽取字段', validation: '校验字段', compilation: '编译知识', compile: '编译知识', review: '自动审核', publish: '发布知识', publication: '发布知识' }
const sourcePhaseNames: Record<string, string> = { docreader: '读取与解析', chunking: '文本分段', embedding: '向量化', 'postprocess.summary': '生成摘要' }
stageNames.checkpoint = '检查已有结果'
const sourceStateNames: Record<string, string> = { done: '已完成', failed: '失败', skipped: '已跳过', cancelled: '已取消' }
const outcomeNames = { verified: '已验证', not_provided: '材料未提供', extraction_failed: '抽取失败' }
const count = (value?: number | null) => typeof value === 'number' && Number.isInteger(value) && value >= 0 ? value : '—'
const discoveryNames = { NOT_EXECUTED: '未执行', FAILED: '发现失败', PENDING: '待确认', REJECTED: '未通过', EMPTY: '未发现有效新知识', ACCEPTED: '已通过检查' }
function discoveryPublished(run: ProductIngestionRun): boolean {
  return run.discovery_summary?.state === 'ACCEPTED' && run.discovery_summary.published_confirmed === true
    && ['succeeded', 'partial_success'].includes(run.state) && !!run.finished_at
    && !!run.stages?.some(stage => stage.name === 'verify' && stage.state === 'succeeded' && !!stage.finished_at)
}
const timestamp = (value?: string | null) => value ? Date.parse(value) : NaN
function duration(start?: string | null, end?: string | null, stopped = false): string {
  const from = timestamp(start)
  const to = end ? timestamp(end) : stopped ? NaN : now.value
  if (!Number.isFinite(from) || !Number.isFinite(to) || to < from) return '—'
  const seconds = Math.floor((to - from) / 1000)
  return seconds < 60 ? `${seconds} 秒` : `${Math.floor(seconds / 60)} 分 ${seconds % 60} 秒`
}
function publishedLink(run: ProductIngestionRun): string | undefined {
  const url = run.published_url
  if (!url || !run.wiki_knowledge_base_id || /[\\\s\u0000-\u001f]/.test(url)) return
  const prefix = `/platform/knowledge-bases/${encodeURIComponent(run.wiki_knowledge_base_id)}`
  try {
    const parsed = new URL(url, 'https://platform.invalid')
    if (!url.startsWith(`${prefix}/`) && !url.startsWith(`${prefix}?`) && !url.startsWith(`${prefix}#`) && url !== prefix) return
    if (parsed.origin !== 'https://platform.invalid' || parsed.pathname !== url.split(/[?#]/)[0]) return
    const suffix = parsed.pathname.slice(prefix.length)
    if (!/^(?:\/schema-wiki(?:\/concept-pages\/[^/%]+|\/entities\/[^/%]+\/(?:overview|free-wiki|sections\/[^/%]+|fields\/[^/%]+))?)?$/.test(suffix)) return
    return url
  } catch { return }
}
function stopTimers() {
  clearTimeout(pollTimer)
  clearInterval(clockTimer)
  pollTimer = undefined
  clockTimer = undefined
}
function schedule() {
  stopTimers()
  if (!active.value.length) return
  now.value = Date.now()
  clockTimer = setInterval(() => { now.value = Date.now() }, 1000)
  const current = generation
  pollTimer = setTimeout(() => void poll(current), 2000)
}
async function poll(current: number) {
  const kb = props.knowledgeBaseId
  const results = await Promise.allSettled(active.value.map(run => getProductIngestion(kb, run.run_id)))
  if (current !== generation) return
  let failed = false
  for (const result of results) {
    if (result.status === 'rejected') { failed = true; continue }
    const index = runs.value.findIndex(run => run.run_id === result.value.run_id)
    if (index >= 0) runs.value[index] = result.value
  }
  error.value = failed ? '暂时无法刷新进度，平台任务仍在后台执行。' : ''
  schedule()
}
async function reload() {
  const current = ++generation
  stopTimers()
  loading.value = true
  error.value = ''
  try {
    const result = await listProductIngestions(props.knowledgeBaseId)
    if (current !== generation) return
    runs.value = result
    for (const run of result) selection.value[run.run_id] ??= []
    schedule()
  } catch {
    if (current === generation) {
      error.value = '无法读取产品任务，请刷新重试。'
      schedule()
    }
  } finally { if (current === generation) loading.value = false }
}
async function retry(run: ProductIngestionRun) {
  const keys = (selection.value[run.run_id] || []).filter(key => run.fields?.some(field => field.field_key === key && field.outcome === 'extraction_failed'))
  if (!keys.length || retrying.value[run.run_id] || !terminal(run.state)) return
  const current = generation
  retrying.value[run.run_id] = true
  try {
    const next = await retryProductFields(props.knowledgeBaseId, run.run_id, keys)
    if (current !== generation) return
    runs.value = [next, ...runs.value.filter(item => item.run_id !== next.run_id)]
    selection.value[next.run_id] = []
    selection.value[run.run_id] = []
    error.value = ''
    schedule()
  } catch {
    if (current === generation) error.value = '未能确认重试任务，请刷新任务列表后检查。'
  } finally { if (current === generation) retrying.value[run.run_id] = false }
}
const recoverable = (run: ProductIngestionRun) => ['failed', 'needs_confirmation'].includes(run.state) && run.can_retry_processing === true && Number.isSafeInteger(run.version) && (run.version ?? 0) > 0
async function retryProcessing(run: ProductIngestionRun) {
  if (!recoverable(run) || retrying.value[run.run_id]) return
  const current = generation
  retrying.value[run.run_id] = true
  try {
    const next = await retryProductProcessing(props.knowledgeBaseId, run.run_id, run.version!)
    if (current !== generation) return
    runs.value = [next, ...runs.value.filter(item => item.run_id !== next.run_id)]
    selection.value[next.run_id] = []
    error.value = ''
    schedule()
  } catch {
    if (current === generation) error.value = '未能确认恢复任务，请刷新任务列表后检查。'
  } finally { if (current === generation) retrying.value[run.run_id] = false }
}
watch(() => [props.knowledgeBaseId, props.refreshToken], (_next, previous) => {
  if (!previous || previous[0] !== props.knowledgeBaseId) {
    runs.value = []
    selection.value = {}
    retrying.value = {}
  }
  if (props.knowledgeBaseId) void reload()
  else { generation++; stopTimers() }
}, { immediate: true })
onUnmounted(() => { generation++; stopTimers() })
</script>

<template>
  <section class="product-ingestion-status" aria-label="产品处理任务">
    <header>
      <div><h3>产品处理任务</h3><p>上传后由平台继续处理，关闭页面不影响任务。</p></div>
      <button type="button" :disabled="loading" @click="reload">刷新</button>
    </header>
    <p v-if="error" role="alert">{{ error }}</p>
    <p v-if="!runs.length">{{ loading ? '正在读取任务…' : '上传产品原始材料后，可在这里查看进度。' }}</p>
    <article v-for="run in runs" :key="run.run_id" data-testid="product-run">
      <div class="run-heading">
        <strong :class="['run-state', run.state]">{{ stateNames[run.state] || run.state }}</strong>
        <span v-if="run.stage">{{ stageNames[run.stage] || run.stage }}</span>
        <span data-testid="run-duration">耗时 {{ duration(run.started_at, run.finished_at, terminal(run.state)) }}</span>
        <a v-if="publishedLink(run)" :href="publishedLink(run)">查看已发布产品</a>
      </div>
      <p class="run-id">任务 {{ run.run_id }}</p>
      <p v-if="run.reason">{{ run.reason }}</p>
      <p data-testid="counts">成功 {{ count(run.counts?.success_count) }} · 材料未提供 {{ count(run.counts?.missing_count) }} · 失败 {{ count(run.counts?.failure_count) }} · 模型调用 {{ count(run.model_call_count) }}<span v-if="run.model_call_count_complete === false">（已记录，部分阶段统计尚未齐全）</span><span v-if="run.reused_model_call_count !== undefined"> · 复用调用 {{ count(run.reused_model_call_count) }}</span></p>
      <div data-testid="discovery-status">
        <p><strong>Schema 外知识发现：</strong><template v-if="discoveryPublished(run)">已发布 {{ count(run.discovery_summary?.counts.published) }} 项知识内容（页面或概念）</template><template v-else>{{ discoveryNames[run.discovery_summary?.state || 'NOT_EXECUTED'] || '发现状态待核对' }}</template><span v-if="run.discovery_summary?.reused"> · 复用已有发现结果</span></p>
        <template v-if="run.discovery_summary && run.discovery_summary.state !== 'NOT_EXECUTED'">
          <p>新发现提议 {{ count(run.discovery_summary.counts.proposed_new) }} · 已有知识重复 {{ count(run.discovery_summary.counts.duplicate) }} · 更新提议 {{ count(run.discovery_summary.counts.update_proposal) }} · 未通过 {{ count(run.discovery_summary.counts.rejected) }}</p>
          <p v-if="run.discovery_summary.coverage">材料范围 {{ count(run.discovery_summary.coverage.material_count) }} 份 · 本次提供 {{ count(run.discovery_summary.coverage.offered_chars) }} 字 · 未覆盖 {{ count(run.discovery_summary.coverage.omitted_chars) }} 字<span v-if="!run.discovery_summary.coverage.complete">（仅检查所提供内容）</span></p>
          <p v-else>发现范围尚未记录</p>
          <p v-if="run.discovery_summary.reason_codes.length">原因：{{ run.discovery_summary.reason_codes.join('、') }}</p>
        </template>
      </div>
      <details v-if="run.reused_stages?.length" data-testid="reused-stages">
        <summary>已复用的处理结果（{{ run.reused_stages.length }} 个阶段）</summary>
        <table>
          <thead><tr><th>处理阶段</th><th>原结果</th><th>原任务耗时</th><th>成功</th><th>未提供</th><th>失败</th></tr></thead>
          <tbody><tr v-for="stage in run.reused_stages" :key="`${stage.run_id}:${stage.stage_key}`">
            <td>{{ stageNames[stage.stage_key] || stage.stage_key }}</td>
            <td>已复用 · {{ stateNames[stage.state] || stage.state }}</td>
            <td>{{ duration(stage.started_at, stage.finished_at, true) }}</td>
            <td>{{ count(stage.success_count) }}</td><td>{{ count(stage.missing_count) }}</td><td>{{ count(stage.failure_count) }}</td>
          </tr></tbody>
        </table>
      </details>
      <div v-if="run.stages?.length" class="stages">
        <table>
          <thead><tr><th>处理阶段</th><th>状态</th><th>耗时</th><th>成功</th><th>未提供</th><th>失败</th></tr></thead>
          <tbody>
            <tr v-for="stage in run.stages" :key="stage.name">
              <td>{{ stageNames[stage.name] || stage.name }}</td>
              <td>{{ stateNames[stage.state] || stage.state }}</td>
              <td>{{ duration(stage.started_at, stage.finished_at, terminal(run.state) || terminal(stage.state) || stage.state === 'skipped') }}</td>
              <td>{{ count(stage.success_count) }}</td><td>{{ count(stage.missing_count) }}</td><td>{{ count(stage.failure_count) }}</td>
            </tr>
          </tbody>
        </table>
      </div>
      <details v-if="run.source_processing?.materials.length">
        <summary>原材料解析记录（实际耗时）</summary>
        <div v-for="material in run.source_processing.materials" :key="material.knowledge_id">
          <p>{{ material.file_name || material.knowledge_id }}<span v-if="material.reused"> · 复用已有解析</span> · 模型调用尝试 {{ count(material.counts?.attempts) }}</p>
          <table><thead><tr><th>阶段</th><th>结果与耗时</th></tr></thead><tbody>
            <tr v-for="phase in material.phases" :key="phase.phase">
              <td>{{ sourcePhaseNames[phase.phase] || phase.phase }}</td>
              <td v-if="!phase.recorded">未记录</td>
              <td v-else><div v-for="occurrence in phase.occurrences" :key="occurrence.occurrence">{{ sourceStateNames[occurrence.status] || occurrence.status }} · {{ (occurrence.duration_ms / 1000).toFixed(1) }} 秒</div></td>
            </tr>
          </tbody></table>
        </div>
      </details>
      <details v-if="run.fields?.length">
        <summary>字段处理结果（{{ run.fields.length }}）</summary>
        <ul>
          <li v-for="field in run.fields" :key="field.field_key">
            <label v-if="field.outcome === 'extraction_failed' && terminal(run.state)">
              <input v-model="selection[run.run_id]" type="checkbox" :value="field.field_key" :disabled="retrying[run.run_id]">
              {{ field.field_key }}
            </label>
            <span v-else>{{ field.field_key }}</span>
            <span>{{ outcomeNames[field.outcome] }}<template v-if="field.reason"> · {{ field.reason }}</template></span>
          </li>
        </ul>
      </details>
      <div v-if="recoverable(run)">
        <p>复用已完成的解析，由平台重新检查来源并继续处理。</p>
        <button type="button" data-testid="retry-processing" :disabled="retrying[run.run_id]" @click="retryProcessing(run)">
          {{ retrying[run.run_id] ? '正在提交…' : '恢复处理' }}
        </button>
      </div>
      <button v-if="terminal(run.state) && run.fields?.some(field => field.outcome === 'extraction_failed')"
        type="button" data-testid="retry-fields"
        :disabled="!selection[run.run_id]?.length || retrying[run.run_id]" @click="retry(run)">
        {{ retrying[run.run_id] ? '正在提交…' : '重试所选失败字段' }}
      </button>
    </article>
  </section>
</template>

<style scoped>
.product-ingestion-status { margin: 0 24px 20px; padding: 20px; border: 1px solid var(--td-component-border, #e5e7eb); border-radius: 10px; color: var(--td-text-color-primary, #20242b); background: var(--td-bg-color-container, #fff); }
header, .run-heading { display: flex; align-items: center; flex-wrap: wrap; gap: 14px; }
header { justify-content: space-between; }
h3 { margin: 0; font-size: 16px; }
p { margin: 8px 0; font-size: 13px; }
header p, .run-id { color: var(--td-text-color-secondary, #667085); }
article { border-top: 1px solid var(--td-component-border, #e5e7eb); margin-top: 16px; padding-top: 16px; }
.run-heading { font-size: 13px; }
.run-id { overflow-wrap: anywhere; }
.run-state { padding: 4px 8px; border-radius: 5px; background: var(--td-bg-color-secondarycontainer, #f3f4f6); }
.succeeded { color: #13804a; } .partial_success, .needs_confirmation { color: #976200; } .failed, [role=alert] { color: #bf3535; }
.stages { overflow-x: auto; margin: 12px 0; }
table { width: 100%; text-align: left; border-collapse: collapse; font-size: 13px; }
th, td { padding: 8px 12px; border-bottom: 1px solid var(--td-component-border, #e5e7eb); white-space: nowrap; }
summary { cursor: pointer; font-size: 13px; margin: 12px 0; }
ul { padding: 0; list-style: none; } li { display: flex; gap: 12px; flex-wrap: wrap; margin: 8px 0; font-size: 13px; overflow-wrap: anywhere; }
input { margin-right: 6px; } button { padding: 6px 12px; border: 1px solid var(--td-component-border, #d1d5db); border-radius: 6px; background: var(--td-bg-color-container, #fff); color: inherit; cursor: pointer; }
button:disabled { opacity: .5; cursor: default; } a { color: var(--td-brand-color, #2563eb); }
</style>

<script setup lang="ts">
import { computed, ref, shallowRef, watch } from 'vue'
import { useRoute } from 'vue-router'
import { readConceptPage830G2, conceptCitationTransport830G2,
  type ConceptSession830G2, type ConceptMember830G2 } from '@/api/schema-wiki/conceptFreeWiki830G2'
import {
  loadBatchConceptActive830G3,
  loadBatchConceptPreparation830G3,
  readBatchConceptPage830G3,
  type BatchConceptMember830G3,
  type BatchConceptPage830G3,
} from '@/api/schema-wiki/batchConcept830G3'
import { buildSchemaCitationPreviewRequest } from '@/api/schema-wiki'
import ConceptCitationViewer830G2 from '@/components/schema-wiki/ConceptCitationViewer830G2.vue'
import { createPdfJsPort } from '@/components/schema-wiki/pdfJsPort'
import SettingDrawer from '@/components/settings/SettingDrawer.vue'
import { get } from '@/utils/request'
import { createSchemaWikiReadTransport, SCHEMA_WIKI_READ_TIMEOUT_MS } from '@/api/schema-wiki/readTransport'

const route = useRoute()
const session = shallowRef<ConceptSession830G2 | null>(null)
const batchPage = shallowRef<BatchConceptPage830G3 | null>(null)
const loading = ref(true)
const error = ref('')
const selected = ref<string | null>(null)
const pdfPort = createPdfJsPort()
let generation = 0
const batchSession = computed<ConceptSession830G2 | null>(() => {
  const source = batchPage.value?.session
  if (!source) return null
  return { scope: source.scope, read: {
    contract: source.read.contract, read_mode: source.read.read_mode, release_id: source.read.release_id,
    activation_epoch: source.read.activation_epoch, candidate_hash: source.read.candidate_hash,
    space_id: source.read.space_id, raw_kb_id: source.read.raw_kb_id, wiki_kb_id: source.read.wiki_kb_id,
    member: { ...source.read.member }, related_members: source.read.related_members.map(member => ({ ...member })),
    citations: source.read.citations.map(citation => ({ ...citation })),
    definition_hash: source.read.definition_hash, aggregate_hash: source.read.aggregate_hash,
  } }
})
const viewerSession = computed(() => session.value ?? batchSession.value)
const read = computed(() => session.value?.read ?? (batchPage.value ? {
  release_id: batchPage.value.session?.read.release_id ?? '',
  activation_epoch: batchPage.value.session?.read.activation_epoch ?? 0,
  member: batchPage.value.member,
  related_members: batchPage.value.relatedMembers,
  citations: batchPage.value.citations,
} : null))
const previewTransport = computed(() => viewerSession.value ? conceptCitationTransport830G2(viewerSession.value, {
  // Source verification can exceed the ordinary request timeout before PDF rendering.
  get: path => get(path, { timeout: SCHEMA_WIKI_READ_TIMEOUT_MS }),
  getBytes: async path => new Uint8Array(await get<ArrayBuffer>(path, { responseType: 'arraybuffer', timeout: SCHEMA_WIKI_READ_TIMEOUT_MS })),
}) : null)
const previewRequest = computed(() => read.value && selected.value ? buildSchemaCitationPreviewRequest({
  release_id: read.value.release_id, activation_epoch: read.value.activation_epoch,
  field_id: read.value.member.member_id, citation_id: selected.value,
}) : null)
function link(member: ConceptMember830G2 | BatchConceptMember830G3) {
  const query = batchPage.value?.directory.mode === 'g3-preparation'
    ? { preparation_id: batchPage.value.directory.preparationID }
    : { release_id: read.value?.release_id }
  return { name: 'conceptPage830G2', params: { kbId: route.params.kbId, memberId: member.member_id },
    query }
}
function stateLabel(member: ConceptMember830G2 | BatchConceptMember830G3) {
  return member.payload.state === 'unknown' ? '待补充'
    : member.payload.state === 'absent_explicitly' ? '材料明确不提供' : '材料已确认'
}
function textList(value: unknown): string[] {
  return Array.isArray(value) ? value.filter(item => typeof item === 'string') : []
}
function preparationEvidence(member: ConceptMember830G2 | BatchConceptMember830G3) {
  const value = member.payload.evidence
  if (!Array.isArray(value)) return []
  return value.filter((item): item is { page_number: number, quote: string } => typeof item === 'object' && item !== null
    && Number.isSafeInteger((item as Record<string, unknown>).page_number)
    && typeof (item as Record<string, unknown>).quote === 'string')
}
const selectedEntity = computed(() => batchPage.value?.directory.entities.find(
  entity => entity.entityID === batchPage.value?.member.owner_id,
))
function fieldByID(memberID: string) {
  return batchPage.value?.directory.members.find(member => member.member_id === memberID)
}
function routeIdentity(value: unknown): string {
  if (typeof value !== 'string' || !/^[A-Za-z0-9._:@-]+$/.test(value)
    || ['current', 'latest'].includes(value.toLowerCase())) throw new Error('INVALID_READ_MODE')
  return value
}
async function load() {
  const current = ++generation
  session.value = null; batchPage.value = null; selected.value = null; loading.value = true; error.value = ''
  try {
    const keys = Object.keys(route.query)
    const release = route.query.release_id; const preparation = route.query.preparation_id
    if (keys.some(key => !['release_id', 'preparation_id'].includes(key))
      || (release !== undefined && preparation !== undefined)) throw new Error('INVALID_READ_MODE')
    const kbID = routeIdentity(route.params.kbId); const memberID = routeIdentity(route.params.memberId)
    const transport = createSchemaWikiReadTransport(get)
    if (preparation !== undefined) {
      const directory = await loadBatchConceptPreparation830G3(kbID, routeIdentity(preparation), transport)
      const loaded = await readBatchConceptPage830G3(directory, memberID, transport)
      if (current === generation) batchPage.value = loaded
    } else if (release !== undefined) {
      const releaseID = routeIdentity(release)
      const active = await loadBatchConceptActive830G3(kbID, transport)
      if (active && active.releaseID === releaseID) {
        const loaded = await readBatchConceptPage830G3(active, memberID, transport)
        if (current === generation) batchPage.value = loaded
      } else {
        const loaded = await readConceptPage830G2(kbID, memberID, releaseID, transport)
        if (current === generation) session.value = loaded
      }
    } else {
      const loaded = await readConceptPage830G2(kbID, memberID, undefined, transport)
      if (current === generation) session.value = loaded
    }
  } catch {
    if (current === generation) error.value = '页面读取失败，请确认页面已发布且你有访问权限。'
  } finally {
    if (current === generation) loading.value = false
  }
}
watch(() => [route.params.kbId, route.params.memberId, route.query], load, { immediate: true, deep: true })
</script>

<template>
  <main class="concept-page">
    <p v-if="loading" role="status">正在读取知识页面…</p>
    <p v-else-if="error" role="alert">{{ error }}</p>
    <template v-else-if="read">
      <header>
        <span class="concept-page__label">{{ batchPage?.directory.mode === 'g3-preparation'
          ? batchPage.directory.statusLabel : read.member.kind === 'concept' ? '共享定义' : '已发布知识' }}</span>
        <h1>{{ read.member.title }}</h1>
        <p v-if="read.member.kind === 'field_assertion'" class="concept-page__meta">
          {{ selectedEntity?.displayName ?? read.member.owner_id }} · {{ stateLabel(read.member) }}
        </p>
        <p v-if="batchPage" class="concept-page__quality">已登记，尚未完成质量验收</p>
      </header>
      <article class="concept-page__body">{{ read.member.content }}</article>
      <section v-if="batchPage && read.member.kind === 'field_assertion'" aria-label="字段详情">
        <h2>字段详情</h2>
        <p v-if="read.member.payload.value !== null"><strong>取值：</strong>{{ read.member.payload.value }}</p>
        <p v-if="read.member.payload.unknown_reason"><strong>待补充原因：</strong>{{ read.member.payload.unknown_reason }}</p>
        <p v-for="condition in textList(read.member.payload.conditions)" :key="`condition-${condition}`">
          <strong>适用条件：</strong>{{ condition }}</p>
        <p v-for="exception in textList(read.member.payload.exceptions)" :key="`exception-${exception}`">
          <strong>例外：</strong>{{ exception }}</p>
        <p v-if="read.member.payload.valid_time"><strong>有效时间：</strong>{{ read.member.payload.valid_time }}</p>
      </section>
      <section v-if="batchPage?.readMode === 'preparation' && preparationEvidence(read.member).length"
        class="concept-page__sources" aria-label="原文证据">
        <h2>原文证据</h2>
        <div v-for="proof in preparationEvidence(read.member)" :key="`${proof.page_number}-${proof.quote}`">
          <p>来源记录：第 {{ proof.page_number }} 页</p><blockquote>{{ proof.quote }}</blockquote>
        </div>
        <p class="concept-page__meta">激活后可打开原件</p>
      </section>
      <section v-else-if="read.citations.length" class="concept-page__sources" aria-label="原文证据">
        <h2>原文证据</h2>
        <button v-for="citation in read.citations" :key="citation.citation_id" type="button"
          :data-testid="batchPage ? 'g3-source' : 'g2-source'" @click="selected = citation.citation_id">
          {{ batchPage ? '查看原文' : `查看第 ${citation.page_number} 页原文` }}
        </button>
      </section>
      <section v-if="batchPage && read.member.kind === 'entity_overview' && selectedEntity" aria-label="产品字段">
        <h2>产品字段</h2>
        <div v-for="section in selectedEntity.sections" :key="section.sectionKey">
          <h3>{{ section.displayName }}</h3>
          <ul class="concept-page__related">
            <li v-for="field in section.fields" :key="field.memberID">
              <RouterLink v-if="fieldByID(field.memberID)" :to="link(fieldByID(field.memberID)!)">{{ field.shortTitle }}</RouterLink>
            </li>
          </ul>
        </div>
      </section>
      <section v-if="read.related_members.length && !(batchPage && read.member.kind === 'entity_overview')" aria-label="相关知识">
        <h2>{{ read.member.kind === 'concept' ? '各实体的具体规定' : '相关知识' }}</h2>
        <ul class="concept-page__related">
          <li v-for="member in read.related_members" :key="member.member_id">
            <RouterLink :to="link(member)">{{ member.title }}</RouterLink>
            <p v-if="member.kind === 'field_assertion'" class="concept-page__meta">
              {{ member.owner_id }} · {{ member.payload.entity_version }} · {{ stateLabel(member) }}
            </p>
            <p class="concept-page__body">{{ member.content }}</p>
          </li>
        </ul>
      </section>
      <SettingDrawer v-if="previewRequest && previewTransport" :visible="selected !== null"
        title="查看原文" description="当前页面所引用的固定版本原文" icon="file" width="760px"
        :min-width="560" :max-width="1000" storage-key="setting-drawer:width:concept-source-830-g2"
        hide-footer @update:visible="visible => { if (!visible) selected = null }">
        <ConceptCitationViewer830G2 v-if="viewerSession" :key="selected!" :session="viewerSession" :citation-id="selected!"
          :preview-transport="previewTransport" :pdf-port="pdfPort" />
      </SettingDrawer>
    </template>
  </main>
</template>

<style scoped>
.concept-page { max-width: 1080px; margin: 0 auto; padding: 36px; color: var(--td-text-color-primary); }
.concept-page__label { color: var(--td-brand-color); font-size: 13px; }
h1 { margin: 8px 0 24px; font-size: 28px; }
h2 { margin: 28px 0 12px; font-size: 18px; }
.concept-page__body { white-space: pre-wrap; overflow-wrap: anywhere; line-height: 1.8; }
.concept-page__meta { color: var(--td-text-color-secondary); font-size: 13px; }
.concept-page__quality { color: var(--td-warning-color); font-weight: 600; }
.concept-page__related { list-style: none; padding: 0; }
.concept-page__related li { padding: 18px 0; border-bottom: 1px solid var(--td-component-border); }
.concept-page__related a { color: var(--td-brand-color); text-decoration: none; font-weight: 600; }
.concept-page__sources button { margin: 0 10px 8px 0; border: 1px solid var(--td-component-border);
  border-radius: 6px; padding: 8px 12px; color: var(--td-brand-color); background: transparent; cursor: pointer; }
@media (max-width: 700px) { .concept-page { padding: 20px; } }
</style>

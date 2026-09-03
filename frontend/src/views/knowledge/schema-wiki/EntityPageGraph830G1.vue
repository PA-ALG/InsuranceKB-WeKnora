<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useRoute } from 'vue-router'

import {
  buildSchemaCitationPreviewRequest,
  createSchemaWikiCitationPreviewTransport,
  type SchemaWikiCitationPreviewTransport,
} from '@/api/schema-wiki'
import {
  createEntityPageGraphPreparationCitationTransport830G1,
  readEntityPageGraphSession830G1,
} from '@/api/schema-wiki/entityPageGraph830G1.ts'
import SchemaCitationViewer from '@/components/schema-wiki/SchemaCitationViewer.vue'
import { createPdfJsPort } from '@/components/schema-wiki/pdfJsPort.ts'
import SettingDrawer from '@/components/settings/SettingDrawer.vue'
import { get } from '@/utils/request'
import type {
  EntityPageCitation830G1,
  EntityPageFieldPayload830G1,
  EntityPageGraphRead830G1,
  EntityPageSectionPayload830G1,
  EntityPageTarget830G1,
} from './entityPageGraph830G1Contract.ts'
import type { SchemaWikiScopeV1 } from './schemaWikiContract.ts'

const route = useRoute()
const loading = ref(true)
const read = ref<EntityPageGraphRead830G1 | null>(null)
const error = ref('')
const previewTransport = ref<SchemaWikiCitationPreviewTransport | null>(null)
const sourceDrawerVisible = ref(false)
const selectedCitation = ref<EntityPageCitation830G1 | null>(null)
const loadedScope = ref<SchemaWikiScopeV1 | null>(null)
const pdfPort = createPdfJsPort()

const wikiKBID = computed(() => String(route.params.kbId ?? ''))
const entityID = computed(() => String(route.params.entityId ?? ''))

const target = computed<EntityPageTarget830G1>(() => {
  if (route.name === 'entityPageSection830G1') {
    return { entityId: entityID.value, pageKind: 'section', stableKey: String(route.params.sectionKey ?? '') }
  }
  if (route.name === 'entityPageField830G1') {
    return { entityId: entityID.value, pageKind: 'field', stableKey: String(route.params.fieldKey ?? '') }
  }
  if (route.name === 'entityPageFreeWiki830G1') {
    return { entityId: entityID.value, pageKind: 'free_wiki', stableKey: 'free-wiki' }
  }
  return { entityId: entityID.value, pageKind: 'overview', stableKey: 'overview' }
})

const pinnedQuery = computed(() => read.value?.read_mode === 'pinned'
  ? { release_id: read.value.release_id }
  : read.value?.read_mode === 'preparation'
    ? { preparation_id: read.value.preparation_id }
    : {})

const fieldPayload = computed(() => read.value?.member.payload.contract === 'field-assertion-page.830.g1.v1'
  ? read.value.member.payload as EntityPageFieldPayload830G1
  : null)
const sectionPayload = computed(() => read.value?.member.payload.contract === 'entity-section-page.830.g1.v1'
  ? read.value.member.payload as EntityPageSectionPayload830G1
  : null)
const currentSection = computed(() => read.value?.profile.sections.find(
  section => section.section_key === sectionPayload.value?.section_key,
) ?? null)
const fieldCount = computed(() => read.value?.profile.sections.reduce(
  (total, section) => total + section.fields.length,
  0,
) ?? 0)
const sourceDrawerDescription = computed(() => read.value?.read_mode === 'pinned'
  ? '固定发布版本的原始证据'
  : read.value?.read_mode === 'preparation'
    ? '候选预览的原始证据'
    : '当前发布版本的原始证据')
const previewRequest = computed(() => {
  if (!read.value || !fieldPayload.value || !selectedCitation.value) return null
  return buildSchemaCitationPreviewRequest({
    release_id: read.value.release_id,
    activation_epoch: read.value.activation_epoch,
    field_id: fieldPayload.value.field_key,
    citation_id: `citation-${selectedCitation.value.join_receipt_sha256.slice(0, 24)}`,
  })
})

function entityRoute(name: string, extra: Record<string, string> = {}) {
  return {
    name,
    params: { kbId: wikiKBID.value, entityId: entityID.value, ...extra },
    query: pinnedQuery.value,
  }
}

function unknownLabel(reason: string | null): string {
  return reason === 'NOT_COVERED_BY_CURRENT_SOURCE_MATERIALS'
    ? '当前材料未提供，待后续材料补充'
    : '尚未确定'
}

function unwrapResponse(value: unknown): unknown {
  if (typeof value !== 'object' || value === null || Array.isArray(value)) {
    throw new Error('SCHEMA_WIKI_RESPONSE_INVALID')
  }
  const record = value as Record<string, unknown>
  if (record.success !== true || !('data' in record) || Object.keys(record).length !== 2) {
    throw new Error('SCHEMA_WIKI_RESPONSE_INVALID')
  }
  return record.data
}

function requestedReadIdentityFromRoute(): { releaseID?: string, preparationID?: string } {
  const keys = Object.keys(route.query)
  if (keys.some(key => key !== 'release_id' && key !== 'preparation_id')
    || keys.includes('release_id') && keys.includes('preparation_id')) {
    throw new Error('ENTITY_PAGE_GRAPH_READ_MODE_INVALID')
  }
  const release = route.query.release_id
  const preparation = route.query.preparation_id
  const exact = (value: unknown, code: string): string | undefined => {
    if (value === undefined) return undefined
    if (typeof value !== 'string' || value === '' || value !== value.trim()
      || ['current', 'latest'].includes(value.toLowerCase())) throw new Error(code)
    return value
  }
  return {
    releaseID: exact(release, 'ENTITY_PAGE_GRAPH_RELEASE_ID_INVALID'),
    preparationID: exact(preparation, 'ENTITY_PAGE_GRAPH_PREPARATION_ID_INVALID'),
  }
}

function previewIO() {
  return {
    get: async (path: string) => unwrapResponse(await get(path)),
    getBytes: async (path: string) => {
      const bytes = await get<ArrayBuffer>(path, { responseType: 'arraybuffer' })
      return new Uint8Array(bytes)
    },
  }
}

function setPreparationPreviewTransport(citation: EntityPageCitation830G1): void {
  if (read.value?.read_mode !== 'preparation' || !read.value.preparation_id || !loadedScope.value) return
  previewTransport.value = createEntityPageGraphPreparationCitationTransport830G1(
    loadedScope.value,
    read.value.preparation_id,
    read.value.entity_id,
    citation.citation_id,
    previewIO(),
  )
}

function openSources(): void {
  const first = fieldPayload.value?.citations[0]
  if (!first) return
  setPreparationPreviewTransport(first)
  if (!previewTransport.value) return
  selectedCitation.value = first
  sourceDrawerVisible.value = true
}

function selectCitation(citation: EntityPageCitation830G1): void {
  if (!fieldPayload.value?.citations.includes(citation)) return
  setPreparationPreviewTransport(citation)
  selectedCitation.value = citation
}

function closeSources(): void {
  sourceDrawerVisible.value = false
  selectedCitation.value = null
}

function updateSourceDrawerVisible(visible: boolean): void {
  if (!visible) closeSources()
}

async function load(): Promise<void> {
  const hasPinnedQuery = Object.prototype.hasOwnProperty.call(route.query, 'release_id')
  const hasPreparationQuery = Object.prototype.hasOwnProperty.call(route.query, 'preparation_id')
  loading.value = true
  read.value = null
  error.value = ''
  previewTransport.value = null
  loadedScope.value = null
  closeSources()
  try {
    const identity = requestedReadIdentityFromRoute()
    const session = await readEntityPageGraphSession830G1(
      wikiKBID.value,
      target.value,
      identity.releaseID,
      { get: path => get(path) },
      identity.preparationID,
    )
    read.value = session.read
    loadedScope.value = session.scope
    if (session.read.read_mode === 'preparation') {
      const payload = session.read.member.payload
      if (payload.contract === 'field-assertion-page.830.g1.v1' && payload.citations[0]) {
        setPreparationPreviewTransport(payload.citations[0])
      }
    } else {
      previewTransport.value = createSchemaWikiCitationPreviewTransport(session.scope, previewIO())
    }
  } catch {
    error.value = hasPinnedQuery
      ? '固定版本页面读取失败'
      : hasPreparationQuery ? '候选预览页面读取失败' : '当前版本页面读取失败'
  } finally {
    loading.value = false
  }
}

watch(() => route.fullPath, load, { immediate: true })
</script>

<template>
  <section class="entity-page-graph" data-testid="entity-page-graph-830-g1">
    <p v-if="loading" class="entity-page-graph__state" role="status">正在读取实体页面…</p>
    <p v-else-if="error" class="entity-page-graph__state entity-page-graph__state--error" role="alert">
      {{ error }}。请核对页面地址或版本标识后重试。
    </p>
    <template v-else-if="read">
      <aside class="entity-page-graph__navigation" aria-label="实体页面导航">
        <div class="entity-page-graph__entity">
          <strong>{{ read.display_name }}</strong>
          <span>{{ read.classification_display_name }}</span>
          <small>{{ read.profile.sections.length }} 个分类 · {{ fieldCount }} 个字段</small>
        </div>
        <RouterLink
          :to="entityRoute('entityPageOverview830G1')"
          :class="{ active: read.member.page_kind === 'overview' }"
        >
          产品总览
        </RouterLink>
        <section v-for="section in read.profile.sections" :key="section.section_key">
          <RouterLink
            data-testid="entity-section-link"
            :to="entityRoute('entityPageSection830G1', { sectionKey: section.section_key })"
            :class="{ active: read.member.page_kind === 'section' && read.member.stable_key === section.section_key }"
          >
            {{ section.display_name }}
          </RouterLink>
          <ul>
            <li v-for="field in section.fields" :key="field.field_key">
              <RouterLink
                :to="entityRoute('entityPageField830G1', { fieldKey: field.field_key })"
                :class="{ active: read.member.page_kind === 'field' && read.member.stable_key === field.field_key }"
              >
                <span>{{ field.short_title }}</span>
                <code>{{ field.field_key }}</code>
              </RouterLink>
            </li>
          </ul>
        </section>
        <RouterLink
          :to="entityRoute('entityPageFreeWiki830G1')"
          :class="{ active: read.member.page_kind === 'free_wiki' }"
        >
          自由知识
        </RouterLink>
      </aside>

      <main class="entity-page-graph__content">
        <header>
          <div>
            <p class="entity-page-graph__eyebrow">
              {{ read.read_mode === 'pinned' ? '固定版本' : read.read_mode === 'preparation' ? '候选预览' : '当前版本' }} · {{ read.release_id }}
            </p>
            <h1>{{ read.member.short_title }}</h1>
            <code data-testid="entity-page-namespace">{{ read.member.namespace }}</code>
          </div>
        </header>

        <div v-if="read.member.payload.contract === 'entity-overview-page.830.g1.v1'" class="entity-page-graph__overview">
          <p>{{ read.display_name }} 的结构化实体页由当前发布清单完整提供。</p>
          <dl>
            <div><dt>实体版本</dt><dd>{{ read.entity_version_id }}</dd></div>
            <div><dt>分类数量</dt><dd>{{ read.profile.sections.length }}</dd></div>
            <div><dt>字段数量</dt><dd>{{ fieldCount }}</dd></div>
          </dl>
        </div>

        <div v-else-if="sectionPayload && currentSection" class="entity-page-graph__section-page">
          <p>本分类包含 {{ currentSection.fields.length }} 个字段。</p>
          <ul>
            <li v-for="field in currentSection.fields" :key="field.field_key">
              <RouterLink :to="entityRoute('entityPageField830G1', { fieldKey: field.field_key })">
                <strong>{{ field.short_title }}</strong>
                <code>{{ field.field_key }}</code>
              </RouterLink>
            </li>
          </ul>
        </div>

        <template v-else-if="fieldPayload">
          <article class="entity-page-graph__field" :data-field-state="fieldPayload.state">
            <span class="entity-page-graph__field-state">
              {{ fieldPayload.state === 'present' ? '已提供' : fieldPayload.state === 'absent_explicitly' ? '明确不包含' : '尚未确定' }}
            </span>
            <p v-if="fieldPayload.state === 'unknown'" data-testid="entity-field-unknown" role="status">
              {{ unknownLabel(fieldPayload.unknown_reason) }}
            </p>
            <p v-else class="entity-page-graph__field-value">{{ fieldPayload.display_value }}</p>
            <div v-if="fieldPayload.citations.length && previewTransport" class="entity-page-graph__sources">
              <h2>冻结原文依据</h2>
              <button
                type="button"
                data-testid="entity-source-action"
                aria-haspopup="dialog"
                @click="openSources"
              >
                查看原文
              </button>
            </div>
          </article>
          <SettingDrawer
            v-if="fieldPayload.citations.length && previewTransport"
            :visible="sourceDrawerVisible"
            title="查看原文"
            :description="sourceDrawerDescription"
            icon="file"
            width="760px"
            :min-width="560"
            :max-width="1000"
            storage-key="setting-drawer:width:entity-field-active-source-830-g1"
            hide-footer
            @update:visible="updateSourceDrawerVisible"
          >
            <div class="entity-page-graph__source-drawer">
              <div
                v-if="fieldPayload.citations.length > 1"
                class="entity-page-graph__source-options"
                role="tablist"
                aria-label="原文来源"
              >
                <button
                  v-for="(citation, index) in fieldPayload.citations"
                  :key="citation.join_receipt_sha256"
                  type="button"
                  role="tab"
                  data-testid="entity-source-option"
                  :aria-selected="selectedCitation === citation"
                  @click="selectCitation(citation)"
                >
                  来源 {{ index + 1 }} · 第 {{ citation.page_number }} 页
                </button>
              </div>
              <SchemaCitationViewer
                v-if="selectedCitation && previewRequest && previewTransport"
                :key="selectedCitation.join_receipt_sha256"
                :request="previewRequest"
                :preview-transport="previewTransport"
                :pdf-port="pdfPort"
                @back="closeSources"
              />
            </div>
          </SettingDrawer>
        </template>

        <div v-else-if="read.member.payload.contract === 'empty-free-wiki-page.830.g1.v1'" class="entity-page-graph__empty" role="status">
          <h2>暂无自由知识条目</h2>
          <p>当前发布清单明确冻结为空。</p>
        </div>
      </main>
    </template>
  </section>
</template>

<style scoped>
.entity-page-graph { display: grid; grid-template-columns: 320px minmax(0, 1fr); min-height: calc(100vh - 64px); background: var(--td-bg-color-container); }
.entity-page-graph__state { grid-column: 1 / -1; margin: auto; color: var(--td-text-color-secondary); }
.entity-page-graph__state--error { color: var(--td-error-color); }
.entity-page-graph__navigation { overflow: auto; padding: 24px 16px; border-right: 1px solid var(--td-component-border); }
.entity-page-graph__entity { display: grid; gap: 6px; margin: 0 8px 20px; }
.entity-page-graph__entity span, .entity-page-graph__entity small { color: var(--td-text-color-secondary); }
.entity-page-graph__navigation a { display: block; padding: 8px; border-radius: 6px; color: inherit; text-decoration: none; }
.entity-page-graph__navigation a.active { background: var(--td-brand-color-light); color: var(--td-brand-color); }
.entity-page-graph__navigation section > a { margin-top: 8px; font-weight: 600; }
.entity-page-graph__navigation ul { margin: 2px 0 8px; padding-left: 16px; list-style: none; }
.entity-page-graph__navigation li span, .entity-page-graph__navigation li code { display: block; }
.entity-page-graph__navigation li code { margin-top: 2px; color: var(--td-text-color-placeholder); font-size: 11px; }
.entity-page-graph__content { min-width: 0; padding: 40px; overflow: auto; }
.entity-page-graph__content header { padding-bottom: 24px; border-bottom: 1px solid var(--td-component-border); }
.entity-page-graph__content h1 { margin: 6px 0 8px; }
.entity-page-graph__eyebrow { margin: 0; color: var(--td-text-color-secondary); font-size: 12px; }
.entity-page-graph__overview dl { display: grid; grid-template-columns: repeat(3, 1fr); gap: 12px; margin-top: 24px; }
.entity-page-graph__overview dl div { padding: 16px; border-radius: 8px; background: var(--td-bg-color-secondarycontainer); }
.entity-page-graph__overview dt { color: var(--td-text-color-secondary); }
.entity-page-graph__overview dd { margin: 8px 0 0; font-weight: 600; }
.entity-page-graph__section-page ul { display: grid; gap: 10px; padding: 0; list-style: none; }
.entity-page-graph__section-page a { display: flex; justify-content: space-between; padding: 14px; border: 1px solid var(--td-component-border); border-radius: 8px; color: inherit; text-decoration: none; }
.entity-page-graph__field { max-width: 900px; padding-top: 24px; }
.entity-page-graph__field-state { display: inline-flex; padding: 4px 10px; border-radius: 999px; background: var(--td-bg-color-secondarycontainer); }
.entity-page-graph__field-value { margin-top: 24px; white-space: pre-wrap; line-height: 1.75; }
.entity-page-graph__sources { margin-top: 32px; }
.entity-page-graph__sources button, .entity-page-graph__source-options button { border: 1px solid var(--td-component-border); border-radius: 6px; padding: 6px 10px; background: transparent; cursor: pointer; }
.entity-page-graph__source-options { display: flex; flex-wrap: wrap; gap: 8px; margin-bottom: 16px; }
.entity-page-graph__source-options button[aria-selected='true'] { border-color: var(--td-brand-color); color: var(--td-brand-color); }
.entity-page-graph__empty { padding: 64px 0; color: var(--td-text-color-secondary); text-align: center; }
@media (max-width: 900px) { .entity-page-graph { grid-template-columns: 250px minmax(0, 1fr); } .entity-page-graph__content { padding: 24px; } }
</style>

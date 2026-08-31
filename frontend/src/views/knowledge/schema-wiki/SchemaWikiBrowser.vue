<script setup lang="ts">
import { computed, ref, watch } from 'vue'

import {
  bootstrapSchemaWikiClient,
  createSchemaWikiCitationPreviewTransport,
  type SchemaWikiCitationPreviewTransport,
} from '@/api/schema-wiki'
import { get } from '@/utils/request'
import {
  parseSchemaFieldPage,
  parseSchemaWikiCurrentEntityVersion,
  type SchemaFieldPageV1,
  type SchemaRootPageV1,
} from './schemaWikiContract.ts'
import {
  assertMedicalSchema67Presentation,
  resolveSchemaWikiMvpExperience,
  type SchemaWikiMvpRuntimeConfig,
} from './schemaWikiMvpPresentation.ts'
import SchemaWikiFieldPage from './SchemaWikiFieldPage.vue'

const props = defineProps<{ knowledgeBaseId: string }>()

const MEDICAL_ENTITY_ID = 'ping-an-e-sheng-bao'
const MEDICAL_ENTITY_VERSION_ID = 'ping-an-e-sheng-bao@596-1'
const HEX_64 = /^[0-9a-f]{64}$/
const CONTROL_CHARACTER = /[\u0000-\u001f\u007f]/

interface SchemaSectionPageV1 {
  readonly section_id: string
  readonly display_name: string
  readonly ordered_field_ids: ReadonlyArray<string>
  readonly section_page_sha256: string
}

const loading = ref(false)
const status = ref<'ready' | 'not-compiled' | 'error'>('error')
const root = ref<SchemaRootPageV1 | null>(null)
const releaseId = ref<string | null>(null)
const activationEpoch = ref<number | null>(null)
const activeCitationTransport = ref<SchemaWikiCitationPreviewTransport | null>(null)
const sections = ref<ReadonlyArray<SchemaSectionPageV1>>([])
const selectedSectionId = ref<string | null>(null)
const selectedFieldId = ref<string | null>(null)
const selectedField = ref<SchemaFieldPageV1 | null>(null)
const fieldPresentation = ref<ReadonlyMap<string, string>>(new Map())

const mvpExperience = computed(() => resolveSchemaWikiMvpExperience(
  props.knowledgeBaseId,
  (window.__RUNTIME_CONFIG__ ?? {}) as SchemaWikiMvpRuntimeConfig,
))
const fieldCount = computed(() => sections.value.reduce(
  (count, section) => count + section.ordered_field_ids.length,
  0,
))

function fieldTitle(fieldId: string): string {
  const title = fieldPresentation.value.get(fieldId)
  if (!title) throw new Error('SCHEMA_WIKI_MVP_PRESENTATION_TOPOLOGY_INVALID')
  return title
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

function canonicalText(value: unknown): value is string {
  return typeof value === 'string'
    && value.length > 0
    && value.trim() === value
    && value.normalize('NFC') === value
    && !CONTROL_CHARACTER.test(value)
}

function exactKeys(value: Record<string, unknown>, keys: readonly string[]): boolean {
  const actual = Object.keys(value).sort()
  const expected = [...keys].sort()
  return actual.length === expected.length && actual.every((key, index) => key === expected[index])
}

function unwrapResponse(value: unknown): unknown {
  if (!isRecord(value) || !exactKeys(value, ['success', 'data']) || value.success !== true) {
    throw new Error('SCHEMA_WIKI_RESPONSE_INVALID')
  }
  return value.data
}

function assertConfiguredAuthority(
  domainsValue: unknown,
  taxonomyValue: unknown,
  expectedRoot: SchemaRootPageV1,
): void {
  if (!Array.isArray(domainsValue) || domainsValue.length !== 1) {
    throw new Error('SCHEMA_WIKI_DOMAIN_INVALID')
  }
  const domain = domainsValue[0]
  if (
    !isRecord(domain)
    || !exactKeys(domain, ['contract', 'domain_id', 'display_name', 'domain_sha256'])
    || domain.contract !== 'knowledge-domain.v1'
    || domain.domain_id !== expectedRoot.domain_id
    || domain.domain_sha256 !== expectedRoot.domain_sha256
    || !canonicalText(domain.display_name)
  ) {
    throw new Error('SCHEMA_WIKI_DOMAIN_INVALID')
  }
  if (
    !isRecord(taxonomyValue)
    || !exactKeys(taxonomyValue, [
      'contract', 'domain_id', 'taxonomy_version', 'previous_snapshot_sha256',
      'nodes', 'redirects', 'taxonomy_sha256',
    ])
    || taxonomyValue.contract !== 'taxonomy-snapshot.v1'
    || taxonomyValue.domain_id !== expectedRoot.domain_id
    || taxonomyValue.taxonomy_version !== expectedRoot.taxonomy_version
    || taxonomyValue.taxonomy_sha256 !== expectedRoot.taxonomy_sha256
    || !Array.isArray(taxonomyValue.nodes)
    || !Array.isArray(taxonomyValue.redirects)
  ) {
    throw new Error('SCHEMA_WIKI_TAXONOMY_INVALID')
  }
}

function parseSectionPage(value: unknown, expectedRoot: SchemaRootPageV1, sectionId: string) {
  const keys = [
    'contract', 'domain_id', 'domain_sha256', 'schema_pack_id', 'schema_version',
    'schema_pack_sha256', 'entity_id', 'entity_version_id', 'product_version_id',
    'taxonomy_version', 'taxonomy_sha256', 'section_id', 'display_name',
    'ordered_field_ids', 'section_page_sha256',
  ]
  if (
    !isRecord(value) || !exactKeys(value, keys)
    || value.contract !== 'schema-section-page.v1'
    || value.domain_id !== expectedRoot.domain_id
    || value.domain_sha256 !== expectedRoot.domain_sha256
    || value.schema_pack_id !== expectedRoot.schema_pack_id
    || value.schema_version !== expectedRoot.schema_version
    || value.schema_pack_sha256 !== expectedRoot.schema_pack_sha256
    || value.entity_id !== expectedRoot.entity_id
    || value.entity_version_id !== expectedRoot.entity_version_id
    || value.product_version_id !== expectedRoot.product_version_id
    || value.taxonomy_version !== expectedRoot.taxonomy_version
    || value.taxonomy_sha256 !== expectedRoot.taxonomy_sha256
    || value.section_id !== sectionId
    || !canonicalText(value.display_name)
    || !Array.isArray(value.ordered_field_ids)
    || !HEX_64.test(String(value.section_page_sha256))
  ) {
    throw new Error('SCHEMA_SECTION_PAGE_INVALID')
  }
  const fieldIds = value.ordered_field_ids.map(fieldId => {
    if (!canonicalText(fieldId)) throw new Error('SCHEMA_SECTION_PAGE_INVALID')
    return fieldId
  })
  if (fieldIds.length === 0 || new Set(fieldIds).size !== fieldIds.length) {
    throw new Error('SCHEMA_SECTION_PAGE_INVALID')
  }
  return Object.freeze({
    section_id: sectionId,
    display_name: value.display_name as string,
    ordered_field_ids: Object.freeze(fieldIds),
    section_page_sha256: value.section_page_sha256 as string,
  })
}

function isNoActiveRelease(error: unknown): boolean {
  return isRecord(error)
    && typeof error.message === 'string'
    && error.message.toLowerCase() === 'no schema wiki active release'
}

async function loadField(fieldId: string): Promise<void> {
  const client = activeClient.value
  if (!client || !releaseId.value) return
  selectedFieldId.value = fieldId
  selectedField.value = null
  try {
    const value = await client.getReleaseField(releaseId.value, fieldId)
    if (!isRecord(value) || !HEX_64.test(String(value.field_page_sha256))) {
      throw new Error('SCHEMA_FIELD_PAGE_INVALID')
    }
    selectedField.value = parseSchemaFieldPage(value, {
      fieldId,
      fieldPageSha256: value.field_page_sha256 as string,
    })
  } catch {
    status.value = 'error'
  }
}

async function selectSection(sectionId: string): Promise<void> {
  const section = sections.value.find(item => item.section_id === sectionId)
  if (!section) return
  selectedSectionId.value = sectionId
  await loadField(section.ordered_field_ids[0])
}

const activeClient = ref<Awaited<ReturnType<typeof bootstrapSchemaWikiClient>> | null>(null)

async function load(): Promise<void> {
  loading.value = true
  status.value = 'error'
  root.value = null
  releaseId.value = null
  activationEpoch.value = null
  activeCitationTransport.value = null
  sections.value = []
  selectedSectionId.value = null
  selectedFieldId.value = null
  selectedField.value = null
  fieldPresentation.value = new Map()
  activeClient.value = null
  try {
    const client = await bootstrapSchemaWikiClient(mvpExperience.value.servingKnowledgeBaseId, {
      get: async path => unwrapResponse(await get(path)),
    })
    const current = parseSchemaWikiCurrentEntityVersion(
      await client.getCurrentEntityVersion(MEDICAL_ENTITY_ID, MEDICAL_ENTITY_VERSION_ID),
      { entityId: MEDICAL_ENTITY_ID, entityVersionId: MEDICAL_ENTITY_VERSION_ID },
    )
    const [domainsValue, taxonomyValue, rootValue] = await Promise.all([
      client.getDomains(),
      client.getCurrentTaxonomy(),
      client.getReleaseRoot(current.active_release_id),
    ])
    const pinnedRoot = parseSchemaWikiCurrentEntityVersion({
      ...current,
      root: rootValue,
    }, {
      entityId: MEDICAL_ENTITY_ID,
      entityVersionId: MEDICAL_ENTITY_VERSION_ID,
    }).root
    if (JSON.stringify(pinnedRoot) !== JSON.stringify(current.root)) {
      throw new Error('SCHEMA_WIKI_RELEASE_PIN_MISMATCH')
    }
    assertConfiguredAuthority(domainsValue, taxonomyValue, current.root)
    const sectionPages = await Promise.all(current.root.ordered_section_ids.map(async sectionId => (
      parseSectionPage(
        await client.getReleaseSection(current.active_release_id, sectionId),
        current.root,
        sectionId,
      )
    )))
    const flattened = sectionPages.flatMap(section => section.ordered_field_ids)
    if (new Set(flattened).size !== flattened.length) {
      throw new Error('SCHEMA_WIKI_FIELD_TOPOLOGY_INVALID')
    }
    fieldPresentation.value = assertMedicalSchema67Presentation(flattened)
    activeClient.value = client
    root.value = current.root
    releaseId.value = current.active_release_id
    activationEpoch.value = current.activation_epoch
    activeCitationTransport.value = createSchemaWikiCitationPreviewTransport(client.scope, {
      get: async path => unwrapResponse(await get(path)),
      getBytes: async path => new Uint8Array(await get<ArrayBuffer>(path, {
        responseType: 'arraybuffer',
      })),
    })
    sections.value = Object.freeze(sectionPages)
    status.value = 'ready'
    await selectSection(sectionPages[0].section_id)
  } catch (error: unknown) {
    status.value = isNoActiveRelease(error) ? 'not-compiled' : 'error'
  } finally {
    loading.value = false
  }
}

watch(() => props.knowledgeBaseId, load, { immediate: true })
</script>

<template>
  <section class="schema-wiki-browser" data-testid="schema-wiki-browser">
    <p v-if="loading" class="schema-wiki-browser__state">{{ $t('knowledgeEditor.wikiBrowser.schemaLoading') }}</p>
    <p v-else-if="status === 'not-compiled'" class="schema-wiki-browser__state" role="status">
      {{ $t('knowledgeEditor.wikiBrowser.schemaNotCompiled') }}
    </p>
    <p v-else-if="status === 'error'" class="schema-wiki-browser__state" role="alert">
      {{ $t('knowledgeEditor.wikiBrowser.schemaLoadFailed') }}
    </p>
    <template v-else-if="root && releaseId && activationEpoch && activeCitationTransport">
      <aside class="schema-wiki-browser__navigation">
        <div class="schema-wiki-browser__heading">
          <h3>{{ root.product_display_name }}</h3>
          <span
            v-if="mvpExperience.active && mvpExperience.label"
            class="schema-wiki-browser__badge"
            data-testid="schema-mvp-badge"
          >
            {{ mvpExperience.label }}
          </span>
          <p class="schema-wiki-browser__counts" data-testid="schema-mvp-counts">
            {{ sections.length }} 个分类 · {{ fieldCount }} 个字段
          </p>
        </div>
        <div v-for="section in sections" :key="section.section_id" class="schema-wiki-browser__section">
          <button
            type="button"
            data-testid="schema-section-action"
            :class="{ active: selectedSectionId === section.section_id }"
            @click="selectSection(section.section_id)"
          >
            <span>{{ section.display_name }}</span>
            <small>{{ section.ordered_field_ids.length }}</small>
          </button>
          <ul v-if="selectedSectionId === section.section_id">
            <li v-for="fieldId in section.ordered_field_ids" :key="fieldId">
              <button
                type="button"
                :class="{ active: selectedFieldId === fieldId }"
                @click="loadField(fieldId)"
              >
                <span data-testid="schema-field-label">{{ fieldTitle(fieldId) }}</span>
                <code data-testid="schema-field-code">{{ fieldId }}</code>
              </button>
            </li>
          </ul>
        </div>
      </aside>
      <main class="schema-wiki-browser__content">
        <SchemaWikiFieldPage
          v-if="selectedField"
          :field-page="selectedField"
          :field-display-name="fieldTitle(selectedField.field_id)"
          :release-id="releaseId"
          :activation-epoch="activationEpoch"
          :preview-transport="activeCitationTransport"
        />
      </main>
    </template>
  </section>
</template>

<style scoped>
.schema-wiki-browser { display: grid; grid-template-columns: 320px minmax(0, 1fr); height: 100%; background: var(--td-bg-color-container); }
.schema-wiki-browser__state { grid-column: 1 / -1; margin: auto; color: var(--td-text-color-secondary); }
.schema-wiki-browser__navigation { overflow: auto; padding: 24px 16px; border-right: 1px solid var(--td-component-border); }
.schema-wiki-browser__heading { margin: 0 8px 20px; }
.schema-wiki-browser__navigation h3 { margin: 0 0 10px; }
.schema-wiki-browser__badge { display: inline-flex; padding: 3px 9px; border-radius: 999px; background: var(--td-success-color-light); color: var(--td-success-color); font-size: 12px; }
.schema-wiki-browser__counts { margin: 10px 0 0; color: var(--td-text-color-secondary); font-size: 12px; }
.schema-wiki-browser__navigation button { width: 100%; padding: 8px; border: 0; border-radius: 6px; background: transparent; text-align: left; cursor: pointer; }
.schema-wiki-browser__section > button { display: flex; align-items: center; justify-content: space-between; gap: 8px; font-weight: 600; }
.schema-wiki-browser__section > button small { color: var(--td-text-color-placeholder); font-weight: 400; }
.schema-wiki-browser__navigation button.active { background: var(--td-brand-color-light); color: var(--td-brand-color); }
.schema-wiki-browser__section ul { margin: 4px 0 12px; padding: 0 0 0 16px; list-style: none; }
.schema-wiki-browser__section li button span { display: block; }
.schema-wiki-browser__section li button code { display: block; margin-top: 3px; overflow: hidden; color: var(--td-text-color-placeholder); font-size: 11px; text-overflow: ellipsis; }
.schema-wiki-browser__content { min-width: 0; overflow: auto; padding: 32px; }
@media (max-width: 900px) {
  .schema-wiki-browser { grid-template-columns: 260px minmax(0, 1fr); }
  .schema-wiki-browser__content { padding: 24px; }
}
</style>

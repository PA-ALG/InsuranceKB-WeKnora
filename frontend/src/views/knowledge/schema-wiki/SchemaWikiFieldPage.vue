<script setup lang="ts">
import { computed, ref, watch } from 'vue'

import {
  buildSchemaCitationPreviewRequest,
  type SchemaWikiCitationPreviewTransport,
} from '@/api/schema-wiki'
import SchemaCitationViewer from '@/components/schema-wiki/SchemaCitationViewer.vue'
import { createPdfJsPort } from '@/components/schema-wiki/pdfJsPort.ts'
import type { CitationTargetV1 } from '@/components/schema-wiki/schemaCitationTarget.ts'
import SettingDrawer from '@/components/settings/SettingDrawer.vue'
import {
  schemaFieldUnknownReasonI18nKey,
  type SchemaFieldPageV1,
} from './schemaWikiContract.ts'

const props = defineProps<{
  fieldPage: SchemaFieldPageV1
  fieldDisplayName: string
  releaseId: string
  activationEpoch: number
  previewTransport: SchemaWikiCitationPreviewTransport
}>()

const sourceDrawerVisible = ref(false)
const selectedCitation = ref<CitationTargetV1 | null>(null)
const pdfPort = createPdfJsPort()

const previewRequest = computed(() => selectedCitation.value === null
  ? null
  : buildSchemaCitationPreviewRequest({
      release_id: props.releaseId,
      activation_epoch: props.activationEpoch,
      field_id: props.fieldPage.field_id,
      citation_id: selectedCitation.value.citation_id,
    }))

function openSources(): void {
  const first = props.fieldPage.citations[0]
  if (!first) return
  selectedCitation.value = first
  sourceDrawerVisible.value = true
}

function selectCitation(citation: CitationTargetV1): void {
  if (!props.fieldPage.citations.includes(citation)) return
  selectedCitation.value = citation
}

function closeSources(): void {
  sourceDrawerVisible.value = false
  selectedCitation.value = null
}

function updateSourceDrawerVisible(visible: boolean): void {
  if (!visible) closeSources()
}

watch(
  () => [props.releaseId, props.activationEpoch, props.fieldPage.field_id],
  closeSources,
)
</script>

<template>
  <article class="schema-wiki-field" :data-field-state="fieldPage.state">
    <header>
      <div>
        <h2>{{ fieldDisplayName }}</h2>
        <code class="schema-wiki-field__id" data-testid="schema-field-id">{{ fieldPage.field_id }}</code>
      </div>
      <span class="schema-wiki-field__state">
        <template v-if="fieldPage.state === 'present'">{{ $t('knowledgeEditor.wikiBrowser.schemaPresent') }}</template>
        <template v-else-if="fieldPage.state === 'absent_explicitly'">{{ $t('knowledgeEditor.wikiBrowser.schemaAbsent') }}</template>
        <template v-else>{{ $t(schemaFieldUnknownReasonI18nKey(fieldPage.unknown_reason)) }}</template>
      </span>
    </header>
    <p v-if="fieldPage.state !== 'unknown'" class="schema-wiki-field__value">
      {{ fieldPage.value_snapshot }}
    </p>
    <p v-else class="schema-wiki-field__unknown" role="status">
      {{ $t(schemaFieldUnknownReasonI18nKey(fieldPage.unknown_reason)) }}
    </p>
    <div v-if="fieldPage.citations.length > 0" class="schema-wiki-field__citations">
      <button
        type="button"
        data-testid="active-source-action"
        aria-haspopup="dialog"
        @click="openSources"
      >
        {{ $t('knowledgeEditor.wikiBrowser.schemaCitation') }}
      </button>
    </div>
    <SettingDrawer
      v-if="fieldPage.citations.length > 0"
      :visible="sourceDrawerVisible"
      :title="$t('knowledgeEditor.wikiBrowser.schemaCitation')"
      description="固定 Active 版本的原始证据"
      icon="file"
      width="760px"
      :min-width="560"
      :max-width="1000"
      storage-key="setting-drawer:width:schema-wiki-active-source"
      hide-footer
      @update:visible="updateSourceDrawerVisible"
    >
      <div class="schema-wiki-field__source-drawer" data-testid="active-source-drawer-content">
        <div
          v-if="fieldPage.citations.length > 1"
          class="schema-wiki-field__source-options"
          role="tablist"
          aria-label="原文来源"
        >
          <button
            v-for="(citation, index) in fieldPage.citations"
            :key="citation.citation_id"
            type="button"
            role="tab"
            data-testid="active-source-option"
            :aria-selected="selectedCitation === citation"
            @click="selectCitation(citation)"
          >
            来源 {{ index + 1 }}
          </button>
        </div>
        <SchemaCitationViewer
          v-if="selectedCitation && previewRequest"
          :key="selectedCitation.citation_id"
          :request="previewRequest"
          :preview-transport="previewTransport"
          :pdf-port="pdfPort"
          @back="closeSources"
        />
      </div>
    </SettingDrawer>
  </article>
</template>

<style scoped>
.schema-wiki-field { max-width: 880px; }
.schema-wiki-field header { display: flex; align-items: center; justify-content: space-between; gap: 16px; }
.schema-wiki-field h2 { margin: 0; }
.schema-wiki-field__id { display: inline-block; margin-top: 6px; color: var(--td-text-color-placeholder); font-size: 12px; }
.schema-wiki-field__state { padding: 4px 10px; border-radius: 999px; background: var(--td-bg-color-secondarycontainer); color: var(--td-text-color-secondary); }
.schema-wiki-field__value { margin-top: 24px; white-space: pre-wrap; line-height: 1.7; }
.schema-wiki-field__unknown { margin-top: 24px; color: var(--td-text-color-placeholder); }
.schema-wiki-field__citations { display: flex; flex-wrap: wrap; gap: 8px; margin-top: 24px; }
.schema-wiki-field__citations button { border: 1px solid var(--td-component-border); border-radius: 6px; padding: 6px 10px; background: transparent; cursor: pointer; }
.schema-wiki-field__source-options { display: flex; flex-wrap: wrap; gap: 8px; margin-bottom: 16px; }
.schema-wiki-field__source-options button { border: 1px solid var(--td-component-border); border-radius: 6px; padding: 6px 10px; background: transparent; cursor: pointer; }
.schema-wiki-field__source-options button[aria-selected='true'] { border-color: var(--td-brand-color); color: var(--td-brand-color); }
</style>

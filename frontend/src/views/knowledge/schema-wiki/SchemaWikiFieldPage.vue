<script setup lang="ts">
import { ref } from 'vue'

import { readPinnedSchemaCitationPreview } from '@/api/schema-wiki'
import { getDown } from '@/utils/request'
import {
  schemaFieldUnknownReasonI18nKey,
  type SchemaFieldPageV1,
  type SchemaWikiScopeV1,
} from './schemaWikiContract.ts'

const props = defineProps<{
  fieldPage: SchemaFieldPageV1
  scope: SchemaWikiScopeV1
  releaseId: string
}>()

const previewStatus = ref<string | null>(null)

async function previewCitation(citationId: string): Promise<void> {
  previewStatus.value = null
  try {
    await readPinnedSchemaCitationPreview(
      props.scope,
      props.releaseId,
      props.fieldPage.field_id,
      citationId,
      {
        getBytes: async path => new Uint8Array(await (await getDown(path)).arrayBuffer()),
      },
    )
    // The current read API deliberately does not expose member/binding custody
    // required by SchemaCitationViewer. Never fabricate that pin client-side.
    previewStatus.value = 'CITATION_BINDING_UNAVAILABLE'
  } catch {
    previewStatus.value = 'PDF_PREVIEW_UNAVAILABLE'
  }
}
</script>

<template>
  <article class="schema-wiki-field" :data-field-state="fieldPage.state">
    <header>
      <h2>{{ fieldPage.field_id }}</h2>
      <span class="schema-wiki-field__state">
        <template v-if="fieldPage.state === 'present'">{{ $t('knowledgeEditor.wikiBrowser.schemaPresent') }}</template>
        <template v-else-if="fieldPage.state === 'absent_explicitly'">{{ $t('knowledgeEditor.wikiBrowser.schemaAbsent') }}</template>
        <template v-else>{{ $t('knowledgeEditor.wikiBrowser.schemaUnknown') }}</template>
      </span>
    </header>
    <p v-if="fieldPage.state !== 'unknown'" class="schema-wiki-field__value">
      {{ fieldPage.value_snapshot }}
    </p>
    <p v-else class="schema-wiki-field__unknown" role="status">
      {{ $t(schemaFieldUnknownReasonI18nKey(fieldPage.unknown_reason)) }}
    </p>
    <div v-if="fieldPage.state !== 'unknown'" class="schema-wiki-field__citations">
      <button
        v-for="citation in fieldPage.citations"
        :key="citation.citation_id"
        type="button"
        @click="previewCitation(citation.citation_id)"
      >
        {{ $t('knowledgeEditor.wikiBrowser.schemaCitation') }} · p.{{ citation.page_number }}
      </button>
    </div>
    <p v-if="previewStatus" class="schema-wiki-field__preview-status" role="status">
      {{ $t('knowledgeEditor.wikiBrowser.schemaCitationUnavailable') }} ({{ previewStatus }})
    </p>
  </article>
</template>

<style scoped>
.schema-wiki-field { max-width: 880px; }
.schema-wiki-field header { display: flex; align-items: center; justify-content: space-between; gap: 16px; }
.schema-wiki-field h2 { margin: 0; }
.schema-wiki-field__state { padding: 4px 10px; border-radius: 999px; background: var(--td-bg-color-secondarycontainer); color: var(--td-text-color-secondary); }
.schema-wiki-field__value { margin-top: 24px; white-space: pre-wrap; line-height: 1.7; }
.schema-wiki-field__unknown { margin-top: 24px; color: var(--td-text-color-placeholder); }
.schema-wiki-field__citations { display: flex; flex-wrap: wrap; gap: 8px; margin-top: 24px; }
.schema-wiki-field__citations button { border: 1px solid var(--td-component-border); border-radius: 6px; padding: 6px 10px; background: transparent; cursor: pointer; }
.schema-wiki-field__preview-status { color: var(--td-text-color-secondary); }
</style>

<script setup lang="ts">
import { computed } from 'vue'
import type { RouteLocationRaw } from 'vue-router'
import type { KnowledgeContentSegment, KnowledgeCitation } from '@/api/schema-wiki/knowledgeContentProvenance'
const props = defineProps<{
  member: { content: string, payload: Record<string, unknown> }
  citations?: readonly KnowledgeCitation[]
  sourcePage?: RouteLocationRaw
}>()
const emit = defineEmits<{ source: [citationID: string] }>()
// API adapters validate coverage and citation identity before this renderer runs.
const segments = computed(() => (props.member.payload.content_provenance as
  { segments: KnowledgeContentSegment[] } | undefined)?.segments)
function sources(segment: KnowledgeContentSegment) {
  return segment.evidence_indexes.map(index => props.citations?.find(c => c.evidence_index === index))
    .filter((citation): citation is KnowledgeCitation => citation !== undefined)
}
</script>
<template>
  <article class="knowledge-content">
    <template v-if="segments">
      <section v-for="(segment, index) in segments" :key="index" :data-origin="segment.origin" class="knowledge-content__segment">
        <span class="knowledge-content__label">{{ segment.origin === 'MODEL_GENERATED' ? '模型生成' : '原文依据' }}</span>
        <div class="knowledge-content__text">{{ segment.text }}</div>
        <button v-for="citation in sources(segment)" :key="citation.citation_id" type="button"
          @click="emit('source', citation.citation_id)">查看第 {{ citation.page_number }} 页原文</button>
        <RouterLink v-if="sourcePage && segment.origin === 'SOURCE_SUPPORTED'" :to="sourcePage">查看知识及原文</RouterLink>
      </section>
    </template>
    <template v-else>{{ member.content }}</template>
  </article>
</template>
<style scoped>
.knowledge-content { white-space: pre-wrap; line-height: 1.8; }
.knowledge-content__segment { margin-bottom: 16px; }
.knowledge-content__label { display: inline-block; font-size: var(--app-text-sm); padding: 1px 8px; border-radius: var(--app-radius-xs); background: #edf4f0; color: #305d48; }
[data-origin="MODEL_GENERATED"] .knowledge-content__label { background: #fff3da; color: #755314; }
.knowledge-content button { margin: 4px 8px 0 0; cursor: pointer; }
</style>

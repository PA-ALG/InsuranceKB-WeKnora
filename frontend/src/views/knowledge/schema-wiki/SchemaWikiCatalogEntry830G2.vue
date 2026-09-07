<script setup lang="ts">
import { computed, ref, shallowRef, watch } from 'vue'

import { loadConceptDirectory830G2, type ConceptCatalogResult830G2 } from '@/api/schema-wiki/conceptDirectory830G2'
import {
  loadSchemaPackCatalog830G3,
  type SchemaPackCatalog830G3 as SchemaPackCatalogValue830G3,
} from '@/api/schema-wiki/schemaPackCatalog830G3'
import { get } from '@/utils/request'
import ConceptDirectory830G2 from './ConceptDirectory830G2.vue'
import SchemaPackCatalog830G3 from './SchemaPackCatalog830G3.vue'
import SchemaWikiBrowser from './SchemaWikiBrowser.vue'
import { resolveSchemaWikiMvpExperience, type SchemaWikiMvpRuntimeConfig } from './schemaWikiMvpPresentation'

const props = defineProps<{ knowledgeBaseId: string }>()
const loading = ref(true)
const error = ref('')
const catalog = shallowRef<ConceptCatalogResult830G2 | null>(null)
const schemaCatalog = shallowRef<SchemaPackCatalogValue830G3 | null>(null)
const schemaCatalogError = ref('')
let generation = 0

const experience = computed(() => resolveSchemaWikiMvpExperience(props.knowledgeBaseId,
  (window.__RUNTIME_CONFIG__ ?? {}) as SchemaWikiMvpRuntimeConfig))
const servingKnowledgeBaseID = computed(() => experience.value.servingKnowledgeBaseId)

async function load() {
  const current = ++generation
  loading.value = true; error.value = ''; schemaCatalogError.value = ''
  catalog.value = null; schemaCatalog.value = null
  const transport = { get: (path: string) => get(path) }
  const [published, structures] = await Promise.allSettled([
    loadConceptDirectory830G2(servingKnowledgeBaseID.value, transport),
    loadSchemaPackCatalog830G3(servingKnowledgeBaseID.value, transport),
  ])
  if (current !== generation) return
  if (published.status === 'fulfilled') catalog.value = published.value
  else error.value = '目录读取失败，请确认已发布版本仍是当前固定版本。'
  if (structures.status === 'fulfilled') schemaCatalog.value = structures.value
  else schemaCatalogError.value = '产品结构目录读取失败，完整性或读取权限未通过。'
  loading.value = false
}
watch(() => [props.knowledgeBaseId, servingKnowledgeBaseID.value], load, { immediate: true })
</script>

<template>
  <section class="catalog-entry">
    <p v-if="loading" role="status" class="catalog-state">正在读取知识目录…</p>
    <template v-else>
      <SchemaPackCatalog830G3 v-if="schemaCatalog" :catalog="schemaCatalog" />
      <p v-else data-testid="g3-catalog-error" role="alert" class="catalog-state">{{ schemaCatalogError }}</p>

      <p v-if="error" role="alert" class="catalog-state">{{ error }}</p>
      <ConceptDirectory830G2 v-else-if="catalog?.mode === 'g2'" :catalog="catalog" />
      <div v-else-if="catalog?.mode === 'entity-g1'" class="catalog-state">
        <RouterLink :to="{ name: 'entityPageOverview830G1',
          params: { kbId: catalog.scope.wiki_kb_id, entityId: catalog.entityID },
          query: { release_id: catalog.releaseID } }">查看已发布实体知识</RouterLink>
      </div>
      <SchemaWikiBrowser v-else-if="catalog?.mode === 'schema-legacy'" :knowledge-base-id="knowledgeBaseId" />
    </template>
  </section>
</template>

<style scoped>
.catalog-state { padding: 32px; color: var(--td-text-color-secondary); }
.catalog-state[role='alert'] { color: var(--td-error-color); }
.catalog-entry { min-height: 100%; }
</style>

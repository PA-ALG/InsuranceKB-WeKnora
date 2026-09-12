<script setup lang="ts">
import { computed } from 'vue'
import type { ConceptCatalogResult830G2 } from '@/api/schema-wiki/conceptDirectory830G2'
import type { BatchConceptDirectory830G3, BatchConceptEntity830G3 } from '@/api/schema-wiki/batchConcept830G3'

const props = defineProps<{
  catalog: Extract<ConceptCatalogResult830G2, { mode: 'g2' }> | BatchConceptDirectory830G3
}>()

function conceptLink(memberID: string) {
  const query = props.catalog.mode === 'g3-preparation'
    ? { preparation_id: props.catalog.preparationID }
    : { release_id: props.catalog.releaseID }
  return { name: 'conceptPage830G2',
    params: { kbId: props.catalog.scope.wiki_kb_id, memberId: memberID },
    query }
}
function historicalLink(memberID: string, releaseID: string) {
  return { name: 'conceptPage830G2', params: { kbId: props.catalog.scope.wiki_kb_id, memberId: memberID },
    query: { release_id: releaseID } }
}
function entityName(entityID: string) {
  if (props.catalog.mode === 'g2') return ''
  return props.catalog.entities.find(entity => entity.entityID === entityID)?.displayName ?? '产品'
}
const classificationLabels: Record<string, string> = {
  accident_insurance: '意外险', critical_illness_insurance: '重疾险',
  endowment_insurance: '两全险', medical_insurance: '医疗险',
}
function navigationLabel(entity: BatchConceptEntity830G3) {
  return entity.navigationPrimaryLabel ?? entity.primaryClassification
}
const grouped = computed(() => {
  if (props.catalog.mode === 'g2') return []
  const entities = [...props.catalog.entities].sort((a, b) =>
    navigationLabel(a).localeCompare(navigationLabel(b))
      || a.displayName.localeCompare(b.displayName, 'zh-CN'))
  const result: { key: string, label: string, entities: BatchConceptEntity830G3[] }[] = []
  for (const entity of entities) {
    const previous = result.at(-1)
    const label = navigationLabel(entity)
    if (previous?.key === label) previous.entities.push(entity)
    else result.push({ key: label,
      label: classificationLabels[label] ?? label, entities: [entity] })
  }
  return result
})
const totalFields = computed(() => props.catalog.mode === 'g2' ? 0
  : props.catalog.entities.reduce((total, entity) => total + entity.fieldCount, 0))
</script>

<template>
  <main v-if="catalog.mode === 'g2'" class="concept-directory" data-testid="g2-concept-directory">
    <header class="concept-directory__header">
      <span>知识目录</span>
      <h2>已发布知识</h2>
      <p>第 {{ catalog.activationEpoch }} 版</p>
    </header>
    <section v-if="catalog.concepts.length" aria-label="共享定义">
      <h3>共享定义</h3>
      <ul>
        <li v-for="concept in catalog.concepts" :key="concept.member_id">
          <RouterLink :to="conceptLink(concept.member_id)">{{ concept.title }}</RouterLink>
          <p>{{ concept.content }}</p>
        </li>
      </ul>
    </section>
    <section aria-label="产品知识">
      <h3>产品知识</h3>
      <ul class="concept-directory__entities">
        <li v-for="entity in catalog.entities" :key="entity.entityID">
          <h4>{{ entity.entityID }}</h4>
          <p>{{ entity.entityVersion }} · {{ entity.fieldCount }} 个字段 · {{ entity.freeItemCount }} 条开放知识</p>
          <RouterLink :to="conceptLink(entity.overview.member_id)">查看字段目录</RouterLink>
          <RouterLink :to="conceptLink(entity.freeWiki.member_id)">查看开放知识</RouterLink>
        </li>
      </ul>
    </section>
  </main>
  <main v-else class="concept-directory" data-testid="g3-concept-directory">
    <header class="concept-directory__header">
      <span>产品知识目录</span>
      <h2>{{ catalog.mode === 'g3-preparation' ? '整包审核预览' : '已发布产品知识' }}</h2>
      <p>{{ catalog.mode === 'g3-preparation' ? catalog.statusLabel : `第 ${catalog.activationEpoch} 版` }} ·
        {{ catalog.entities.length }} 个产品 · {{ totalFields }} 个字段</p>
    </header>

    <section v-if="catalog.mode === 'g3-preparation' && catalog.alignments.length" class="concept-directory__alignment"
      aria-label="字段名称调整">
      <h3>字段名称调整</h3>
      <p>以下两项沿用已发布内容，仅统一字段名称。审核时可分别查看原版本与本次版本。</p>
      <ul>
        <li v-for="alignment in catalog.alignments" :key="alignment.entityID">
          <span>{{ entityName(alignment.entityID) }}：社会保险要求 → 社会保险要求（复数结构）</span>
          <RouterLink :to="historicalLink(alignment.oldMemberID, alignment.oldReleaseID)">查看已发布历史版本</RouterLink>
          <RouterLink :to="conceptLink(alignment.newMemberID)">查看本次待审核版本</RouterLink>
          <details>
            <summary>技术详情</summary>
            <code>{{ alignment.oldFieldKey }} → {{ alignment.newFieldKey }}</code>
          </details>
        </li>
      </ul>
    </section>

    <section v-for="group in grouped" :key="group.key" :aria-label="group.label">
      <h3>{{ group.label }}</h3>
      <ul class="concept-directory__entities">
        <li v-for="entity in group.entities" :key="entity.entityID">
          <h4>{{ entity.displayName }}</h4>
          <p>{{ entity.issuer }} · {{ entity.schemaPackDisplayName }} · {{ entity.fieldCount }} 个字段</p>
          <p class="concept-directory__quality">已登记，尚未完成质量验收</p>
          <RouterLink :to="conceptLink(entity.overview.member_id)">查看产品总览</RouterLink>
          <RouterLink :to="conceptLink(entity.freeWiki.member_id)">查看开放知识</RouterLink>
          <div v-for="section in entity.sections" :key="section.sectionKey" class="concept-directory__section">
            <h5>{{ section.displayName }}</h5>
            <ul>
              <li v-for="field in section.fields" :key="field.memberID">
                <RouterLink :to="conceptLink(field.memberID)">{{ field.shortTitle }}</RouterLink>
              </li>
            </ul>
          </div>
          <details>
            <summary>技术详情</summary>
            <p><code>{{ entity.entityID }}</code> · <code>{{ entity.entityVersion }}</code></p>
            <p><code>{{ entity.schemaPackID }}</code> / <code>{{ entity.profileID }}</code></p>
          </details>
        </li>
      </ul>
    </section>
  </main>
</template>

<style scoped>
.concept-directory { max-width: 1080px; margin: 0 auto; padding: 28px 32px; color: var(--td-text-color-primary); }
.concept-directory__header span { color: var(--td-brand-color); font-size: 13px; }
.concept-directory__header h2 { margin: 6px 0; font-size: 26px; }
.concept-directory__header p, li p { color: var(--td-text-color-secondary); }
h3 { margin: 28px 0 12px; }
ul { list-style: none; margin: 0; padding: 0; }
li { padding: 16px 0; border-bottom: 1px solid var(--td-component-border); }
.concept-directory__entities { display: grid; grid-template-columns: repeat(auto-fit, minmax(260px, 1fr)); gap: 16px; }
.concept-directory__entities li { padding: 18px; border: 1px solid var(--td-component-border); border-radius: 8px; }
.concept-directory__quality { font-weight: 600; color: var(--td-warning-color); }
.concept-directory__section { margin-top: 18px; }
.concept-directory__section h5 { margin: 0 0 6px; font-size: 15px; }
.concept-directory__section li { padding: 5px 0; border: 0; }
.concept-directory__alignment { margin-top: 24px; padding: 16px 20px; border: 1px solid var(--td-component-border); border-radius: 8px; }
.concept-directory__alignment li > span { display: block; margin-bottom: 8px; font-weight: 600; }
details { margin-top: 12px; color: var(--td-text-color-secondary); }
a { margin-right: 18px; color: var(--td-brand-color); font-weight: 600; text-decoration: none; }
@media (max-width: 700px) { .concept-directory { padding: 20px; } }
</style>

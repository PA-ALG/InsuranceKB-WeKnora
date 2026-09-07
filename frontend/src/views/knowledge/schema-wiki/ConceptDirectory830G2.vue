<script setup lang="ts">
import type { ConceptCatalogResult830G2 } from '@/api/schema-wiki/conceptDirectory830G2'

const props = defineProps<{
  catalog: Extract<ConceptCatalogResult830G2, { mode: 'g2' }>
}>()

function conceptLink(memberID: string) {
  return { name: 'conceptPage830G2',
    params: { kbId: props.catalog.scope.wiki_kb_id, memberId: memberID },
    query: { release_id: props.catalog.releaseID } }
}
</script>

<template>
  <main class="concept-directory" data-testid="g2-concept-directory">
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
a { margin-right: 18px; color: var(--td-brand-color); font-weight: 600; text-decoration: none; }
@media (max-width: 700px) { .concept-directory { padding: 20px; } }
</style>

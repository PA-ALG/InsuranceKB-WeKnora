<script setup lang="ts">
import { computed, ref, useId, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import type { Release } from './enterpriseApi'
import { entityView, type EntitySummary, type FieldView } from './releaseView'
import { wikiPages, type WikiPageEntry } from './wikiPagesView'

const props = defineProps<{ entry: EntitySummary; release: Release; spaceId: string; selected?: boolean }>()
const { t } = useI18n()
const expanded = ref(false)
watch(() => props.selected, selected => { expanded.value = !!selected }, { immediate: true })
const contentId = useId()
const view = computed(() => expanded.value ? entityView(props.release, props.entry.entityId) : null)
const pages = computed(() => expanded.value ? wikiPages(props.release, props.entry.entityId) : [])
const sections = computed(() => view.value ? [
  ...view.value.sections,
  ...(view.value.other.length ? [{ key: '__other__', title: t('enterpriseKnowledge.entity.other'), fields: view.value.other }] : []),
  ...(view.value.generated.length ? [{ key: '__generated__', title: t('enterpriseKnowledge.entity.generated'), fields: view.value.generated }] : []),
] : [])
const target = computed(() => ({ name: 'enterpriseEntity', params: { spaceId: props.spaceId, entityId: props.entry.entityId }, query: { release: props.release.id } }))
function fieldTarget(field: FieldView) {
  const claim = props.release.members.find(member => member.kind === 'claim' && member.logical_slug === field.slug)
  const key = typeof claim?.payload?.predicate === 'string' ? claim.payload.predicate : field.slug
  return { ...target.value, hash: `#${key}` }
}
function pageTarget(page: WikiPageEntry) {
  return { name: 'enterpriseWikiPage', params: { spaceId: props.spaceId, entityId: props.entry.entityId,
    pageType: page.pageType, pageSlug: page.key.slice(page.pageType.length + 1) }, query: { release: props.release.id } }
}
</script>

<template>
  <li class="ek-nav-entry" data-nav-entry>
    <div class="ek-nav-entry__head">
      <button type="button" class="ek-nav-entry__toggle" :aria-expanded="expanded" :aria-controls="contentId"
        :aria-label="t(expanded ? 'enterpriseKnowledge.nav.collapseEntry' : 'enterpriseKnowledge.nav.expandEntry', { name: entry.name })"
        @click="expanded = !expanded"><span aria-hidden="true">{{ expanded ? '▾' : '▸' }}</span></button>
      <RouterLink :to="target" :title="entry.name" :aria-current="selected ? 'page' : undefined">
        <span>{{ entry.name }}</span>
      </RouterLink>
    </div>
    <div v-if="expanded" :id="contentId" class="ek-nav-fields">
      <details v-for="section in sections" :key="section.key" open>
        <summary>{{ section.title }}</summary>
        <ul>
          <li v-for="field in section.fields" :key="field.slug"><RouterLink :to="fieldTarget(field)" :title="field.title">{{ field.title }}</RouterLink></li>
        </ul>
      </details>
      <p v-if="!sections.length" class="ek-page__note">{{ t('enterpriseKnowledge.nav.noFields') }}</p>
      <details v-if="pages.length" :key="`${spaceId}/${release.id}/${entry.entityId}`" data-nav-wiki class="ek-nav-wiki">
        <summary>{{ t('enterpriseKnowledge.wiki.navigation') }} <span class="ek-nav-wiki__count">{{ pages.length }}</span></summary>
        <ul><li v-for="page in pages" :key="page.slug"><RouterLink :to="pageTarget(page)" :title="page.title">{{ page.title }}</RouterLink></li></ul>
      </details>
    </div>
  </li>
</template>

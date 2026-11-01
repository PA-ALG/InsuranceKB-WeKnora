<script setup lang="ts">
import { computed, inject, ref, useId, watch } from 'vue'
import { routeLocationKey } from 'vue-router'
import { useNavigationMemory } from './navigationMemory'
import { useI18n } from 'vue-i18n'
import type { Release } from './enterpriseApi'
import type { SaleStatus } from './productVersions'
import { entityView, type EntitySummary, type FieldView } from './releaseView'
import { wikiPages, type WikiPageEntry } from './wikiPagesView'

// saleStatus is set only for an entry with version data (PV-4b).
const props = defineProps<{ entry: EntitySummary; release: Release; spaceId: string; selected?: boolean; wikiPageKey?: string; saleStatus?: SaleStatus }>()
const { t } = useI18n()
const expanded = ref(false)
watch(() => props.selected, selected => { expanded.value = !!selected }, { immediate: true })
const contentId = useId()
const view = computed(() => expanded.value ? entityView(props.release, props.entry.entityId) : null)
const pages = computed(() => expanded.value ? wikiPages(props.release, props.entry.entityId) : [])
const memory = useNavigationMemory()
const memoryKey = computed(() => JSON.stringify([props.spaceId, props.release.id, props.entry.entityId]))
const schemaExpanded = ref(true), wikiExpanded = ref(false)
const schemaDetails = ref<HTMLDetailsElement>(), wikiDetails = ref<HTMLDetailsElement>()
watch([memoryKey, () => props.wikiPageKey], () => {
  const saved = memory.read(memoryKey.value)
  schemaExpanded.value = saved.schema ?? true
  wikiExpanded.value = !!props.wikiPageKey && wikiPages(props.release, props.entry.entityId).some(page => page.key === props.wikiPageKey)
    ? true : saved.wiki ?? false
}, { immediate: true })
function rememberExpansion(group: 'schema' | 'wiki') {
  const details = group === 'schema' ? schemaDetails.value : wikiDetails.value
  const expanded = group === 'schema' ? schemaExpanded : wikiExpanded
  // Setting :open also queues a native toggle. Only a DOM change from our rendered state
  // is a reader choice; forcing a wiki group open must not overwrite the saved choice.
  if (details && details.open !== expanded.value) {
    expanded.value = details.open
    memory.write(memoryKey.value, group, details.open)
  }
}
function toggleEntry() {
  // Native toggle events are queued; save the DOM state before the group is unmounted.
  rememberExpansion('schema')
  rememberExpansion('wiki')
  expanded.value = !expanded.value
}
function rememberWikiExpansion(event: Event) {
  if (event.currentTarget === wikiDetails.value) rememberExpansion('wiki')
}
function rememberSchemaExpansion(event: Event) {
  if (event.currentTarget === schemaDetails.value) rememberExpansion('schema')
}
const route = inject(routeLocationKey, undefined)
function decodedHash(hash: string) {
  try { return decodeURIComponent(hash) } catch { return hash }
}
function isCurrentField(field: FieldView) {
  return route?.name === 'enterpriseEntity' && route.params.spaceId === props.spaceId
    && route.params.entityId === props.entry.entityId && decodedHash(route.hash) === fieldTarget(field).hash
}
const missingLabel = computed(() => t('enterpriseKnowledge.nav.missingField'))
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
        @click="toggleEntry"><span aria-hidden="true">{{ expanded ? '▾' : '▸' }}</span></button>
      <RouterLink :to="target" :title="entry.name" :aria-current="selected && !wikiPageKey ? 'page' : undefined">
        <span>{{ entry.name }}</span>
      </RouterLink>
      <span v-if="saleStatus" class="ek-sale-status" :data-sale-status="saleStatus">{{ t(`enterpriseKnowledge.version.status.${saleStatus}`) }}</span>
    </div>
    <div v-if="expanded" :id="contentId" class="ek-nav-fields">
      <details :key="`${spaceId}/${release.id}/${entry.entityId}/schema`" ref="schemaDetails"
        data-nav-schema class="ek-nav-schema" :open="schemaExpanded" @toggle="rememberSchemaExpansion">
        <summary>{{ t('enterpriseKnowledge.nav.schemaWiki') }}</summary>
        <details v-for="section in sections" :key="section.key" open>
          <summary>{{ section.title }}</summary>
          <ul>
            <li v-for="field in section.fields" :key="field.slug"><RouterLink :to="fieldTarget(field)"
              :title="field.title + (field.state === 'unknown' ? missingLabel : '')"
              :data-field-missing="field.state === 'unknown' ? '' : undefined"
              :aria-current="isCurrentField(field) ? 'location' : null">{{ field.title }}<span v-if="field.state === 'unknown'" class="ek-sr-only">{{ missingLabel }}</span></RouterLink></li>
          </ul>
        </details>
        <p v-if="!sections.length" class="ek-page__note">{{ t('enterpriseKnowledge.nav.noFields') }}</p>
      </details>
      <details v-if="pages.length" :key="`${spaceId}/${release.id}/${entry.entityId}/${wikiPageKey ?? ''}`"
        ref="wikiDetails" data-nav-wiki class="ek-nav-wiki" :open="wikiExpanded" @toggle="rememberWikiExpansion">
        <summary>{{ t('enterpriseKnowledge.wiki.navigation') }} <span class="ek-nav-wiki__count">{{ pages.length }}</span></summary>
        <ul><li v-for="page in pages" :key="page.slug"><RouterLink :to="pageTarget(page)" :title="page.title"
          :aria-current="page.key === wikiPageKey ? 'page' : undefined">{{ page.title }}</RouterLink></li></ul>
      </details>
    </div>
  </li>
</template>

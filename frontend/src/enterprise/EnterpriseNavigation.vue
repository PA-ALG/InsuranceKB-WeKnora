<script setup lang="ts">
import { computed, nextTick, ref, useId, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import type { Release } from './enterpriseApi'
import { navigationTree } from './navigationView'
import { conceptKeys, conceptView } from './conceptView'
import NavigationEntry from './NavigationEntry.vue'
import { businessDay, discontinuedCount, familyClusters, saleStatuses, visibleEntries } from './productVersions'
import type { EntitySummary } from './releaseView'

const props = defineProps<{ release: Release; spaceId: string; entityId?: string; conceptKey?: string; wikiPageKey?: string }>()
const { t } = useI18n()
const tree = computed(() => navigationTree(props.release))
const concepts = computed(() => conceptKeys(props.release).map(key => conceptView(props.release, key)!))
const categories = computed(() => {
  const groups = new Map<string, typeof concepts.value>()
  for (const concept of concepts.value) {
    if (!groups.has(concept.category)) groups.set(concept.category, [])
    groups.get(concept.category)!.push(concept)
  }
  return [...groups].map(([title, entries]) => ({ title, entries }))
})
const selected = ref(0)
const mobileOpen = ref(false)
const query = ref('')
const collapsed = ref(new Set<string>())
const tablist = ref<HTMLElement>()
const id = useId()
const search = computed(() => query.value.trim().toLocaleLowerCase())
const matches = (name: string) => name.toLocaleLowerCase().includes(search.value)
// PV-4b: discontinued versions stay hidden unless included, except the entry on screen; the
// business day is taken again whenever the release or entry changes.
const day = ref(businessDay(new Date()))
const includeDiscontinued = ref(false)
const statuses = computed(() => saleStatuses(props.release, day.value))
const discontinued = computed(() => discontinuedCount(props.release, tree.value.flatMap(domain => domain.groups.flatMap(group => group.entries)), day.value))
const shown = (entries: EntitySummary[]) =>
  visibleEntries(props.release, entries, day.value, { includeDiscontinued: includeDiscontinued.value, keep: props.entityId })
const filteredTree = computed(() => tree.value.map(domain => ({ ...domain, groups: domain.groups
  .map(group => ({ ...group, entries: shown(group.entries.filter(entry => matches(entry.name))) })).filter(group => group.entries.length)
  .map(group => ({ ...group, clusters: familyClusters(props.release, group.entries) })) })))
const filteredCategories = computed(() => categories.value.map(category => ({ ...category,
  entries: category.entries.filter(concept => matches(concept.title)),
})).filter(category => category.entries.length))
const groupId = (domain: string, group: string) => JSON.stringify([domain, group])
const isOpen = (key: string) => !!search.value || !collapsed.value.has(key)
function toggleGroup(key: string) {
  const next = new Set(collapsed.value)
  if (next.has(key)) next.delete(key)
  else next.add(key)
  collapsed.value = next
}
function selectTab(index: number) {
  selected.value = index
  query.value = ''
}
async function showConcepts() {
  selectTab(tree.value.length)
  mobileOpen.value = true
  await nextTick()
  tablist.value?.querySelector<HTMLButtonElement>('[aria-selected="true"]')?.focus()
}
defineExpose({ showConcepts })
const tabs = computed(() => [...tree.value.map(domain => domain.title || t(domain.key ? 'enterpriseKnowledge.nav.other' : 'enterpriseKnowledge.title')), t('enterpriseKnowledge.nav.concepts')])
watch(() => [props.release, props.entityId, props.conceptKey], () => {
  const index = tree.value.findIndex(domain => domain.groups.some(group => group.entries.some(entry => entry.entityId === props.entityId)))
  selected.value = props.conceptKey ? tree.value.length : Math.max(index, 0)
  query.value = ''
  day.value = businessDay(new Date())
  for (const domain of tree.value) for (const group of domain.groups) {
    if (group.entries.some(entry => entry.entityId === props.entityId)) collapsed.value.delete(groupId(domain.key, group.key))
  }
  const category = concepts.value.find(concept => concept.key === props.conceptKey)?.category
  if (category !== undefined) collapsed.value.delete(groupId('concept', category))
  mobileOpen.value = false
}, { immediate: true })
function keydown(event: KeyboardEvent, index: number) {
  let next = index
  if (event.key === 'ArrowRight') next = (index + 1) % tabs.value.length
  else if (event.key === 'ArrowLeft') next = (index + tabs.value.length - 1) % tabs.value.length
  else if (event.key === 'Home') next = 0
  else if (event.key === 'End') next = tabs.value.length - 1
  else return
  event.preventDefault()
  selectTab(next)
  const buttons = (event.currentTarget as HTMLElement).parentElement?.querySelectorAll<HTMLButtonElement>('[role="tab"]')
  buttons?.[next]?.focus()
}
</script>

<template>
  <nav :class="['ek-navigation', { 'ek-navigation--open': mobileOpen }]" :aria-label="t('enterpriseKnowledge.nav.navigation')">
    <button type="button" class="ek-button ek-navigation__toggle" :aria-expanded="mobileOpen" :aria-controls="id" @click="mobileOpen = !mobileOpen">
      {{ t('enterpriseKnowledge.nav.navigation') }} <span aria-hidden="true">{{ mobileOpen ? '▴' : '▾' }}</span>
    </button>
    <div :id="id" class="ek-navigation__body">
      <div ref="tablist" role="tablist" :aria-label="t('enterpriseKnowledge.nav.navigation')" class="ek-nav-tabs">
        <button v-for="(title, index) in tabs" :id="`${id}-tab-${index}`" :key="index" type="button" role="tab"
          :data-nav-domain="index < tree.length && tree[index]?.key ? '' : undefined"
          :aria-selected="selected === index" :aria-controls="`${id}-panel-${index}`" :tabindex="selected === index ? 0 : -1"
          @click="selectTab(index)" @keydown="keydown($event, index)">{{ title }}</button>
      </div>
      <input v-model="query" data-nav-filter type="search" class="ek-nav-filter" :aria-label="t('enterpriseKnowledge.home.filter')" :placeholder="t('enterpriseKnowledge.home.filter')" />
      <label v-if="discontinued" class="ek-nav-discontinued" data-nav-discontinued>
        <input v-model="includeDiscontinued" type="checkbox" /> {{ t('enterpriseKnowledge.version.includeDiscontinued', { n: discontinued }) }}
      </label>
      <div v-for="(domain, index) in filteredTree" v-show="selected === index" :id="`${id}-panel-${index}`" :key="domain.key"
        role="tabpanel" :aria-labelledby="`${id}-tab-${index}`">
        <section v-for="(group, groupIndex) in domain.groups" :key="group.key" class="ek-nav-group">
          <h2 v-if="group.key" :data-nav-group="group.key"><button type="button" :aria-expanded="isOpen(groupId(domain.key, group.key))"
            :aria-controls="`${id}-group-${index}-${groupIndex}`" @click="toggleGroup(groupId(domain.key, group.key))">
            <span aria-hidden="true">{{ isOpen(groupId(domain.key, group.key)) ? '▾' : '▸' }}</span>
            <span class="ek-nav-group__name" :title="group.title || t('enterpriseKnowledge.nav.other')">{{ group.title || t('enterpriseKnowledge.nav.other') }}</span>
            <small>{{ group.entries.length }}</small>
          </button></h2>
          <ul v-show="isOpen(groupId(domain.key, group.key))" :id="`${id}-group-${index}-${groupIndex}`">
            <template v-for="(cluster, clusterIndex) in group.clusters" :key="cluster.family?.key ?? `entries-${clusterIndex}`">
              <li v-if="cluster.family" class="ek-nav-family" data-nav-family>
                <span class="ek-nav-family__name" :title="cluster.family.title" aria-hidden="true">{{ cluster.family.title }}</span>
                <ul :aria-label="cluster.family.title">
                  <NavigationEntry v-for="entry in cluster.entries" :key="entry.entityId" :entry="entry" :release="release" :space-id="spaceId"
                    :selected="entry.entityId === entityId" :wiki-page-key="entry.entityId === entityId ? wikiPageKey : undefined"
                    :sale-status="statuses.get(entry.entityId)" />
                </ul>
              </li>
              <template v-else>
                <NavigationEntry v-for="entry in cluster.entries" :key="entry.entityId" :entry="entry" :release="release" :space-id="spaceId"
                  :selected="entry.entityId === entityId" :wiki-page-key="entry.entityId === entityId ? wikiPageKey : undefined"
                  :sale-status="statuses.get(entry.entityId)" />
              </template>
            </template>
          </ul>
        </section>
        <p v-if="!domain.groups.length" class="ek-empty">{{ t('enterpriseKnowledge.home.noProducts') }}</p>
      </div>
      <div v-show="selected === tree.length" :id="`${id}-panel-${tree.length}`" role="tabpanel" :aria-labelledby="`${id}-tab-${tree.length}`">
        <section v-for="(category, index) in filteredCategories" :key="category.title" class="ek-nav-group">
          <h2><button type="button" :aria-expanded="isOpen(groupId('concept', category.title))" :aria-controls="`${id}-concepts-${index}`" @click="toggleGroup(groupId('concept', category.title))">
            <span aria-hidden="true">{{ isOpen(groupId('concept', category.title)) ? '▾' : '▸' }}</span>
            <span class="ek-nav-group__name" :title="category.title || t('enterpriseKnowledge.nav.other')">{{ category.title || t('enterpriseKnowledge.nav.other') }}</span>
            <small>{{ category.entries.length }}</small>
          </button></h2>
          <ul v-show="isOpen(groupId('concept', category.title))" :id="`${id}-concepts-${index}`">
            <li v-for="concept in category.entries" :key="concept.key" data-nav-concept>
              <RouterLink :to="{ name: 'enterpriseConcept', params: { spaceId, conceptKey: concept.key }, query: { release: release.id } }"
                :title="concept.title" :aria-current="concept.key === conceptKey ? 'page' : undefined">{{ concept.title }}</RouterLink>
            </li>
          </ul>
        </section>
        <p v-if="!filteredCategories.length" class="ek-empty">{{ t(concepts.length ? 'enterpriseKnowledge.home.noConcepts' : 'enterpriseKnowledge.nav.noConcepts') }}</p>
      </div>
    </div>
  </nav>
</template>

<style src="./enterpriseNavigation.css"></style>

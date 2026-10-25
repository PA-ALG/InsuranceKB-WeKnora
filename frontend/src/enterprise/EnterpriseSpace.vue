<script setup lang="ts">
import { computed, onUnmounted, ref, useId, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { EnterpriseError, readRelease, type Release } from './enterpriseApi'
import { spaceHomeView } from './spaceHomeView'
import { searchFields } from './releaseSearch'
import { previousReleaseId, releaseChanges } from './releaseChanges'
import EnterpriseNavigation from './EnterpriseNavigation.vue'

const props = defineProps<{ spaceId: string; releaseId?: string }>()
const { t } = useI18n()
const state = ref<'loading' | 'failed' | 'unpublished' | 'ready'>('loading')
const release = ref<Release | null>(null)
const base = ref<Release | null>(null)
const changes = computed(() => release.value ? releaseChanges(release.value, base.value) : null)
const home = computed(() => release.value ? spaceHomeView(release.value) : null)
const query = ref('')
const searchId = useId()
const navigation = ref<InstanceType<typeof EnterpriseNavigation>>()
const search = computed(() => query.value.trim().toLocaleLowerCase())
const matches = (name: string) => name.toLocaleLowerCase().includes(search.value)
const groups = computed(() => (home.value?.groups ?? []).map(group => ({ ...group, rows: group.rows.filter(row => matches(row.name)) }))
  .filter(group => group.rows.length))
const concepts = computed(() => (home.value?.concepts ?? []).filter(concept => matches(concept.title)))
const common = computed(() => search.value ? concepts.value : concepts.value.slice(0, 10))
const fieldSearch = computed(() => release.value ? searchFields(release.value, query.value) : { hits: [], total: 0 })
const generated = computed(() => new Set((release.value?.members ?? [])
  .filter(member => member.kind === 'claim' && member.payload?.origin === 'MODEL_GENERATED').map(member => member.logical_slug)))
function entityTarget(entityId: string) {
  return { name: 'enterpriseEntity', params: { spaceId: props.spaceId, entityId }, query: { release: release.value!.id } }
}
function conceptTarget(conceptKey: string) {
  return { name: 'enterpriseConcept', params: { spaceId: props.spaceId, conceptKey }, query: { release: release.value!.id } }
}
function openRow(event: Event) {
  if ((event.target as Element).closest('a')) return
  event.preventDefault()
  ;(event.currentTarget as HTMLElement).querySelector<HTMLAnchorElement>('a')?.click()
}
let generation = 0

async function loadBase(current: Release, request: number) {
  try {
    const id = previousReleaseId(current)
    if (!id) return
    const previous = await readRelease(props.spaceId, id)
    if (request === generation && previous.id === id) base.value = previous
  } catch { /* Optional comparison must not prevent reading the current release. */ }
}

async function load() {
  const current = ++generation
  state.value = 'loading'
  release.value = null
  base.value = null
  query.value = ''
  try {
    const active = props.releaseId ? await readRelease(props.spaceId, props.releaseId) : await readRelease(props.spaceId)
    if (current !== generation) return
    release.value = active
    state.value = 'ready'
    void loadBase(active, current)
  } catch (error) {
    if (current !== generation) return
    // A Space that has never published is empty, not broken.
    state.value = error instanceof EnterpriseError && error.code === 'RELEASE_NOT_FOUND' ? 'unpublished' : 'failed'
  }
}

watch(() => [props.spaceId, props.releaseId], load, { immediate: true })
onUnmounted(() => { generation++ })
</script>

<template>
  <main class="ek-page ek-space-page">
    <h1 v-if="!release" class="ek-page__title">{{ t('enterpriseKnowledge.title') }}</h1>
    <p v-if="state === 'loading'" role="status" class="ek-status">{{ t('enterpriseKnowledge.loading') }}</p>
    <div v-else-if="state === 'failed'" role="alert" class="ek-alert">
      <span>{{ t('enterpriseKnowledge.space.failed') }}</span>
      <button type="button" class="ek-button" @click="load">{{ t('enterpriseKnowledge.retry') }}</button>
    </div>
    <p v-else-if="state === 'unpublished'" class="ek-empty">{{ t('enterpriseKnowledge.space.noRelease') }}</p>
    <div v-else-if="release && home" class="ek-layout">
      <EnterpriseNavigation ref="navigation" :release="release" :space-id="spaceId" />
      <article class="ek-layout__content ek-home">
        <header>
          <div class="ek-home__heading">
            <h1 class="ek-page__title" data-space-title>{{ home.title || t('enterpriseKnowledge.title') }}</h1>
            <span class="ek-meta-tag" data-space-version :title="spaceId">{{ t('enterpriseKnowledge.home.version', { epoch: release.epoch }) }}</span>
            <span v-if="changes && (changes.added.length || changes.changed.length || changes.removed.length)" data-space-changes class="ek-home__changes">
              <RouterLink :to="{ name: 'enterpriseChanges', params: { spaceId }, query: { release: release.id } }">{{ t('enterpriseKnowledge.changes.summary', { added: changes.added.length, changed: changes.changed.length, removed: changes.removed.length }) }} →</RouterLink>
            </span>
            <RouterLink class="ek-home__graph-link" :to="{ name: 'enterpriseGraph', params: { spaceId }, query: { release: release.id } }">{{ t('enterpriseKnowledge.graph.title') }} →</RouterLink>
            <RouterLink class="ek-home__spot-link" :to="{ name: 'enterpriseSpotChecks', params: { spaceId } }">{{ t('enterpriseKnowledge.spot.entry') }} →</RouterLink>
            <RouterLink class="ek-home__spot-link" :to="{ name: 'enterpriseConfirmations', params: { spaceId } }">{{ t('enterpriseKnowledge.confirm.entry') }} →</RouterLink>
          </div>
          <p class="ek-page__meta" data-space-counts>{{ t('enterpriseKnowledge.home.counts', { products: home.productCount, concepts: home.concepts.length }) }}</p>
        </header>
        <div class="ek-home__search" data-space-search>
          <label class="ek-sr-only" :for="searchId">{{ t('enterpriseKnowledge.home.search') }}</label>
          <input :id="searchId" v-model="query" type="search" :placeholder="t('enterpriseKnowledge.home.search')" />
        </div>
        <div v-if="concepts.length" class="ek-home__shortcuts">
          <span>{{ t('enterpriseKnowledge.home.common') }}</span>
          <RouterLink v-for="concept in concepts.slice(0, 6)" :key="concept.key" data-concept-shortcut :to="conceptTarget(concept.key)">{{ concept.title }}</RouterLink>
        </div>
        <section class="ek-home__section">
          <h2>{{ t('enterpriseKnowledge.home.overview') }}</h2>
          <p v-if="!home.productCount" class="ek-empty">{{ t('enterpriseKnowledge.space.empty') }}</p>
          <div v-else class="ek-home__table" tabindex="0" role="region" :aria-label="t('enterpriseKnowledge.home.overview')">
            <table>
              <thead><tr>
                <th data-overview-column scope="col">{{ t('enterpriseKnowledge.concept.columns.product') }}</th>
                <th v-for="column in home.columns" :key="column.key" data-overview-column scope="col">{{ column.title }}</th>
              </tr></thead>
              <tbody v-for="group in groups" :key="group.id">
                <tr class="ek-home__group" :data-overview-group="group.key"><th scope="rowgroup" :colspan="home.columns.length + 1">
                  {{ group.title || t('enterpriseKnowledge.nav.other') }} <small>{{ group.rows.length }}</small>
                </th></tr>
                <tr v-for="row in group.rows" :key="row.entityId" :data-overview-row="row.entityId" class="ek-home__row" tabindex="0"
                  @click="openRow" @keydown.enter="openRow" @keydown.space.prevent="openRow">
                  <th scope="row"><RouterLink :to="entityTarget(row.entityId)" :title="row.name">{{ row.name }}</RouterLink></th>
                  <td v-for="cell in row.cells" :key="cell.key" :data-overview-cell="cell.key" :title="cell.fullValue">
                    <span v-for="(value, index) in cell.values" :key="index" :class="['ek-home__value', { 'ek-home__value--missing': value.state === 'unknown', 'ek-home__value--generated': value.generated }]">
                      <span v-if="value.generated" class="ek-origin ek-origin--generated">{{ t('enterpriseKnowledge.origin.generated') }}</span>
                      {{ value.state === 'present' ? value.text : value.state === 'absent_explicitly' ? t('enterpriseKnowledge.home.absent') : '—' }}
                    </span>
                  </td>
                </tr>
              </tbody>
              <tbody v-if="!groups.length"><tr><td :colspan="home.columns.length + 1" class="ek-empty">{{ t('enterpriseKnowledge.home.noProducts') }}</td></tr></tbody>
            </table>
          </div>
        </section>
        <section class="ek-home__section">
          <h2>{{ t('enterpriseKnowledge.home.common') }}</h2>
          <div class="ek-home__concepts">
            <RouterLink v-for="concept in common" :key="concept.key" data-common-concept :to="conceptTarget(concept.key)">{{ concept.title }}</RouterLink>
            <span v-if="!common.length" class="ek-page__meta">{{ t('enterpriseKnowledge.home.noConcepts') }}</span>
            <button type="button" class="ek-link-button" data-all-concepts @click="navigation?.showConcepts()">{{ t('enterpriseKnowledge.home.allConcepts', { count: home.concepts.length }) }} →</button>
          </div>
        </section>
        <section v-if="search" class="ek-home__section ek-home__fields" data-search-fields>
          <h2>{{ t('enterpriseKnowledge.home.fieldContent') }}</h2>
          <p v-if="fieldSearch.total > 50" class="ek-page__meta" role="status">{{ t('enterpriseKnowledge.home.fieldLimit', { total: fieldSearch.total }) }}</p>
          <ul v-if="fieldSearch.hits.length" class="ek-home__hits">
            <li v-for="hit in fieldSearch.hits" :key="hit.slug" data-search-hit>
              <RouterLink :to="{ ...entityTarget(hit.entityId), hash: `#${hit.fieldKey}` }">
                <span class="ek-home__hit-title">{{ hit.name }} <span aria-hidden="true">·</span> {{ hit.fieldTitle }}</span>
                <span v-if="generated.has(hit.slug)" class="ek-origin ek-origin--generated">{{ t('enterpriseKnowledge.origin.generated') }}</span>
                <span class="ek-home__snippet"><template v-for="(part, index) in hit.parts" :key="index"><mark v-if="part.mark">{{ part.text }}</mark><template v-else>{{ part.text }}</template></template></span>
              </RouterLink>
            </li>
          </ul>
          <p v-else-if="groups.length || concepts.length" class="ek-page__meta">{{ t('enterpriseKnowledge.home.noFields') }}</p>
          <p v-else class="ek-empty" role="status">{{ t('enterpriseKnowledge.home.noResults', { query: query.trim() }) }}</p>
        </section>
      </article>
    </div>
  </main>
</template>

<style src="./enterprisePage.css"></style>
<style src="./spaceHome.css"></style>

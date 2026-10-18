<script setup lang="ts">
import { computed, nextTick, onUnmounted, ref, useId, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { EnterpriseError, readRelease, type Release } from './enterpriseApi'
import { conceptView } from './conceptView'
import { relationGraph, type GraphNode } from './graphView'
import { graphDisplay } from './graphDisplay'
import RelationGraphCanvas from './RelationGraphCanvas.vue'

const props = defineProps<{ spaceId: string; releaseId?: string }>()
const { t } = useI18n()
const state = ref<'loading' | 'failed' | 'unpublished' | 'ready'>('loading')
const release = ref<Release | null>(null)
const graph = computed(() => release.value ? relationGraph(release.value) : { nodes: [], edges: [] })
const products = computed(() => graph.value.nodes.filter(node => node.kind === 'product'))
const palette = ['var(--td-brand-color)', 'var(--td-success-color)', 'var(--td-warning-color)', 'var(--td-error-color)',
  'var(--td-brand-color-7)', 'var(--td-success-color-7)']
const groups = computed(() => [...new Map(products.value.map(node => [node.group, node.groupTitle])).entries()]
  .map(([key, title], index) => ({ key, title: title || t('enterpriseKnowledge.nav.other'), color: palette[index % palette.length]! })))
const colors = computed(() => new Map(groups.value.map(group => [group.key, group.color])))
const enabled = ref<string[]>([])
const showAll = ref(false), locatedId = ref('')
const display = computed(() => graphDisplay(graph.value, enabled.value, showAll.value, locatedId.value))
const visible = computed(() => display.value.visible)
const selectedId = ref('')
const selected = computed(() => visible.value.nodes.find(node => node.id === selectedId.value))
const concept = computed(() => selected.value?.kind === 'concept' && release.value
  ? conceptView(release.value, selected.value.id.slice('concept:'.length)) : null)
const canvas = ref<InstanceType<typeof RelationGraphCanvas>>()
const closeButton = ref<HTMLButtonElement>()
const query = ref(''), searched = ref(false)
const searchId = useId(), detailTitleId = useId()
const matches = computed(() => {
  const term = query.value.trim().toLocaleLowerCase()
  return term ? display.value.available.nodes.filter(node => node.title.toLocaleLowerCase().includes(term)) : []
})
const matchingResults = computed(() => matches.value.slice(0, 8))
const pin = computed(() => ({ release: release.value!.id }))
const detailTarget = computed(() => selected.value?.kind === 'product'
  ? { name: 'enterpriseEntity', params: { spaceId: props.spaceId, entityId: selected.value.id.slice('entity:'.length) }, query: pin.value }
  : { name: 'enterpriseConcept', params: { spaceId: props.spaceId, conceptKey: selected.value?.id.slice('concept:'.length) }, query: pin.value })

async function select(node: GraphNode, locate = false) {
  if (locate) locatedId.value = node.kind === 'concept' ? node.id : ''
  selectedId.value = node.id
  searched.value = false
  // Hidden concepts must enter the canvas before its centering method can find them.
  await nextTick()
  if (locate) canvas.value?.locateNode(node.id)
  closeButton.value?.focus()
}
async function locateNode(id: string): Promise<boolean> {
  const node = display.value.available.nodes.find(node => node.id === id)
  if (!node) return false
  await select(node, true)
  return true
}
defineExpose({ locateNode })
function search() {
  searched.value = true
  const match = matches.value[0]
  if (match) void select(match, true)
}
async function close() {
  const id = selectedId.value
  selectedId.value = ''
  await nextTick()
  canvas.value?.focusNode(id)
}
watch(visible, () => { if (!selected.value) selectedId.value = '' })
// A location exception survives closing details so focus can return to that node. Explicit
// filter changes reset the exception and recompute against the newly visible products.
watch([enabled, showAll], () => { locatedId.value = '' }, { flush: 'sync' })
let generation = 0
async function load() {
  const current = ++generation
  state.value = 'loading'; release.value = null; selectedId.value = ''; query.value = ''; searched.value = false
  showAll.value = false; locatedId.value = ''
  try {
    const loaded = props.releaseId ? await readRelease(props.spaceId, props.releaseId) : await readRelease(props.spaceId)
    if (current !== generation) return
    release.value = loaded
    enabled.value = groups.value.map(group => group.key)
    state.value = 'ready'
  } catch (error) {
    if (current !== generation) return
    state.value = error instanceof EnterpriseError && error.code === 'RELEASE_NOT_FOUND' ? 'unpublished' : 'failed'
  }
}
watch(() => [props.spaceId, props.releaseId], load, { immediate: true })
onUnmounted(() => { generation++ })
</script>

<template>
  <main class="ek-page ek-graph-page">
    <header class="ek-graph-heading">
      <div>
        <RouterLink v-if="release" class="ek-back" :to="{ name: 'enterpriseSpace', params: { spaceId }, query: pin }">← {{ t('enterpriseKnowledge.graph.back') }}</RouterLink>
        <h1 class="ek-page__title">{{ t('enterpriseKnowledge.graph.title') }}</h1>
        <p class="ek-page__meta">{{ t('enterpriseKnowledge.graph.description') }}</p>
      </div>
      <span v-if="release" class="ek-meta-tag">{{ t('enterpriseKnowledge.space.version', { epoch: release.epoch }) }}</span>
    </header>
    <p v-if="state === 'loading'" class="ek-status" role="status">{{ t('enterpriseKnowledge.loading') }}</p>
    <div v-else-if="state === 'failed'" class="ek-alert" role="alert">
      <span>{{ t('enterpriseKnowledge.space.failed') }}</span>
      <button type="button" class="ek-button" @click="load">{{ t('enterpriseKnowledge.retry') }}</button>
    </div>
    <p v-else-if="state === 'unpublished'" class="ek-empty">{{ t('enterpriseKnowledge.space.noRelease') }}</p>
    <p v-else-if="!products.length" class="ek-empty">{{ t('enterpriseKnowledge.space.empty') }}</p>
    <template v-else>
      <div class="ek-graph-toolbar">
        <form class="ek-graph-search" data-graph-search @submit.prevent="search">
          <label :for="searchId" class="ek-sr-only">{{ t('enterpriseKnowledge.graph.search') }}</label>
          <input :id="searchId" v-model="query" type="search" :placeholder="t('enterpriseKnowledge.graph.search')"
            @input="searched = true" @keydown.enter.prevent="search" @keydown.esc="searched = false" />
          <button type="submit" class="ek-button">{{ t('enterpriseKnowledge.graph.find') }}</button>
          <ul v-if="searched && query.trim()" class="ek-graph-results">
            <li v-for="node in matchingResults" :key="node.id"><button type="button" @click="select(node, true)">{{ node.title }}</button></li>
            <li v-if="!matches.length" role="status">{{ t('enterpriseKnowledge.graph.noMatch') }}</li>
          </ul>
        </form>
        <label class="ek-graph-all-concepts" data-graph-all-concepts>
          <input v-model="showAll" type="checkbox" role="switch" :aria-checked="showAll" />{{ t('enterpriseKnowledge.graph.showAll') }}
        </label>
      </div>
      <div class="ek-page__meta ek-graph-counts" data-graph-counts aria-live="polite">
        <span>{{ showAll ? t('enterpriseKnowledge.graph.allMode') : t('enterpriseKnowledge.graph.defaultMode') }}</span>
        <span>{{ t('enterpriseKnowledge.graph.counts', { products: visible.nodes.filter(node => node.kind === 'product').length,
          concepts: visible.nodes.filter(node => node.kind === 'concept').length, edges: visible.edges.length }) }}</span>
        <span>{{ t('enterpriseKnowledge.graph.hiddenCommon', { count: display.hiddenConceptCount }) }}</span>
        <span v-if="display.revealedConceptCount">{{ t('enterpriseKnowledge.graph.located', { count: display.revealedConceptCount }) }}</span>
      </div>
      <fieldset class="ek-graph-filters">
        <legend>{{ t('enterpriseKnowledge.graph.filter') }}</legend>
        <label v-for="group in groups" :key="group.key" :data-graph-group="group.key" :style="{ '--group-color': group.color }">
          <input v-model="enabled" type="checkbox" :value="group.key" /><span class="ek-graph-swatch" />{{ group.title }}
        </label>
        <span class="ek-graph-legend"><span class="ek-graph-concept-swatch" />{{ t('enterpriseKnowledge.graph.concept') }}</span>
      </fieldset>
      <div class="ek-graph-workspace">
        <div class="ek-graph-stage">
          <RelationGraphCanvas ref="canvas" :graph="visible" :colors="colors" :selected="selectedId" @select="select" />
          <p v-if="!visible.nodes.length" class="ek-graph-filter-empty" role="status">{{ t('enterpriseKnowledge.graph.noGroups') }}</p>
        </div>
        <aside v-if="selected" class="ek-graph-detail" data-graph-detail :aria-labelledby="detailTitleId" @keydown.esc.prevent="close">
          <div class="ek-graph-detail__top">
            <span class="ek-meta-tag">{{ selected.kind === 'product' ? t('enterpriseKnowledge.concept.columns.product') : t('enterpriseKnowledge.graph.concept') }}</span>
            <button ref="closeButton" type="button" class="ek-button" data-graph-close :aria-label="t('enterpriseKnowledge.graph.close')" @click="close">×</button>
          </div>
          <h2 :id="detailTitleId">{{ selected.title }}</h2>
          <template v-if="selected.kind === 'product'">
            <dl><dt>{{ t('enterpriseKnowledge.concept.columns.group') }}</dt><dd>{{ selected.groupTitle || t('enterpriseKnowledge.nav.other') }}</dd></dl>
            <p class="ek-graph-detail__count">{{ t('enterpriseKnowledge.graph.relatedConcepts', { count: selected.degree }) }}</p>
          </template>
          <template v-else>
            <h3>{{ t('enterpriseKnowledge.concept.definition') }}</h3>
            <span v-if="concept?.definitionGenerated" class="ek-origin ek-origin--generated">{{ t('enterpriseKnowledge.origin.generated') }}</span>
            <p class="ek-graph-definition">{{ concept?.definition || t('enterpriseKnowledge.graph.noDefinition') }}</p>
            <p class="ek-graph-detail__count">{{ t('enterpriseKnowledge.graph.relatedProducts', { count: selected.degree }) }}</p>
          </template>
          <RouterLink class="ek-graph-open" :to="detailTarget">{{ selected.kind === 'product' ? t('enterpriseKnowledge.graph.openProduct') : t('enterpriseKnowledge.graph.openConcept') }} →</RouterLink>
          <p class="ek-page__meta">{{ t('enterpriseKnowledge.graph.pinned') }}</p>
        </aside>
        <aside v-else class="ek-graph-detail ek-graph-detail--empty">
          <span class="ek-graph-detail__icon" aria-hidden="true">◎</span>
          <h2>{{ t('enterpriseKnowledge.graph.choose') }}</h2>
          <p>{{ t('enterpriseKnowledge.graph.chooseHint') }}</p>
        </aside>
      </div>
      <p class="ek-graph-help">{{ t('enterpriseKnowledge.graph.help') }}</p>
    </template>
  </main>
</template>

<style src="./enterprisePage.css"></style>
<style src="./enterpriseGraph.css"></style>

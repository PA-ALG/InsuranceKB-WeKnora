<script setup lang="ts">
import { computed, onUnmounted, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { readRelease, type Release } from './enterpriseApi'
import { conceptView } from './conceptView'
import { stateLabel } from './fieldLabels'
import EnterpriseNavigation from './EnterpriseNavigation.vue'

const props = defineProps<{ spaceId: string; conceptKey: string; releaseId?: string }>()
const { t } = useI18n()
const state = ref<'loading' | 'failed' | 'ready'>('loading')
const release = ref<Release | null>(null)
const view = computed(() => release.value ? conceptView(release.value, props.conceptKey) : null)
let generation = 0
async function load() {
  const current = ++generation
  state.value = 'loading'
  release.value = null
  try {
    const result = props.releaseId ? await readRelease(props.spaceId, props.releaseId) : await readRelease(props.spaceId)
    if (current !== generation) return
    release.value = result
    state.value = 'ready'
  } catch {
    if (current === generation) state.value = 'failed'
  }
}
function entryTarget(entityId: string) {
  return { name: 'enterpriseEntity', params: { spaceId: props.spaceId, entityId }, query: { release: release.value!.id }, hash: `#${props.conceptKey}` }
}
watch(() => [props.spaceId, props.releaseId], load, { immediate: true })
onUnmounted(() => { generation++ })
</script>

<template>
  <main class="ek-page">
    <RouterLink class="ek-back" :to="{ name: 'enterpriseSpace', params: { spaceId }, query: { release: release?.id || releaseId } }">{{ spaceId }}</RouterLink>
    <p v-if="state === 'loading'" role="status" class="ek-status">{{ t('enterpriseKnowledge.loading') }}</p>
    <div v-else-if="state === 'failed'" role="alert" class="ek-alert">
      <span>{{ t('enterpriseKnowledge.concept.failed') }}</span>
      <button type="button" class="ek-button" @click="load">{{ t('enterpriseKnowledge.retry') }}</button>
    </div>
    <div v-else-if="release" class="ek-layout">
      <EnterpriseNavigation :release="release" :space-id="spaceId" :concept-key="conceptKey" />
      <article class="ek-layout__content">
        <p v-if="!view" class="ek-empty">{{ t('enterpriseKnowledge.concept.notFound') }}</p>
        <template v-else>
          <h1 class="ek-page__title">{{ view.title }}</h1>
          <p class="ek-page__meta">{{ t('enterpriseKnowledge.space.version', { epoch: release.epoch }) }}</p>
          <section v-if="view.definition" :class="['ek-section', { 'ek-section--generated': view.definitionGenerated }]" data-concept-definition>
            <h2 class="ek-section__title">{{ t('enterpriseKnowledge.concept.definition') }}</h2>
            <p v-if="view.definitionGenerated" class="ek-page__note">{{ t('enterpriseKnowledge.origin.generated') }}</p>
            <p>{{ view.definition }}</p>
          </section>
          <section v-if="view.summary?.explanation" class="ek-section ek-section--generated" data-concept-explanation>
            <h2 class="ek-section__title">{{ t('enterpriseKnowledge.origin.generated') }}</h2><p>{{ view.summary.explanation }}</p>
          </section>
          <section v-if="view.summary" class="ek-section ek-section--generated" data-concept-summary>
            <h2 class="ek-section__title">{{ t('enterpriseKnowledge.concept.summary') }}</h2>
            <p v-if="view.summary.stale" class="ek-stale" data-concept-stale>{{ t('enterpriseKnowledge.concept.stale') }}</p>
            <p v-for="(statement, index) in view.summary.statements" :key="index" data-concept-statement>
              {{ statement.text }}
              <RouterLink v-for="reference in statement.refs" :key="reference.slug" class="ek-concept-ref" :to="entryTarget(reference.entityId)">{{ reference.name }}</RouterLink>
            </p>
          </section>
          <div class="ek-comparison" tabindex="0" role="region" :aria-label="t('enterpriseKnowledge.concept.comparison')">
            <table>
              <caption>{{ t('enterpriseKnowledge.concept.comparison') }}</caption>
              <thead><tr><th v-for="column in ['group', 'product', 'summary', 'sources']" :key="column" scope="col">{{ t(`enterpriseKnowledge.concept.columns.${column}`) }}</th></tr></thead>
              <tbody>
                <tr v-for="row in view.rows" :key="row.slug" data-concept-row>
                  <td>{{ row.group || t('enterpriseKnowledge.nav.other') }}</td>
                  <th scope="row"><RouterLink :to="entryTarget(row.entityId)">{{ row.name }}</RouterLink></th>
                  <td>{{ row.state === 'present' ? row.summary : stateLabel(t, row.state) }}</td><td>{{ row.evidenceCount }}</td>
                </tr>
              </tbody>
            </table>
          </div>
          <section v-if="view.related.length" class="ek-section">
            <h2 class="ek-section__title">{{ t('enterpriseKnowledge.concept.related') }}</h2>
            <ul><li v-for="related in view.related" :key="related.key" data-concept-related><RouterLink
              :to="{ name: 'enterpriseConcept', params: { spaceId, conceptKey: related.key }, query: { release: release.id } }">{{ related.title }}</RouterLink></li></ul>
          </section>
        </template>
      </article>
    </div>
  </main>
</template>

<style src="./enterprisePage.css"></style>

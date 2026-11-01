<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { readCitation, type Release } from './enterpriseApi'
import { stateLabel } from './fieldLabels'
import { methodView, type MethodMaterial } from './methodView'
import { businessDay } from './productVersions'

// SK-3 §5.3: a sales method of the release on screen. Every item opens its own evidence and every
// citation stays in this release; materials are named by one citation read each.
const props = defineProps<{ release: Release; spaceId: string; entityId: string }>()
const emit = defineEmits<{ open: [member: string, evidence: number] }>()
const { t, te } = useI18n()
const view = computed(() => methodView(props.release, props.entityId))
const day = (instant: string) => businessDay(new Date(instant))
const notice = computed(() => {
  const key = `enterpriseKnowledge.method.notices.${view.value?.notice}`
  return view.value?.notice ? (te(key) ? t(key) : view.value.noticeText) : ''
})
type Read = { state: 'loading' | 'failed' | 'ready'; document?: string; revisedAt?: string }
const reads = ref<Record<string, Read>>({})
let generation = 0
async function readMaterial(material: MethodMaterial, request: number) {
  try {
    const cited = await readCitation(props.spaceId, props.release.id, material.member, material.evidence)
    const source = 'source' in cited ? cited.source : undefined
    if (request === generation) reads.value = { ...reads.value, [material.sourceRef]: { state: 'ready', document: source?.document, revisedAt: source?.revised_at } }
  } catch {
    if (request === generation) reads.value = { ...reads.value, [material.sourceRef]: { state: 'failed' } }
  }
}
watch(() => [props.release.id, props.entityId], () => {
  const request = ++generation
  const materials = view.value?.materials ?? []
  reads.value = Object.fromEntries(materials.map(material => [material.sourceRef, { state: 'loading' } as Read]))
  for (const material of materials) void readMaterial(material, request)
}, { immediate: true })
const target = (entityId: string) => ({ name: 'enterpriseEntity', params: { spaceId: props.spaceId, entityId }, query: { release: props.release.id } })
</script>

<template>
  <div v-if="view" class="ek-method" data-method-page>
    <p class="ek-method__banner" role="note" data-method-banner>{{ t('enterpriseKnowledge.method.banner') }}</p>
    <p v-if="notice" class="ek-method__notice" role="note" data-method-notice>{{ notice }}</p>
    <section v-if="view.labels.length" class="ek-method__labels" :aria-label="t('enterpriseKnowledge.method.labels')">
      <ul>
        <li v-for="label in view.labels" :key="label.label" class="ek-meta-tag" data-method-label>
          {{ label.family ? t('enterpriseKnowledge.method.family', { name: label.family.title }) : label.title }}
        </li>
      </ul>
      <p v-for="label in view.labels.filter(entry => entry.family?.products.length)" :key="`${label.label}/products`" class="ek-page__meta" data-method-family>
        {{ t('enterpriseKnowledge.method.familyProducts') }}
        <RouterLink v-for="product in label.family!.products" :key="product.entityId" class="ek-method__product" :to="target(product.entityId)">{{ product.name }}</RouterLink>
      </p>
    </section>
    <section v-for="field in view.fields" :key="field.slug" class="ek-section ek-method__field" :data-method-field="field.slug">
      <h2 class="ek-section__title">{{ field.title }}</h2>
      <ol v-if="field.items" class="ek-method__items">
        <li v-for="(item, index) in field.items" :key="index" data-method-item>
          <span>{{ item }}</span>
          <button type="button" class="ek-link-button ek-source-chip" data-method-source
            :aria-label="t('enterpriseKnowledge.method.sourceOf', { n: index + 1 })" @click="emit('open', field.slug, index)">{{ t('enterpriseKnowledge.method.source') }}</button>
        </li>
      </ol>
      <template v-else>
        <p v-if="field.text !== null" class="ek-method__text">{{ field.text }}</p>
        <p v-else class="ek-field__state">{{ stateLabel(t, field.state) }}</p>
        <p v-if="field.evidenceCount" class="ek-method__sources">
          <button v-for="index in field.evidenceCount" :key="index" type="button" class="ek-link-button ek-source-chip"
            @click="emit('open', field.slug, index - 1)">{{ t('enterpriseKnowledge.entity.source', { n: index }) }}</button>
        </p>
      </template>
    </section>
    <footer class="ek-method__footer">
      <p v-if="view.materials.length" class="ek-page__meta" data-method-materials>
        {{ t('enterpriseKnowledge.method.materials') }}
        <span v-for="material in view.materials" :key="material.sourceRef" class="ek-method__material">
          <template v-if="reads[material.sourceRef]?.state === 'ready'">{{ reads[material.sourceRef]!.revisedAt
            ? t('enterpriseKnowledge.method.material', { document: reads[material.sourceRef]!.document, date: day(reads[material.sourceRef]!.revisedAt!) })
            : reads[material.sourceRef]!.document }}</template>
          <template v-else-if="reads[material.sourceRef]?.state === 'failed'">{{ t('enterpriseKnowledge.method.materialsFailed') }}</template>
          <template v-else>{{ t('enterpriseKnowledge.method.materialsLoading') }}</template>
        </span>
      </p>
      <p v-if="view.updatedAt" class="ek-page__meta" data-method-updated>{{ t('enterpriseKnowledge.method.updated', { date: day(view.updatedAt) }) }}</p>
    </footer>
  </div>
</template>

<style src="./enterpriseMethod.css"></style>

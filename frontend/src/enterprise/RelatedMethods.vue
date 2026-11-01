<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import type { Release } from './enterpriseApi'
import { relatedMethods } from './methodView'

// SK-3 §5.4: links only; method content never enters a product's field page.
const props = defineProps<{ release: Release; spaceId: string; entityId: string }>()
const { t } = useI18n()
const methods = computed(() => relatedMethods(props.release, props.entityId))
const target = (entityId: string) => ({ name: 'enterpriseEntity', params: { spaceId: props.spaceId, entityId }, query: { release: props.release.id } })
</script>

<template>
  <section v-if="methods.length" class="ek-section ek-related-methods" data-related-methods>
    <h2 class="ek-section__title">{{ t('enterpriseKnowledge.method.related') }}</h2>
    <p class="ek-page__meta">{{ t('enterpriseKnowledge.method.banner') }}</p>
    <ul>
      <li v-for="method in methods" :key="method.entityId"><RouterLink :to="target(method.entityId)">{{ method.name }}</RouterLink></li>
    </ul>
  </section>
</template>

<style src="./enterpriseMethod.css"></style>

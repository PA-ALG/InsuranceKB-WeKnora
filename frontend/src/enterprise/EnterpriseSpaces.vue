<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { listSpaces } from './enterpriseApi'

const { t } = useI18n()
const state = ref<'loading' | 'failed' | 'ready'>('loading')
const spaces = ref<string[]>([])
let generation = 0

async function load() {
  const current = ++generation
  state.value = 'loading'
  try {
    const ids = await listSpaces()
    if (current !== generation) return
    spaces.value = ids
    state.value = 'ready'
  } catch {
    if (current === generation) state.value = 'failed'
  }
}

onMounted(load)
</script>

<template>
  <main class="ek-page">
    <h1 class="ek-page__title">{{ t('enterpriseKnowledge.title') }}</h1>
    <p v-if="state === 'loading'" role="status" class="ek-status">{{ t('enterpriseKnowledge.loading') }}</p>
    <div v-else-if="state === 'failed'" role="alert" class="ek-alert">
      <span>{{ t('enterpriseKnowledge.spaces.failed') }}</span>
      <button type="button" class="ek-button" @click="load">{{ t('enterpriseKnowledge.retry') }}</button>
    </div>
    <p v-else-if="spaces.length === 0" class="ek-empty">{{ t('enterpriseKnowledge.spaces.empty') }}</p>
    <ul v-else class="ek-cards">
      <li v-for="spaceId in spaces" :key="spaceId" class="ek-card">
        <RouterLink class="ek-card__link" :to="{ name: 'enterpriseSpace', params: { spaceId } }">{{ spaceId }}</RouterLink>
      </li>
    </ul>
  </main>
</template>

<style src="./enterprisePage.css"></style>

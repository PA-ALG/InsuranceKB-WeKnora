<script setup lang="ts">
import { computed, nextTick, onUnmounted, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRouter } from 'vue-router'
import { Drawer } from 'tdesign-vue-next'
import { Marked } from 'marked'
import DOMPurify from 'dompurify'
import { readRelease, type Release } from './enterpriseApi'
import { wikiPageView } from './wikiPagesView'
import EnterpriseNavigation from './EnterpriseNavigation.vue'
import CitationPanel from './CitationPanel.vue'

const props = defineProps<{ spaceId: string; entityId: string; pageType?: string; pageSlug?: string; releaseId?: string }>()
const { t } = useI18n(), router = useRouter()
const release = ref<Release | null>(null), state = ref<'loading' | 'failed' | 'ready'>('loading')
const view = computed(() => release.value ? wikiPageView(release.value, props.entityId, `${props.pageType}/${props.pageSlug}`) : null)
const source = ref<{ spaceId: string; releaseId: string; member: string; evidence: number } | null>(null)
let generation = 0, sourceButton: HTMLElement | null = null
const product = computed(() => ({ name: 'enterpriseEntity', params: { spaceId: props.spaceId, entityId: props.entityId }, query: { release: release.value?.id } }))
const escapeHTML = (text: string) => text.replace(/[&<>"']/g, char => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[char]!)
function wikiTarget(slug: string) {
  const parts = slug.split('/'), [, entityId, pageType, pageSlug] = parts
  if (parts.length !== 4 || parts[0] !== 'wiki' || !entityId || !pageSlug ||
    (pageType !== 'concept' && pageType !== 'entity') ||
    [entityId, pageSlug].some(part => part !== part.trim() || part === '.' || part === '..') || !release.value) return null
  return { name: 'enterpriseWikiPage', params: { spaceId: props.spaceId, entityId, pageType, pageSlug }, query: { release: release.value.id } }
}
// A local parser avoids global Markdown extensions. Raw HTML cannot forge the navigation marker.
const markdown = new Marked({
  renderer: { html: () => '' },
  extensions: [{
    name: 'wikiLink', level: 'inline', start: text => text.indexOf('[['),
    tokenizer(text) {
      const match = /^\[\[([^\]\n]+)\]\]/.exec(text)
      if (!match) return
      const [slug, ...label] = match[1]!.split('|')
      return { type: 'wikiLink', raw: match[0], slug, label: label.length ? label.join('|') : slug }
    },
    renderer(token) {
      const target = wikiTarget(token.slug), label = escapeHTML(token.label)
      return target ? `<a data-wiki-link="${escapeHTML(token.slug)}" href="${escapeHTML(router.resolve(target).href)}">${label}</a>` : label
    },
  }],
})
const html = computed(() => DOMPurify.sanitize(markdown.parse(view.value?.content ?? '', { async: false }), {
  USE_PROFILES: { html: true }, ALLOW_DATA_ATTR: false, ADD_ATTR: ['data-wiki-link'], FORBID_ATTR: ['style'],
}))
function followLink(event: MouseEvent) {
  if (event.defaultPrevented || event.button !== 0 || event.ctrlKey || event.metaKey || event.shiftKey || event.altKey) return
  const link = event.target instanceof Element ? event.target.closest<HTMLAnchorElement>('a[data-wiki-link]') : null
  const target = link ? wikiTarget(link.dataset.wikiLink ?? '') : null
  if (target) { event.preventDefault(); void router.push(target) }
}
function openSource(index: number, event: MouseEvent) {
  if (!view.value || !release.value) return
  sourceButton = event.currentTarget as HTMLElement
  source.value = { spaceId: props.spaceId, releaseId: release.value.id, member: view.value.slug, evidence: index }
}
async function closeSource() {
  source.value = null
  await nextTick()
  if (sourceButton?.isConnected) sourceButton.focus()
}
async function load() {
  const request = ++generation, space = props.spaceId, id = props.releaseId
  state.value = 'loading'; release.value = null
  try {
    const result = await (id ? readRelease(space, id) : readRelease(space))
    if (request !== generation) return
    if (!result.id || result.id === 'active' || (id && id !== 'active' && result.id !== id)) throw new Error('INVALID_RELEASE')
    release.value = result; state.value = 'ready'
  } catch { if (request === generation) state.value = 'failed' }
}
watch(() => [props.spaceId, props.releaseId], load, { immediate: true })
watch(() => [props.spaceId, props.releaseId, props.entityId, props.pageType, props.pageSlug], () => { source.value = null; sourceButton = null })
onUnmounted(() => { generation++ })
</script>

<template>
  <main class="ek-page">
    <p v-if="state === 'loading'" role="status" class="ek-status">{{ t('enterpriseKnowledge.loading') }}</p>
    <div v-else-if="state === 'failed'" role="alert" class="ek-alert">
      <span>{{ t('enterpriseKnowledge.wiki.failed') }}</span>
      <button type="button" class="ek-button" @click="load">{{ t('enterpriseKnowledge.retry') }}</button>
    </div>
    <template v-else-if="release">
      <RouterLink class="ek-back" :to="{ name: 'enterpriseSpace', params: { spaceId }, query: { release: release.id } }">← {{ spaceId }}</RouterLink>
      <div class="ek-layout">
        <EnterpriseNavigation :release="release" :space-id="spaceId" :entity-id="entityId" />
        <article class="ek-layout__content">
          <div v-if="view" data-wiki-page>
            <h1 class="ek-page__title">{{ view.title }}</h1>
            <p class="ek-wiki-generated" data-wiki-generated>{{ t('enterpriseKnowledge.wiki.generated') }}</p>
            <p class="ek-page__meta">{{ t('enterpriseKnowledge.space.version', { epoch: release.epoch }) }}</p>
            <p v-if="view.summary" class="ek-wiki-summary">{{ view.summary }}</p>
            <div class="ek-wiki-content" @click="followLink" v-html="html"></div>
            <section v-if="view.evidence.length" class="ek-wiki-sources" :aria-label="t('enterpriseKnowledge.wiki.sources')">
              <h2>{{ t('enterpriseKnowledge.wiki.sources') }}</h2>
              <ol>
                <li v-for="evidence in view.evidence" :key="evidence.index">
                  <button type="button" class="ek-button" data-wiki-source @click="openSource(evidence.index, $event)">{{ t('enterpriseKnowledge.wiki.source', { n: evidence.index + 1 }) }}</button>
                  <span class="ek-page__meta">{{ t('enterpriseKnowledge.citation.page', { page: evidence.page }) }}</span>
                  <blockquote>{{ evidence.quote }}</blockquote>
                </li>
              </ol>
            </section>
          </div>
          <p v-else class="ek-empty">{{ t('enterpriseKnowledge.wiki.notFound') }}</p>
          <RouterLink class="ek-back ek-wiki-back" :to="product">← {{ t('enterpriseKnowledge.wiki.back') }}</RouterLink>
        </article>
      </div>
    </template>
    <Drawer v-if="source" :visible="true" size="min(640px, 100vw)" :footer="false" destroy-on-close :header="t('enterpriseKnowledge.wiki.source', { n: source.evidence + 1 })" @close="closeSource">
      <CitationPanel :space-id="source.spaceId" :release-id="source.releaseId" :member="source.member" :evidence="source.evidence" />
    </Drawer>
  </main>
</template>

<style src="./enterprisePage.css"></style>
<style scoped>
.ek-wiki-generated { border-left: 3px solid var(--td-warning-color); background: var(--td-warning-color-1); color: var(--td-text-color-primary); padding: 12px 16px; border-radius: 0 6px 6px 0; font-weight: 600; }
.ek-wiki-summary { color: var(--td-text-color-secondary); font-size: 16px; line-height: 1.8; white-space: pre-wrap; }
.ek-wiki-content { margin: 24px 0; font-size: 15px; line-height: 1.85; overflow-wrap: anywhere; }
.ek-wiki-content :deep(h1) { font-size: 24px; }
.ek-wiki-content :deep(h2) { font-size: 20px; margin-top: 28px; }
.ek-wiki-content :deep(h3) { font-size: 17px; }
.ek-wiki-content :deep(pre) { overflow-x: auto; padding: 12px; background: var(--td-bg-color-secondarycontainer); border-radius: 6px; }
.ek-wiki-content :deep(table) { display: block; overflow-x: auto; border-collapse: collapse; }
.ek-wiki-content :deep(th), .ek-wiki-content :deep(td) { border: 1px solid var(--td-border-level-1-color); padding: 6px 12px; }
.ek-wiki-content :deep(img) { max-width: 100%; height: auto; }
.ek-wiki-content :deep(blockquote), .ek-wiki-sources blockquote { margin: 8px 0 16px; padding-left: 12px; border-left: 2px solid var(--td-border-level-2-color); color: var(--td-text-color-secondary); white-space: pre-wrap; }
.ek-wiki-content :deep(a:focus-visible) { outline: 2px solid var(--td-brand-color); outline-offset: 2px; }
.ek-wiki-sources { border-top: 1px solid var(--td-border-level-1-color); padding-top: 20px; margin-top: 32px; }
.ek-wiki-sources h2 { font-size: 16px; }
.ek-wiki-sources ol { list-style: none; padding: 0; }
.ek-wiki-sources .ek-button { margin-right: 12px; }
.ek-wiki-back { display: inline-block; margin-top: 24px; }
</style>

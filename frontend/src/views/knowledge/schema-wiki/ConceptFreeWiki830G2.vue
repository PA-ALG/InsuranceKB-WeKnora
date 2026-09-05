<script setup lang="ts">
import { computed, ref, shallowRef, watch } from 'vue'
import { useRoute } from 'vue-router'
import { readConceptPage830G2, conceptCitationTransport830G2,
  type ConceptSession830G2, type ConceptMember830G2 } from '@/api/schema-wiki/conceptFreeWiki830G2'
import { buildSchemaCitationPreviewRequest } from '@/api/schema-wiki'
import ConceptCitationViewer830G2 from '@/components/schema-wiki/ConceptCitationViewer830G2.vue'
import { createPdfJsPort } from '@/components/schema-wiki/pdfJsPort'
import SettingDrawer from '@/components/settings/SettingDrawer.vue'
import { get } from '@/utils/request'

const route = useRoute()
const session = shallowRef<ConceptSession830G2 | null>(null)
const loading = ref(true)
const error = ref('')
const selected = ref<string | null>(null)
const pdfPort = createPdfJsPort()
let generation = 0
const read = computed(() => session.value?.read)
const previewTransport = computed(() => session.value ? conceptCitationTransport830G2(session.value, {
  get: path => get(path),
  getBytes: async path => new Uint8Array(await get<ArrayBuffer>(path, { responseType: 'arraybuffer' })),
}) : null)
const previewRequest = computed(() => read.value && selected.value ? buildSchemaCitationPreviewRequest({
  release_id: read.value.release_id, activation_epoch: read.value.activation_epoch,
  field_id: read.value.member.member_id, citation_id: selected.value,
}) : null)
function link(member: ConceptMember830G2) {
  return { name: 'conceptPage830G2', params: { kbId: route.params.kbId, memberId: member.member_id },
    query: { release_id: read.value?.release_id } }
}
function stateLabel(member: ConceptMember830G2) {
  return member.payload.state === 'unknown' ? '待补充'
    : member.payload.state === 'absent_explicitly' ? '材料明确不提供' : '材料已确认'
}
async function load() {
  const current = ++generation
  session.value = null; selected.value = null; loading.value = true; error.value = ''
  try {
    const release = route.query.release_id
    if (Object.keys(route.query).some(k => k !== 'release_id')
      || (release !== undefined && typeof release !== 'string')) throw new Error('INVALID_READ_MODE')
    const loaded = await readConceptPage830G2(String(route.params.kbId ?? ''),
      String(route.params.memberId ?? ''), release, { get: path => get(path) })
    if (current === generation) session.value = loaded
  } catch {
    if (current === generation) error.value = '页面读取失败，请确认页面已发布且你有访问权限。'
  } finally {
    if (current === generation) loading.value = false
  }
}
watch(() => [route.params.kbId, route.params.memberId, route.query], load, { immediate: true, deep: true })
</script>

<template>
  <main class="concept-page">
    <p v-if="loading" role="status">正在读取知识页面…</p>
    <p v-else-if="error" role="alert">{{ error }}</p>
    <template v-else-if="read">
      <header>
        <span class="concept-page__label">{{ read.member.kind === 'concept' ? '共享定义' : '已发布知识' }}</span>
        <h1>{{ read.member.title }}</h1>
        <p v-if="read.member.kind === 'field_assertion'" class="concept-page__meta">
          {{ read.member.owner_id }} · {{ read.member.payload.entity_version }} · {{ stateLabel(read.member) }}
        </p>
      </header>
      <article class="concept-page__body">{{ read.member.content }}</article>
      <section v-if="read.citations.length" class="concept-page__sources" aria-label="原文证据">
        <h2>原文证据</h2>
        <button v-for="citation in read.citations" :key="citation.citation_id" type="button"
          data-testid="g2-source" @click="selected = citation.citation_id">
          查看第 {{ citation.page_number }} 页原文
        </button>
      </section>
      <section v-if="read.related_members.length" aria-label="相关知识">
        <h2>{{ read.member.kind === 'concept' ? '各实体的具体规定' : '相关知识' }}</h2>
        <ul class="concept-page__related">
          <li v-for="member in read.related_members" :key="member.member_id">
            <RouterLink :to="link(member)">{{ member.title }}</RouterLink>
            <p v-if="member.kind === 'field_assertion'" class="concept-page__meta">
              {{ member.owner_id }} · {{ member.payload.entity_version }} · {{ stateLabel(member) }}
            </p>
            <p class="concept-page__body">{{ member.content }}</p>
          </li>
        </ul>
      </section>
      <SettingDrawer v-if="previewRequest && previewTransport" :visible="selected !== null"
        title="查看原文" description="当前页面所引用的固定版本原文" icon="file" width="760px"
        :min-width="560" :max-width="1000" storage-key="setting-drawer:width:concept-source-830-g2"
        hide-footer @update:visible="visible => { if (!visible) selected = null }">
        <ConceptCitationViewer830G2 v-if="session" :key="selected!" :session="session" :citation-id="selected!"
          :preview-transport="previewTransport" :pdf-port="pdfPort" />
      </SettingDrawer>
    </template>
  </main>
</template>

<style scoped>
.concept-page { max-width: 1080px; margin: 0 auto; padding: 36px; color: var(--td-text-color-primary); }
.concept-page__label { color: var(--td-brand-color); font-size: 13px; }
h1 { margin: 8px 0 24px; font-size: 28px; }
h2 { margin: 28px 0 12px; font-size: 18px; }
.concept-page__body { white-space: pre-wrap; overflow-wrap: anywhere; line-height: 1.8; }
.concept-page__meta { color: var(--td-text-color-secondary); font-size: 13px; }
.concept-page__related { list-style: none; padding: 0; }
.concept-page__related li { padding: 18px 0; border-bottom: 1px solid var(--td-component-border); }
.concept-page__related a { color: var(--td-brand-color); text-decoration: none; font-weight: 600; }
.concept-page__sources button { margin: 0 10px 8px 0; border: 1px solid var(--td-component-border);
  border-radius: 6px; padding: 8px 12px; color: var(--td-brand-color); background: transparent; cursor: pointer; }
@media (max-width: 700px) { .concept-page { padding: 20px; } }
</style>

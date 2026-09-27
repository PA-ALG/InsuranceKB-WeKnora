<script setup lang="ts">
import { computed, ref, watch } from 'vue'

import type {
  SchemaPackCatalog830G3,
  SchemaPackField830G3,
} from '@/api/schema-wiki/schemaPackCatalog830G3'

const props = defineProps<{ catalog: SchemaPackCatalog830G3 }>()
const selectedPackID = ref('')
const selectedSectionKey = ref('')

const fieldCount = computed(() => props.catalog.entries.reduce(
  (total, entry) => total + entry.pack.fields.length, 0,
))
const selectedEntry = computed(() => props.catalog.entries.find(
  entry => entry.pack.schema_pack_id === selectedPackID.value,
) ?? props.catalog.entries[0])
const selectedSection = computed(() => selectedEntry.value.profile.sections.find(
  section => section.section_key === selectedSectionKey.value,
) ?? selectedEntry.value.profile.sections[0])
const fieldsByKey = computed(() => new Map(selectedEntry.value.pack.fields.map(field => [field.field_key, field])))
const displayedFields = computed(() => selectedSection.value.fields.map(field => fieldsByKey.value.get(field.field_key)!))

function selectPack(packID: string) {
  const entry = props.catalog.entries.find(item => item.pack.schema_pack_id === packID)
  if (!entry) return
  selectedPackID.value = packID
  selectedSectionKey.value = entry.profile.sections[0].section_key
}

function display(value: string | number | null): string {
  return value === null || value === '' ? '工作簿未填写' : String(value)
}

function fieldValues(field: SchemaPackField830G3): Array<string | number | null> {
  return [
    field.schema_category, field.short_title, field.value_spec, field.field_key,
    field.description, field.source_guidance, field.formation_method, field.knowledge_role,
    field.common_field_marker, field.other_applicable_products, field.usage_frequency,
  ]
}

watch(() => props.catalog, catalog => selectPack(catalog.entries[0].pack.schema_pack_id), { immediate: true })
</script>

<template>
  <section class="pack-catalog" data-testid="schema-pack-catalog-830-g3">
    <header class="pack-catalog__header">
      <div>
        <p class="pack-catalog__eyebrow">保险产品 Schema Catalog</p>
        <h2>产品结构目录</h2>
        <p data-testid="catalog-counts">{{ catalog.entries.length }} 个产品结构 · {{ fieldCount }} 个字段</p>
      </div>
      <div class="pack-catalog__statuses" aria-label="目录状态">
        <span>结构待确认</span>
        <span>业务质量待评估</span>
      </div>
    </header>

    <nav class="pack-catalog__packs" aria-label="选择产品结构">
      <button
        v-for="entry in catalog.entries"
        :key="entry.pack.schema_pack_id"
        type="button"
        data-testid="catalog-pack-action"
        :data-pack-id="entry.pack.schema_pack_id"
        :class="{ active: entry.pack.schema_pack_id === selectedEntry.pack.schema_pack_id }"
        @click="selectPack(entry.pack.schema_pack_id)"
      >
        <strong>{{ entry.pack.display_name }}</strong>
        <small>{{ entry.profile.sections.length }} 个节点 · {{ entry.pack.fields.length }} 个字段</small>
      </button>
    </nav>

    <article class="pack-catalog__review">
      <header>
        <div>
          <p class="pack-catalog__eyebrow">整包结构审查</p>
          <h3 data-testid="catalog-selected-pack">{{ selectedEntry.pack.display_name }}</h3>
          <p>{{ selectedEntry.pack.applicable_classifications.join('、') }}</p>
        </div>
        <details>
          <summary>查看版本与校验信息</summary>
          <dl>
            <dt>Catalog</dt><dd>{{ catalog.catalog_id }} @ {{ catalog.catalog_version }}</dd>
            <dt>Schema Pack</dt><dd>{{ selectedEntry.pack.schema_pack_id }} @ {{ selectedEntry.pack.schema_version }}</dd>
            <dt>Pack hash</dt><dd><code>{{ selectedEntry.pack.schema_pack_sha256 }}</code></dd>
            <dt>Profile</dt><dd>{{ selectedEntry.profile.profile_id }} @ {{ selectedEntry.profile.profile_version }}</dd>
            <dt>Profile hash</dt><dd><code>{{ selectedEntry.profile.profile_sha256 }}</code></dd>
          </dl>
        </details>
      </header>

      <nav class="pack-catalog__sections" aria-label="选择展示节点">
        <button
          v-for="section in selectedEntry.profile.sections"
          :key="section.section_key"
          type="button"
          data-testid="catalog-section-action"
          :class="{ active: section.section_key === selectedSection.section_key }"
          @click="selectedSectionKey = section.section_key"
        >
          {{ section.display_name }} <small>{{ section.fields.length }}</small>
        </button>
      </nav>

      <section class="pack-catalog__fields">
        <header>
          <h4>{{ selectedSection.display_name }}</h4>
          <p>{{ displayedFields.length }} 个字段，顺序来自候选展示 Profile</p>
        </header>
        <div class="pack-catalog__table-scroll">
          <table>
            <thead><tr>
              <th v-for="heading in ['业务分类', '字段名', '取值', '英文名', '说明', '取值来源',
                '知识形成方式', '知识角色', '公共字段', '其它适用险种', '使用频次']" :key="heading">
                {{ heading }}
              </th>
            </tr></thead>
            <tbody>
              <tr v-for="field in displayedFields" :key="field.field_key">
                <td v-for="(value, index) in fieldValues(field)" :key="index" :class="{ empty: value === null || value === '' }">
                  {{ display(value) }}
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </section>
    </article>
  </section>
</template>

<style scoped>
.pack-catalog { padding: 28px; color: var(--td-text-color-primary); background: var(--td-bg-color-page); }
.pack-catalog__header, .pack-catalog__review > header { display: flex; justify-content: space-between; gap: 24px; align-items: flex-start; }
.pack-catalog h2, .pack-catalog h3, .pack-catalog h4 { margin: 4px 0 8px; }
.pack-catalog__eyebrow { margin: 0; color: var(--td-brand-color); font-size: 12px; font-weight: 700; letter-spacing: .08em; text-transform: uppercase; }
.pack-catalog__statuses { display: flex; flex-wrap: wrap; gap: 8px; }
.pack-catalog__statuses span { padding: 6px 10px; border-radius: 999px; background: var(--td-warning-color-light); color: var(--td-warning-color); font-size: 12px; font-weight: 700; }
.pack-catalog__packs { display: grid; grid-template-columns: repeat(auto-fit, minmax(156px, 1fr)); gap: 10px; margin: 24px 0; }
.pack-catalog button { border: 1px solid var(--td-component-border); border-radius: 8px; background: var(--td-bg-color-container); color: inherit; cursor: pointer; text-align: left; }
.pack-catalog button.active { border-color: var(--td-brand-color); box-shadow: inset 0 0 0 1px var(--td-brand-color); }
.pack-catalog__packs button { display: grid; gap: 5px; padding: 12px; }
.pack-catalog__packs small, .pack-catalog__sections small { color: var(--td-text-color-secondary); }
.pack-catalog__review { padding: 22px; border: 1px solid var(--td-component-border); border-radius: 12px; background: var(--td-bg-color-container); }
.pack-catalog__review details { max-width: 620px; }
.pack-catalog__review dl { display: grid; grid-template-columns: max-content minmax(0, 1fr); gap: 6px 12px; }
.pack-catalog__review dd { margin: 0; overflow-wrap: anywhere; }
.pack-catalog__sections { display: flex; flex-wrap: wrap; gap: 8px; margin: 20px 0; }
.pack-catalog__sections button { padding: 8px 12px; }
.pack-catalog__fields > header { display: flex; justify-content: space-between; align-items: baseline; gap: 16px; }
.pack-catalog__table-scroll { overflow: auto; border: 1px solid var(--td-component-border); border-radius: 8px; }
.pack-catalog table { width: 100%; min-width: 1900px; border-collapse: collapse; font-size: 13px; }
.pack-catalog th, .pack-catalog td { padding: 10px 12px; border-bottom: 1px solid var(--td-component-border); vertical-align: top; text-align: left; white-space: pre-wrap; }
.pack-catalog th { position: sticky; top: 0; background: var(--td-bg-color-secondarycontainer); }
.pack-catalog td.empty { color: var(--td-text-color-placeholder); font-style: italic; }
@media (max-width: 900px) { .pack-catalog { padding: 16px; } .pack-catalog__header, .pack-catalog__review > header { display: grid; } }
</style>

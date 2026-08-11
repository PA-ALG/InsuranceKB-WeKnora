<script setup lang="ts">
import { nextTick, onMounted, ref, shallowRef } from 'vue'

import type { SchemaWikiClient } from '../../../api/schema-wiki/index.ts'
import type { PdfPort, RenderedPdfPage } from '../../../components/schema-wiki/pdfJsPort.ts'
import {
  assertGoldenSummaryDossierJoin,
  goldenEvidenceHighlightStyle,
  goldenQualityStatusPresentation,
  parseSchemaWikiGoldenEvidencePreviewAuthority,
  parseSchemaWikiGoldenQualityDossier,
  parseSchemaWikiGoldenQualitySummary,
  type Schema67GoldenFieldDecisionV1,
  type SchemaWikiGoldenQualityDossierV1,
  type SchemaWikiGoldenQualitySummaryV1,
} from './schemaWikiGoldenQualityContract.ts'
import type {
  GoldenReviewerPresentation,
} from './schemaWikiGoldenReviewerPresentation.ts'
import {
  goldenSuccessorStatusPresentation,
  parseSchemaWikiGoldenSuccessorStatus,
} from './schemaWikiGoldenSuccessorStatusContract.ts'

const props = defineProps<{
  client: SchemaWikiClient
  preparationId: string
  evaluationId: string
  evidenceSelection?: { readonly field_id: string; readonly evidence_id: string }
  getBytesByToken: (opaqueToken: string) => Promise<Uint8Array>
  pdfPort: PdfPort
}>()

const emit = defineEmits<{
  previewEvidence: [selection: { readonly fieldId: string; readonly evidenceId: string }]
}>()

const summary = ref<SchemaWikiGoldenQualitySummaryV1 | null>(null)
const dossier = ref<SchemaWikiGoldenQualityDossierV1 | null>(null)
const reviewPresentation = ref<GoldenReviewerPresentation | null>(null)
const qualityError = ref<string | null>(null)
const evidenceError = ref<string | null>(null)
const renderedPage = shallowRef<RenderedPdfPage | null>(null)
const highlightStyle = ref<Record<string, string> | null>(null)
const canvasHost = ref<HTMLElement | null>(null)

function correctness(row: Schema67GoldenFieldDecisionV1): 'PASS' | 'FAIL' {
  return row.state_correct && row.value_correct ? 'PASS' : 'FAIL'
}

function completeness(row: Schema67GoldenFieldDecisionV1): 'PASS' | 'FAIL' {
  return row.atom_false_negative === 0
    && row.evidence_fragments === row.evidence_fragments_matched
    && row.bbox_required === row.bbox_passed
    ? 'PASS'
    : 'FAIL'
}

async function sha256Hex(bytes: Uint8Array): Promise<string> {
  const copy = Uint8Array.from(bytes)
  const digest = await globalThis.crypto.subtle.digest('SHA-256', copy.buffer)
  return Array.from(new Uint8Array(digest), byte => byte.toString(16).padStart(2, '0')).join('')
}

async function loadEvidence(candidateSha256: string): Promise<void> {
  if (!props.evidenceSelection) return
  try {
    const request = {
      preparation_id: props.preparationId,
      evaluation_id: props.evaluationId,
      field_id: props.evidenceSelection.field_id,
      evidence_id: props.evidenceSelection.evidence_id,
    }
    const authority = parseSchemaWikiGoldenEvidencePreviewAuthority(
      await props.client.getGoldenEvidencePreview(
        request.preparation_id,
        request.evaluation_id,
        request.field_id,
        request.evidence_id,
      ),
      { ...request, candidateSha256 },
    )
    const bytes = await props.getBytesByToken(authority.opaque_token)
    if (!(bytes instanceof Uint8Array) || bytes.byteLength === 0) {
      throw new Error('GOLDEN_EVIDENCE_UNAVAILABLE')
    }
    if (await sha256Hex(bytes) !== authority.revision_source.file_sha256) {
      throw new Error('PREVIEW_BYTES_HASH_MISMATCH')
    }
    const opened = await props.pdfPort.open(bytes.slice())
    if (opened.pageCount !== authority.revision_source.page_count
      || authority.page_number > opened.pageCount) {
      throw new Error('PAGE_UNAVAILABLE')
    }
    const page = await opened.renderPage(authority.page_number)
    if (page.pageNumber !== authority.page_number) throw new Error('PAGE_UNAVAILABLE')
    const bbox = goldenEvidenceHighlightStyle(authority, { width: page.width, height: page.height })
    renderedPage.value = page
    highlightStyle.value = {
      left: `${bbox.left}px`,
      top: `${bbox.top}px`,
      width: `${bbox.width}px`,
      height: `${bbox.height}px`,
    }
    await nextTick()
    canvasHost.value?.replaceChildren(page.canvas)
  } catch (error: unknown) {
    renderedPage.value = null
    highlightStyle.value = null
    evidenceError.value = error instanceof Error
      && ['PAGE_UNAVAILABLE', 'BBOX_UNAVAILABLE', 'PREVIEW_BYTES_HASH_MISMATCH'].includes(error.message)
      ? error.message
      : 'GOLDEN_EVIDENCE_UNAVAILABLE'
  }
}

onMounted(async () => {
  try {
    const status = await parseSchemaWikiGoldenSuccessorStatus(
      await props.client.getGoldenSuccessorStatus(),
      {
        spaceId: props.client.scope.space_id,
        rawKbId: props.client.scope.raw_kb_id,
        wikiKbId: props.client.scope.wiki_kb_id,
      },
    )
    reviewPresentation.value = goldenSuccessorStatusPresentation(status)
  } catch {
    reviewPresentation.value = null
  }
  try {
    const expected = { preparationId: props.preparationId, evaluationId: props.evaluationId }
    const [summaryValue, dossierValue] = await Promise.all([
      props.client.getGoldenQualitySummary(props.preparationId, props.evaluationId),
      props.client.getGoldenQualityDossier(props.preparationId, props.evaluationId),
    ])
    const exactSummary = parseSchemaWikiGoldenQualitySummary(summaryValue, expected)
    const exactDossier = parseSchemaWikiGoldenQualityDossier(dossierValue, expected)
    assertGoldenSummaryDossierJoin(exactSummary, exactDossier)
    const presentation = goldenQualityStatusPresentation(exactSummary.public_aggregate.status)
    if (!presentation.readable) throw new Error('GOLDEN_QUALITY_UNAVAILABLE')
    summary.value = exactSummary
    dossier.value = exactDossier
    await loadEvidence(exactDossier.private_dossier.candidate_sha256)
  } catch {
    summary.value = null
    dossier.value = null
    qualityError.value = 'GOLDEN_QUALITY_UNAVAILABLE'
  }
})
</script>

<template>
  <section class="golden-quality-review" data-testid="golden-quality-review">
    <section
      v-if="reviewPresentation"
      class="golden-quality-review__successor"
      data-testid="golden-review-summary"
      aria-label="Golden review successor"
    >
      <header>
        <h2>Schema67 人工审核迁移状态</h2>
        <p data-testid="golden-review-reviewed-by">
          Source review: {{ reviewPresentation.sourceReview.status }} · reviewer {{ reviewPresentation.sourceReview.reviewedBy }}
        </p>
        <p data-testid="golden-review-annotator">
          Annotator model: {{ reviewPresentation.sourceReview.annotatorModelId }}
        </p>
        <p data-testid="golden-review-reviewed-at">
          Reviewed at: {{ reviewPresentation.sourceReview.reviewedAtLabel }}
        </p>
        <p data-testid="golden-review-attestor">
          Fact attestor: {{ reviewPresentation.sourceReview.attestedBy }}（非 reviewer）
        </p>
        <p data-testid="golden-review-mapping">
          Schema67 mapping: {{ reviewPresentation.mapping.status }} ·
          {{ reviewPresentation.mapping.closedCount }} 已闭合 ·
          {{ reviewPresentation.mapping.residualCount }} 未映射
        </p>
        <p data-testid="golden-review-admission">
          Golden admission: {{ reviewPresentation.admission.status }} ·
          {{ reviewPresentation.admission.readyToSignStatus }} ·
          receipt {{ reviewPresentation.admission.receiptStatus }} ·
          {{ reviewPresentation.admission.blockingReasonCodes.join(' · ') }}
        </p>
      </header>
    </section>

    <p v-if="qualityError" data-testid="golden-quality-error" role="alert">
      {{ qualityError }}
    </p>
    <template v-else-if="summary && dossier">
      <header>
        <h2>Schema67 Golden quality</h2>
        <p data-testid="golden-quality-status">
          {{ summary.public_aggregate.status }} · {{ goldenQualityStatusPresentation(summary.public_aggregate.status).label }}
        </p>
        <p class="golden-quality-review__notice">
          Read-only preparation evaluation · no serving effect
        </p>
      </header>

      <section aria-label="Quality metrics">
        <h3>Quality metrics (15)</h3>
        <table>
          <tbody>
            <tr
              v-for="metric in summary.public_aggregate.metrics"
              :key="metric.metric_id"
              data-testid="golden-metric-row"
            >
              <th scope="row">{{ metric.metric_id }}</th>
              <td>{{ metric.evaluability }}</td>
              <td>{{ metric.value_ppm === null ? 'N/A' : `${metric.value_ppm} ppm` }}</td>
              <td>{{ metric.admission_status }}</td>
            </tr>
          </tbody>
        </table>
      </section>

      <section aria-label="Field comparisons">
        <h3>Field comparisons (67)</h3>
        <article
          v-for="field in dossier.private_dossier.field_decisions"
          :key="field.field_id"
          class="golden-quality-review__field"
          data-testid="golden-field-row"
        >
          <h4>{{ field.field_id }}</h4>
          <dl>
            <dt>Candidate state</dt><dd>{{ field.candidate_state }}</dd>
            <dt>Golden state</dt><dd>{{ field.golden_state }}</dd>
            <dt>Correctness</dt><dd>{{ correctness(field) }}</dd>
            <dt>Completeness</dt><dd>{{ completeness(field) }}</dd>
            <dt>Value comparison</dt><dd>{{ field.value_correct ? 'MATCH' : 'DIFF' }}</dd>
            <dt>Evidence branches</dt>
            <dd>{{ field.evidence_fragments_matched }}/{{ field.evidence_fragments }}</dd>
            <dt>BBox checks</dt><dd>{{ field.bbox_passed }}/{{ field.bbox_required }}</dd>
            <dt>High risk</dt><dd>{{ field.high_risk_pass ? 'PASS' : 'FLAGGED' }}</dd>
            <dt>Conflict</dt><dd>{{ field.conflict_resolved ? 'RESOLVED' : 'FLAGGED' }}</dd>
          </dl>
        </article>
      </section>

      <section v-if="evidenceSelection" aria-label="Evidence preview">
        <p v-if="evidenceError" data-testid="golden-evidence-error" role="status">
          {{ evidenceError }}
        </p>
        <div
          v-else-if="renderedPage"
          class="golden-quality-review__page"
          data-testid="golden-evidence-page"
          :data-page-number="renderedPage.pageNumber"
          :style="{ width: `${renderedPage.width}px`, height: `${renderedPage.height}px` }"
        >
          <div ref="canvasHost" />
          <span
            v-if="highlightStyle"
            class="golden-quality-review__highlight"
            data-testid="golden-evidence-highlight"
            :style="highlightStyle"
          />
        </div>
      </section>
    </template>
  </section>
</template>

<style scoped>
.golden-quality-review { display: grid; gap: 24px; }
.golden-quality-review__successor { display: grid; gap: 20px; }
.golden-quality-review__notice { color: var(--td-text-color-secondary); }
.golden-quality-review table { width: 100%; border-collapse: collapse; }
.golden-quality-review th,
.golden-quality-review td { padding: 8px; border-bottom: 1px solid var(--td-component-border); text-align: left; }
.golden-quality-review__field { padding: 16px 0; border-bottom: 1px solid var(--td-component-border); }
.golden-quality-review__field dl { display: grid; grid-template-columns: 150px 1fr; gap: 6px 12px; }
.golden-quality-review__field dt { color: var(--td-text-color-secondary); }
.golden-quality-review__field dd { margin: 0; }
.golden-quality-review__page { position: relative; }
.golden-quality-review__highlight {
  position: absolute;
  border: 2px solid #e89b19;
  background: rgb(255 207 64 / 24%);
  pointer-events: none;
}
</style>

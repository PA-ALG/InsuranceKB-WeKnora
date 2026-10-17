// Display labels for the generic claim state and origin values. Each key is written out in a
// literal t() call so the locale key audit covers it; unknown values are shown as they are.

export type Translate = (key: string, named?: Record<string, unknown>) => string

export function stateLabel(t: Translate, state: string): string {
  switch (state) {
    case 'absent_explicitly':
      return t('enterpriseKnowledge.state.absent')
    case 'unknown':
      return t('enterpriseKnowledge.state.unknown')
    default:
      return state
  }
}

export function originLabel(t: Translate, origin: string): string {
  switch (origin) {
    case 'SOURCE_SUPPORTED':
      return t('enterpriseKnowledge.origin.source')
    case 'MIXED':
      return t('enterpriseKnowledge.origin.mixed')
    case 'MODEL_GENERATED':
      return t('enterpriseKnowledge.origin.generated')
    case 'EXPERT_REVISION':
      return t('enterpriseKnowledge.origin.expert')
    case 'STRUCTURED_IMPORT':
      return t('enterpriseKnowledge.origin.imported')
    default:
      return origin
  }
}

export function citationFailure(t: Translate, code: string): string {
  switch (code) {
    case 'EVIDENCE_MISMATCH':
      return t('enterpriseKnowledge.citation.mismatch')
    case 'RELEASE_NOT_FOUND':
    case 'MEMBER_NOT_FOUND':
    case 'EVIDENCE_NOT_FOUND':
    case 'SOURCE_NOT_FOUND':
      return t('enterpriseKnowledge.citation.notFound')
    case 'EVIDENCE_UNSUPPORTED':
      return t('enterpriseKnowledge.citation.unsupported')
    default:
      return t('enterpriseKnowledge.citation.failed')
  }
}

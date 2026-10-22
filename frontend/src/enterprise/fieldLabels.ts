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

// Why an expert edit was refused (S9b Spec §2.3). A stale edit offers the latest version.
export function expertEditFailure(t: Translate, code: string, status?: number): { text: string; reload: boolean } {
  switch (code) {
    case 'EXPERT_EDIT_STALE':
    case 'MEMBER_NOT_FOUND':
    case 'RELEASE_CONFLICT':
    case 'NEEDS_REBASE':
      return { text: t('enterpriseKnowledge.expert.stale'), reload: true }
    case 'EXPERT_EDIT_INVALID':
      return { text: t('enterpriseKnowledge.expert.invalid'), reload: false }
    case 'RELEASE_ACCESS_DENIED':
      return { text: t('enterpriseKnowledge.expert.denied'), reload: false }
    case 'SERVICE_UNAVAILABLE':
      return { text: t('enterpriseKnowledge.expert.unavailable'), reload: false }
  }
  if (status === 403) return { text: t('enterpriseKnowledge.expert.denied'), reload: false }
  if (status === 503) return { text: t('enterpriseKnowledge.expert.unavailable'), reload: false }
  return { text: t('enterpriseKnowledge.expert.failed'), reload: false }
}

export function expertRoleLabel(t: Translate, role: string): string {
  switch (role) {
    case 'owner':
      return t('enterpriseKnowledge.expert.roleOwner')
    case 'admin':
      return t('enterpriseKnowledge.expert.roleAdmin')
    default:
      return role
  }
}

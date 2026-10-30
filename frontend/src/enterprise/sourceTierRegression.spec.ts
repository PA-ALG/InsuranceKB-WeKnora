import { describe, expect, it } from 'vitest'
import { createI18n } from 'vue-i18n'
import zhCN from '@/enterprise/i18n/locales/zh-CN'
import enUS from '@/enterprise/i18n/locales/en-US'
import jaJP from '@/enterprise/i18n/locales/ja-JP'
import koKR from '@/enterprise/i18n/locales/ko-KR'
import ruRU from '@/enterprise/i18n/locales/ru-RU'
import { sourceTier, sourceTierLabel, sourceTierForChunk, referenceSourceKey } from './sourceTier'

describe('source provenance boundaries', () => {
  it.each([null, undefined, false, 'raw_text', [], { source_tier: 'release' },
    { metadata: 'release' }, { metadata: [] }, { metadata: { source_tier: ['release'] } },
    { metadata: { source_tier: 'Release' } }, { metadata: { source_tier: 'raw_text ' } },
  ])('does not infer a source tier from malformed or model supplied values: %j', reference => {
    expect(sourceTier(reference)).toBeNull()
  })

  it('does not label an ambiguous chunk from different versions or source tiers', () => {
    const raw = { id: 'shared', metadata: { source_tier: 'raw_text', release_id: 'r1' } }
    expect(sourceTierForChunk('shared', [raw, { ...raw, metadata: { source_tier: 'release', release_id: 'r1' } }])).toBeNull()
    expect(sourceTierForChunk('shared', [raw, { ...raw, metadata: { source_tier: 'raw_text', release_id: 'r2' } }])).toBeNull()
    expect(sourceTierForChunk('shared', [raw, { id: 'shared' }])).toBeNull()
    expect(sourceTierForChunk('shared', [raw, { ...raw }])).toBe('raw_text')
    expect(sourceTierForChunk('second', [{ ...raw, chunk_ids: ['first', 'second'] }])).toBe('raw_text')
    expect(sourceTierForChunk('shared', [{ ...raw, chunk_type: 'web_search' }])).toBeNull()
  })

  it('keeps unrecognized future source metadata separate without displaying it as reviewed', () => {
    const reference = { metadata: { source_tier: 'future', release_id: 'r1' } }
    expect(sourceTier(reference)).toBeNull()
    expect(referenceSourceKey(reference)).not.toBe(referenceSourceKey({}))
    expect(referenceSourceKey(reference)).not.toBe(referenceSourceKey({ metadata: { source_tier: 'raw_text', release_id: 'r1' } }))
    expect(sourceTierLabel(null, key => key)).toBe('')
  })

  it.each(Object.entries({ 'zh-CN': zhCN, 'en-US': enUS, 'ja-JP': jaJP, 'ko-KR': koKR, 'ru-RU': ruRU }))(
    '%s provides distinct translated labels for both source tiers', (locale, messages) => {
      const { t } = createI18n({ legacy: false, locale, messages: { [locale]: messages } }).global
      const raw = sourceTierLabel('raw_text', t)
      const published = sourceTierLabel('release', t)
      expect(raw).toBeTruthy(); expect(published).toBeTruthy()
      expect(raw).not.toBe(published)
      expect(raw).not.toContain('chat.sourceTier'); expect(published).not.toContain('chat.sourceTier')
    },
  )
})

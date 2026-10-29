// Q1a acceptance (protected, written by Claude): every chat reference from an enterprise Space says
// which kind of source it is (Spec docs/design/slices/Q1-问答接入发布版本.md §2.3).
import { describe, expect, it } from 'vitest'
import { createI18n } from 'vue-i18n'
import zhCN from '@/enterprise/i18n/locales/zh-CN'
import { sourceTier, sourceTierLabel } from './sourceTier'

const { t } = createI18n({ legacy: false, locale: 'zh-CN', messages: { 'zh-CN': zhCN } }).global

describe('chat source tier', () => {
  it('reads the tier written by the platform into the reference metadata', () => {
    expect(sourceTier({ metadata: { source_tier: 'raw_text', release_id: 'rel-1' } })).toBe('raw_text')
    expect(sourceTier({ metadata: { source_tier: 'release' } })).toBe('release')
  })

  it('has no tier for ordinary references or unknown values', () => {
    expect(sourceTier({})).toBeNull()
    expect(sourceTier({ metadata: null })).toBeNull()
    expect(sourceTier({ metadata: { source_tier: 'something_else' } })).toBeNull()
  })

  it('labels the two tiers distinctly', () => {
    expect(sourceTierLabel('raw_text', t)).toBe('原文检索（未经编译审核）')
    expect(sourceTierLabel('release', t)).toBe('已发布知识（审核过）')
  })
})

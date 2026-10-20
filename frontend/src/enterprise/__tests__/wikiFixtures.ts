// S6d acceptance fixtures (protected, written by Claude): the S3e release plus wiki_page members.
// M1 has two concept pages and one entity page; C1 has none; one M1 page is not Space-visible and
// one page belongs to another product. Synthetic data only.
import type { Release, ReleaseMember } from '../enterpriseApi'
import { member, release } from './s3eFixtures'

function evidence(page: number, quote: string) {
  return {
    source_ref: 'source:v1:k1:1:' + 'a'.repeat(64), file_sha256: 'a'.repeat(64),
    locator: { kind: 'PDF_TEXT_SPAN', page, start: 0, end: quote.length }, quote, access_scope: 'space',
  }
}

export function wikiPage(entityId: string, key: string, title: string, extra: Record<string, unknown> = {}): ReleaseMember {
  const [pageType] = key.split('/')
  return member('wiki_page', `wiki/${entityId}/${key}`, {
    page_key: key, entity_refs: [entityId], title, page_type: pageType, summary: `${title}的说明。`,
    content: `${title}正文。`, aliases: [], evidence: [], origin: 'MODEL_GENERATED',
    generator: 'weknora-native-wiki', model: 'deepseek-v4-flash', ...extra,
  })
}

export function wikiRelease(): Release {
  const data = release()
  const hidden = { ...wikiPage('M1', 'concept/hidden', '隐藏页'), access_scope: 'internal' }
  data.members.push(
    wikiPage('M1', 'entity/jia-yi-liao', '甲医疗'),
    wikiPage('M1', 'concept/kuan-xian-qi', '宽限期'),
    wikiPage('M1', 'concept/deng-dai-qi', '等待期', {
      content: '# 等待期\n\n等待期见 [[wiki/M1/concept/kuan-xian-qi|宽限期规则]]，另见 [[concept/elsewhere|别处]]。\n\n<script>window.hacked = true</script><img src="x" onerror="window.hacked = true">',
      evidence: [evidence(3, '等待期为90日。'), evidence(5, '意外无等待期。')],
    }),
    hidden,
    wikiPage('M2', 'concept/qi-ta', '其他产品的页'),
  )
  return data
}

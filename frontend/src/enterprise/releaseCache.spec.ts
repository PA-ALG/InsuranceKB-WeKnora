// S3i acceptance (protected, written by Claude; rewritten 2026-10-20 per Spec §2.1 revision): every
// release read still reaches the server, so authorization is checked each time; only identical reads
// in flight together share one request, and the release stays out of deep reactivity
// (Spec docs/design/slices/S3i-企业知识读取性能.md §2.1).
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { isReactive, ref } from 'vue'

vi.mock('@/utils/request', () => ({ get: vi.fn(), post: vi.fn() }))

type Api = typeof import('./enterpriseApi')
let api: Api
let get: ReturnType<typeof vi.fn>

const release = (id: string) => ({ id, epoch: 9, members: [{ kind: 'entity', logical_slug: 'entity/M1', payload: { names: ['甲'] } }] })
const ok = (data: unknown) => Promise.resolve({ success: true, data })

beforeEach(async () => {
  vi.resetModules()
  get = vi.mocked((await import('@/utils/request')).get) as unknown as ReturnType<typeof vi.fn>
  get.mockReset()
  api = await import('./enterpriseApi')
})

const urls = () => get.mock.calls.map(call => String(call[0]))

describe('release reads', () => {
  it('shares one request between identical reads in flight together', async () => {
    get.mockImplementation((url: string) => ok(release(decodeURIComponent(url.split('/').at(-1)!))))
    const [a, b] = await Promise.all([api.readRelease('demo', 'rel-9'), api.readRelease('demo', 'rel-9')])
    const [c, d] = await Promise.all([api.readRelease('demo'), api.readRelease('demo')])
    expect(urls()).toEqual([
      '/api/v1/enterprise/spaces/demo/view/releases/rel-9',
      '/api/v1/enterprise/spaces/demo/view/releases/active',
    ])
    expect([a.id, b.id, c.id, d.id]).toEqual(['rel-9', 'rel-9', 'active', 'active'])
  })

  it('asks the server again for every later read, so access is checked each time', async () => {
    get.mockImplementation(() => ok(release('rel-9')))
    await api.readRelease('demo', 'rel-9')
    await api.readRelease('demo', 'rel-9')
    await api.readRelease('demo')
    await api.readRelease('demo', 'rel-9')
    expect(urls()).toEqual([
      '/api/v1/enterprise/spaces/demo/view/releases/rel-9',
      '/api/v1/enterprise/spaces/demo/view/releases/rel-9',
      '/api/v1/enterprise/spaces/demo/view/releases/active',
      '/api/v1/enterprise/spaces/demo/view/releases/rel-9',
    ])
  })

  it('does not share a failure with later reads, nor reads across Spaces', async () => {
    get.mockImplementationOnce(() => Promise.resolve({ success: false, code: 'RELEASE_ACCESS_DENIED' }))
      .mockImplementation(() => ok(release('rel-9')))
    await expect(api.readRelease('demo', 'rel-9')).rejects.toBeTruthy()
    await Promise.all([api.readRelease('demo', 'rel-9'), api.readRelease('other', 'rel-9')])
    expect(urls()).toEqual([
      '/api/v1/enterprise/spaces/demo/view/releases/rel-9',
      '/api/v1/enterprise/spaces/demo/view/releases/rel-9',
      '/api/v1/enterprise/spaces/other/view/releases/rel-9',
    ])
  })

  it('keeps the release out of deep reactivity', async () => {
    get.mockImplementation(() => ok(release('rel-9')))
    const holder = ref(await api.readRelease('demo', 'rel-9'))
    expect(isReactive(holder.value)).toBe(false)
  })
})

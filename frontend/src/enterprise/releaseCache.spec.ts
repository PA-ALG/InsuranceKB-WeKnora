// S3i acceptance (protected, written by Claude): a release is immutable by ID, so the browser reads each
// pinned release once, shares concurrent reads, keeps it out of deep reactivity and bounds what it
// holds (Spec docs/design/slices/S3i-企业知识读取性能.md §2.1).
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

describe('release cache', () => {
  it('reads a pinned release once and shares concurrent reads', async () => {
    get.mockImplementation((url: string) => ok(release(decodeURIComponent(url.split('/').at(-1)!))))
    const [a, b] = await Promise.all([api.readRelease('demo', 'rel-9'), api.readRelease('demo', 'rel-9')])
    const c = await api.readRelease('demo', 'rel-9')
    expect(urls()).toEqual(['/api/v1/enterprise/spaces/demo/view/releases/rel-9'])
    expect([a.id, b.id, c.id]).toEqual(['rel-9', 'rel-9', 'rel-9'])
  })

  it('keeps the release out of deep reactivity', async () => {
    get.mockImplementation(() => ok(release('rel-9')))
    const holder = ref(await api.readRelease('demo', 'rel-9'))
    expect(isReactive(holder.value)).toBe(false)
  })

  it('always asks for Active, then serves the ID it resolved to from the cache', async () => {
    get.mockImplementation(() => ok(release('rel-9')))
    await api.readRelease('demo')
    await api.readRelease('demo')
    await api.readRelease('demo', 'rel-9')
    expect(urls()).toEqual([
      '/api/v1/enterprise/spaces/demo/view/releases/active',
      '/api/v1/enterprise/spaces/demo/view/releases/active',
    ])
  })

  it('does not cache failures and does not share across Spaces', async () => {
    get.mockImplementationOnce(() => Promise.resolve({ success: false, code: 'SERVICE_UNAVAILABLE' }))
      .mockImplementation(() => ok(release('rel-9')))
    await expect(api.readRelease('demo', 'rel-9')).rejects.toBeTruthy()
    await api.readRelease('demo', 'rel-9')
    await api.readRelease('other', 'rel-9')
    expect(urls()).toEqual([
      '/api/v1/enterprise/spaces/demo/view/releases/rel-9',
      '/api/v1/enterprise/spaces/demo/view/releases/rel-9',
      '/api/v1/enterprise/spaces/other/view/releases/rel-9',
    ])
  })

  it('holds at most four releases, dropping the least recently read', async () => {
    get.mockImplementation((url: string) => ok(release(decodeURIComponent(url.split('/').at(-1)!))))
    for (const id of ['r1', 'r2', 'r3', 'r4']) await api.readRelease('demo', id)
    await api.readRelease('demo', 'r1') // r1 is now the most recent; r2 the least
    await api.readRelease('demo', 'r5')
    await api.readRelease('demo', 'r1')
    await api.readRelease('demo', 'r2')
    expect(urls().map(url => url.split('/').at(-1))).toEqual(['r1', 'r2', 'r3', 'r4', 'r5', 'r2'])
  })
})

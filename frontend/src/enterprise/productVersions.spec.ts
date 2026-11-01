// PV-4b acceptance (protected, written by Claude): the browser derives a version's sale status with
// the platform's rule — the same vector file both test — and reads family and supersedes links
// from the release only (Spec docs/design/slices/PV-4b-读取侧.md §1, §3).
import { readFileSync } from 'node:fs'
import { describe, expect, it } from 'vitest'
import { entitySummaries } from './releaseView'
import {
  businessDay, discontinuedCount, familyClusters, saleStatus, versionInfo, visibleEntries, type Lifecycle,
} from './productVersions'
import { VERSION_NOW, versionRelease } from './__tests__/versionFixtures'

interface Vectors {
  status: { name: string; lifecycle: Lifecycle | null; day: string; status: string }[]
  business_day: { instant: string; day: string }[]
}
const vectors: Vectors = JSON.parse(readFileSync(
  new URL('../../../internal/enterprise/knowledge/testdata/sale_status_vectors.json', import.meta.url), 'utf8'))

const DAY = businessDay(VERSION_NOW)
const nursing = () => entitySummaries(versionRelease()).filter(entry => entry.labels.includes('nursing'))
const ids = (entries: { entityId: string }[]) => entries.map(entry => entry.entityId)

describe('sale status', () => {
  it('matches every shared vector', () => {
    expect(vectors.status.length).toBeGreaterThan(0)
    for (const vector of vectors.status) expect(saleStatus(vector.lifecycle, vector.day), vector.name).toBe(vector.status)
  })

  it('takes the business day of an instant at UTC+8', () => {
    for (const vector of vectors.business_day) expect(businessDay(new Date(vector.instant)), vector.instant).toBe(vector.day)
    expect(DAY).toBe('2026-11-01')
  })
})

describe('version info', () => {
  it('reads status, family and supersedes links of the release, ignoring ends it lacks', () => {
    const release = versionRelease()
    expect(versionInfo(release, 'V2', DAY)).toMatchObject({
      status: 'on_sale', family: { key: '甲护理', title: '甲护理系列' },
      predecessors: [{ entityId: 'V1', name: '甲护理保险' }], successors: [],
    })
    expect(versionInfo(release, 'V1', DAY)).toMatchObject({
      status: 'discontinued', predecessors: [], successors: [{ entityId: 'V2', name: '甲护理保险' }],
    })
    expect(versionInfo(release, 'V2', DAY).lifecycle).toEqual({ sale_start: '2024-04-23', source_status: 'on_sale', basis_date: '2026-10-20' })
  })

  it('has no status, family or links for an entity without version data', () => {
    expect(versionInfo(versionRelease(), 'U1', DAY)).toEqual({ lifecycle: null, status: null, family: null, predecessors: [], successors: [] })
  })
})

describe('navigation entries', () => {
  it('clusters a family of two or more entries, newest sale start first', () => {
    const release = versionRelease()
    const clusters = familyClusters(release, nursing())
    expect(clusters).toHaveLength(1)
    expect(clusters[0].family).toEqual({ key: '甲护理', title: '甲护理系列' })
    expect(ids(clusters[0].entries)).toEqual(['B1', 'V2', 'V1'])
    const medical = entitySummaries(release).filter(entry => entry.labels.includes('medical'))
    expect(familyClusters(release, medical)).toEqual([{ family: null, entries: medical }])
  })

  it('leaves a family of one entry unclustered', () => {
    const release = versionRelease()
    const single = nursing().filter(entry => entry.entityId === 'V2')
    expect(familyClusters(release, single)).toEqual([{ family: null, entries: single }])
  })

  it('hides discontinued entries unless included, but never the current one', () => {
    const release = versionRelease()
    expect(ids(visibleEntries(release, nursing(), DAY, { includeDiscontinued: false }))).toEqual(['V2', 'B1'])
    expect(ids(visibleEntries(release, nursing(), DAY, { includeDiscontinued: true }))).toEqual(['V1', 'V2', 'B1'])
    expect(ids(visibleEntries(release, nursing(), DAY, { includeDiscontinued: false, keep: 'V1' }))).toEqual(['V1', 'V2', 'B1'])
    expect(discontinuedCount(release, entitySummaries(release), DAY)).toBe(1)
  })
})

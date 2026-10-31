// S11e (Spec §3.2a, review round 2): the ZIP directory is checked on the raw bytes, before JSZip
// resolves, merges or drops anything. Fixtures are structural only: stored entries with plain text.
import JSZip from 'jszip'
import { describe, expect, it } from 'vitest'
import { readZipDirectory, ZipDirectoryRejected } from './officeZipDirectory'

interface Raw { name: string | Uint8Array; data?: string; flags?: number; method?: number; extra?: number[]; attributes?: number }
interface End { disk: number; directoryDisk: number; diskEntries: number; total: number; trailing: number[] }

/** A stored-only ZIP written byte by byte, so names and records can be what JSZip would never write. */
function rawZip(records: Raw[], end: Partial<End> = {}): ArrayBuffer {
  const out: number[] = []
  const u16 = (v: number) => out.push(v & 0xff, (v >>> 8) & 0xff)
  const u32 = (v: number) => out.push(v & 0xff, (v >>> 8) & 0xff, (v >>> 16) & 0xff, (v >>> 24) & 0xff)
  const encoded = records.map(r => ({
    ...r, nameBytes: typeof r.name === 'string' ? [...new TextEncoder().encode(r.name)] : [...r.name],
    dataBytes: [...new TextEncoder().encode(r.data ?? '')], offset: 0,
  }))
  for (const r of encoded) {
    r.offset = out.length
    u32(0x04034b50); u16(20); u16(r.flags ?? 0x0800); u16(r.method ?? 0); u16(0); u16(0); u32(0)
    u32(r.dataBytes.length); u32(r.dataBytes.length); u16(r.nameBytes.length); u16(0)
    out.push(...r.nameBytes, ...r.dataBytes)
  }
  const directoryStart = out.length
  for (const r of encoded) {
    const extra = r.extra ?? []
    u32(0x02014b50); u16(20); u16(20); u16(r.flags ?? 0x0800); u16(r.method ?? 0); u16(0); u16(0); u32(0)
    u32(r.dataBytes.length); u32(r.dataBytes.length); u16(r.nameBytes.length); u16(extra.length); u16(0)
    u16(0); u16(0); u32(r.attributes ?? 0); u32(r.offset)
    out.push(...r.nameBytes, ...extra)
  }
  const directorySize = out.length - directoryStart
  u32(0x06054b50); u16(end.disk ?? 0); u16(end.directoryDisk ?? 0)
  u16(end.diskEntries ?? end.total ?? records.length); u16(end.total ?? records.length)
  u32(directorySize); u32(directoryStart); u16(0)
  out.push(...(end.trailing ?? []))
  return new Uint8Array(out).buffer
}

function problem(data: ArrayBuffer, maxEntries = 100): string {
  try {
    readZipDirectory(data, maxEntries)
  } catch (error) {
    expect(error).toBeInstanceOf(ZipDirectoryRejected)
    return (error as ZipDirectoryRejected).problem
  }
  return 'accepted'
}

const FILES: Raw[] = [{ name: '[Content_Types].xml', data: '<Types/>' }, { name: 'word/' }, { name: 'word/document.xml', data: '<w/>' }]

describe('the raw ZIP directory', () => {
  it('lists every record, folders included', () => {
    expect(readZipDirectory(rawZip(FILES), 100)).toEqual([
      { name: '[Content_Types].xml', directory: false, size: 8 },
      { name: 'word/', directory: true, size: 0 },
      { name: 'word/document.xml', directory: false, size: 4 },
    ])
  })

  it('reads what JSZip writes', async () => {
    const zip = new JSZip()
    zip.file('word/document.xml', '<w/>')
    const entries = readZipDirectory(await zip.generateAsync({ type: 'arraybuffer' }), 100)
    expect(entries.map(e => e.name)).toEqual(['word/', 'word/document.xml'])
  })

  it('counts folders toward the entry limit', () => {
    expect(problem(rawZip(FILES), 3)).toBe('accepted')
    expect(problem(rawZip(FILES), 2)).toBe('size')
  })

  it.each([
    ['a raw duplicate', ['a.xml', 'a.xml']],
    ['names that collide once resolved', ['a/b.xml', 'a/./b.xml']],
    ['names that collide through a parent segment', ['b.xml', 'a/../b.xml']],
    ['names that differ only in case', ['A.xml', 'a.xml']],
  ])('refuses %s', (_name, names) => {
    expect(problem(rawZip(names.map(name => ({ name, data: 'x' }))))).toBe('structure')
  })

  it.each([
    ['an absolute name', '/a.xml'],
    ['a parent segment', '../a.xml'],
    ['a current segment', './a.xml'],
    ['an empty segment', 'a//b.xml'],
    ['a backslash', 'a\\b.xml'],
    ['a NUL', 'a\u0000b.xml'],
    ['another control character', 'a\u0007b.xml'],
  ])('refuses %s', (_name, name) => {
    expect(problem(rawZip([{ name, data: 'x' }]))).toBe('structure')
  })

  it('refuses names that are not UTF-8, which JSZip would decode differently', () => {
    expect(problem(rawZip([{ name: new Uint8Array([0x61, 0xff, 0x2e, 0x78]), data: 'x' }]))).toBe('structure')
  })

  it('refuses a Unicode path field, which JSZip would read instead of the name', () => {
    expect(problem(rawZip([{ name: 'a.xml', flags: 0, extra: [0x75, 0x70, 0, 0], data: 'x' }]))).toBe('structure')
  })

  it('refuses a file name carrying the folder attribute, and a folder with content', () => {
    expect(problem(rawZip([{ name: 'a.xml', attributes: 0x10, data: 'x' }]))).toBe('structure')
    expect(problem(rawZip([{ name: 'a/', data: 'x' }]))).toBe('structure')
  })

  it.each([
    ['more records than the end record declares', { total: 2 }],
    ['fewer records than the end record declares', { total: 4 }],
    ['ZIP64 counts', { total: 0xffff }],
    ['another disk', { disk: 1 }],
    ['a directory on another disk', { directoryDisk: 1 }],
    ['entries split across disks', { diskEntries: 2 }],
    ['bytes after the end record', { trailing: [0] }],
  ])('refuses %s', (_name, end) => {
    expect(problem(rawZip(FILES, end))).toBe('package')
  })

  it.each([
    ['an encrypted entry', { flags: 0x0801 }],
    ['strong encryption', { flags: 0x0840 }],
    ['an unsupported compression method', { method: 12 }],
    ['a ZIP64 field', { extra: [0x01, 0x00, 0, 0] }],
  ])('refuses %s', (_name, record) => {
    expect(problem(rawZip([{ name: 'a.xml', data: 'x', ...record }]))).toBe('package')
  })

  it('refuses bytes without an end record', () => {
    expect(problem(new TextEncoder().encode('not a zip').buffer as ArrayBuffer)).toBe('package')
    expect(problem(new ArrayBuffer(0))).toBe('package')
  })
})

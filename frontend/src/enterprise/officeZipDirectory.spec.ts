// S11e (Spec §3.2a, review round 2): the ZIP directory is checked on the raw bytes, before JSZip
// resolves, merges or drops anything. Fixtures are structural only: stored entries with plain text.
import JSZip from 'jszip'
import { describe, expect, it } from 'vitest'
import { rawZip, type RawRecord as Raw } from './__tests__/rawZip'
import { readZipDirectory, ZipDirectoryRejected } from './officeZipDirectory'

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

  describe('local headers, where JSZip takes the names from', () => {
    it.each([
      ['a local name other than the central one', [{ name: 'a.xml', localName: 'b.xml', data: 'x' }]],
      ['a local name repeated under two central names', [{ name: 'a.xml', data: 'x' }, { name: 'b.xml', localName: 'a.xml', data: 'y' }]],
      ['a non-canonical local name', [{ name: 'a.xml', localName: '../a.xml', data: 'x' }]],
      ['local names that differ only in case', [{ name: 'A.xml', data: 'x' }, { name: 'b.xml', localName: 'a.xml', data: 'y' }]],
      ['a local name of another length', [{ name: 'a.xml', localName: 'a.xmll', data: 'x' }]],
      ['a UTF-8 flag only in the central directory', [{ name: 'a.xml', flags: 0x0800, localFlags: 0, data: 'x' }]],
    ])('refuses %s', (_name, records) => {
      expect(problem(rawZip(records as Raw[]))).toBe('structure')
    })

    it('refuses an entry whose data runs into the next local header', () => {
      expect(problem(rawZip([{ name: 'a.xml', data: 'x', compressedSize: 8 }, { name: 'b.xml', data: 'y' }]))).toBe('package')
    })

    it('refuses an entry whose data runs into the central directory', () => {
      expect(problem(rawZip([{ name: 'a.xml', data: 'x', compressedSize: 40 }]))).toBe('package')
    })

    it('refuses an encrypted local header', () => {
      expect(problem(rawZip([{ name: 'a.xml', localFlags: 0x0801, data: 'x' }]))).toBe('package')
    })
  })

  it('refuses bytes without an end record', () => {
    expect(problem(new TextEncoder().encode('not a zip').buffer as ArrayBuffer)).toBe('package')
    expect(problem(new ArrayBuffer(0))).toBe('package')
  })
})

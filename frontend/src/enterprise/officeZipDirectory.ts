// Reads a ZIP's own directory before any zip library touches it (S11e Spec §3.2a). JSZip resolves
// names, merges duplicates and builds objects for every entry while loading, so the raw entry
// count, raw names and the format features we do not support are checked here, on the bytes.
// JSZip 3.10.1 lists entries from the central directory but takes each name from the entry's local
// header (lib/zipEntry.js readLocalPart); both must therefore hold the same name, byte for byte.

export type ZipDirectoryProblem = 'package' | 'size' | 'structure'

export class ZipDirectoryRejected extends Error {
  constructor(readonly problem: ZipDirectoryProblem) {
    super(`ZIP directory rejected: ${problem}`)
    this.name = 'ZipDirectoryRejected'
  }
}

export interface ZipEntry {
  name: string
  directory: boolean
  /** Declared inflated size; only a pre-check, the inflated bytes are counted later. */
  size: number
}

const LOCAL_HEADER = 0x04034b50
const END_OF_DIRECTORY = 0x06054b50
const ZIP64_LOCATOR = 0x07064b50
const DIRECTORY_ENTRY = 0x02014b50
const UNSUPPORTED_FLAGS = 0x0001 | 0x0040 | 0x2000 // encrypted, strong encryption, encrypted directory
const UTF8_FLAG = 0x0800
const STORED = 0
const DEFLATED = 8
const ZIP64_EXTRA = 0x0001
const UNICODE_PATH_EXTRA = 0x7075 // JSZip would read this name instead of the entry's own
const DOS_DIRECTORY = 0x10
const utf8 = new TextDecoder('utf-8', { fatal: true })

function rejected(problem: ZipDirectoryProblem): ZipDirectoryRejected {
  return new ZipDirectoryRejected(problem)
}

/** JSZip's `utils.resolve` (jszip 3.10.1 lib/utils.js), applied to every name it loads. */
function resolveLikeJSZip(path: string): string {
  const parts = path.split('/')
  const result: string[] = []
  parts.forEach((part, index) => {
    if (part === '.' || (part === '' && index !== 0 && index !== parts.length - 1)) return
    if (part === '..') result.pop()
    else result.push(part)
  })
  return result.join('/')
}

/** A name a package may use: relative, `/`-separated, no empty, `.` or `..` segment, no control or `\`. */
function canonical(name: string, directory: boolean): boolean {
  if (!name || name.startsWith('/') || /[\\\u0000-\u001f\u007f]/.test(name)) return false
  const segments = (directory ? name.slice(0, -1) : name).split('/')
  return segments.every(segment => segment !== '' && segment !== '.' && segment !== '..')
}

export function readZipDirectory(data: ArrayBuffer, maxEntries: number): ZipEntry[] {
  const view = new DataView(data)
  const bytes = new Uint8Array(data)
  // The end record is the last 22 bytes plus a comment of at most 65535 bytes, and must end the file.
  let end = -1
  for (let at = data.byteLength - 22; at >= Math.max(0, data.byteLength - 22 - 0xffff); at--) {
    if (view.getUint32(at, true) === END_OF_DIRECTORY && at + 22 + view.getUint16(at + 20, true) === data.byteLength) {
      end = at
      break
    }
  }
  if (end < 0) throw rejected('package')
  const disk = view.getUint16(end + 4, true)
  const directoryDisk = view.getUint16(end + 6, true)
  const diskEntries = view.getUint16(end + 8, true)
  const total = view.getUint16(end + 10, true)
  const directorySize = view.getUint32(end + 12, true)
  const directoryStart = view.getUint32(end + 16, true)
  // Multi-disk and ZIP64 archives are not supported, whatever they would contain.
  if (disk !== 0 || directoryDisk !== 0 || diskEntries !== total) throw rejected('package')
  if (total === 0xffff || directorySize === 0xffffffff || directoryStart === 0xffffffff) throw rejected('package')
  if (end >= 20 && view.getUint32(end - 20, true) === ZIP64_LOCATOR) throw rejected('package')
  if (total > maxEntries) throw rejected('size')
  if (directoryStart + directorySize !== end) throw rejected('package')

  const entries: ZipEntry[] = []
  const seen = new Set<string>()
  const regions: [number, number][] = []
  let at = directoryStart
  while (at < end) {
    // More records than the end record declares: stop before reading them.
    if (entries.length >= total) throw rejected('package')
    if (at + 46 > end || view.getUint32(at, true) !== DIRECTORY_ENTRY) throw rejected('package')
    const flags = view.getUint16(at + 8, true)
    const method = view.getUint16(at + 10, true)
    const compressed = view.getUint32(at + 20, true)
    const size = view.getUint32(at + 24, true)
    const nameLength = view.getUint16(at + 28, true)
    const extraLength = view.getUint16(at + 30, true)
    const commentLength = view.getUint16(at + 32, true)
    const startDisk = view.getUint16(at + 34, true)
    const attributes = view.getUint32(at + 38, true)
    const localHeader = view.getUint32(at + 42, true)
    const next = at + 46 + nameLength + extraLength + commentLength
    if (next > end) throw rejected('package')
    if (flags & UNSUPPORTED_FLAGS || (method !== STORED && method !== DEFLATED) || startDisk !== 0) throw rejected('package')
    if (compressed === 0xffffffff || size === 0xffffffff || localHeader === 0xffffffff || localHeader >= directoryStart) {
      throw rejected('package')
    }
    for (let extra = at + 46 + nameLength; extra < at + 46 + nameLength + extraLength;) {
      if (extra + 4 > at + 46 + nameLength + extraLength) throw rejected('package')
      const id = view.getUint16(extra, true)
      if (id === ZIP64_EXTRA) throw rejected('package')
      if (id === UNICODE_PATH_EXTRA) throw rejected('structure')
      extra += 4 + view.getUint16(extra + 2, true)
    }
    // The local header JSZip reads the name from: inside the file, before the central directory,
    // with the same name bytes and the same UTF-8 flag; its data must end before the directory too.
    if (localHeader + 30 > directoryStart || view.getUint32(localHeader, true) !== LOCAL_HEADER) throw rejected('package')
    const localFlags = view.getUint16(localHeader + 6, true)
    const localNameLength = view.getUint16(localHeader + 26, true)
    const localData = localHeader + 30 + localNameLength + view.getUint16(localHeader + 28, true)
    if (localFlags & UNSUPPORTED_FLAGS || localData + compressed > directoryStart) throw rejected('package')
    const nameBytes = bytes.subarray(at + 46, at + 46 + nameLength)
    const localName = bytes.subarray(localHeader + 30, localHeader + 30 + localNameLength)
    if (localNameLength !== nameLength || localName.some((byte, i) => byte !== nameBytes[i])) throw rejected('structure')
    if ((localFlags ^ flags) & UTF8_FLAG) throw rejected('structure')
    regions.push([localHeader, localData + compressed])
    let name: string
    try {
      name = utf8.decode(localName)
    } catch {
      throw rejected('structure')
    }
    const directory = name.endsWith('/')
    // A DOS directory attribute on a file name would make JSZip load it as a folder.
    if ((attributes & DOS_DIRECTORY && !directory) || (directory && size > 0)) throw rejected('structure')
    // Names that collide once JSZip resolves them, or in any case, would let the renderer read an
    // entry other than the one checked.
    const key = resolveLikeJSZip(name).toLowerCase()
    if (seen.has(key)) throw rejected('structure')
    seen.add(key)
    if (!canonical(name, directory)) throw rejected('structure')
    entries.push({ name, directory, size })
    at = next
  }
  if (entries.length !== total) throw rejected('package')
  // Entries may not share or overlap their local headers and data.
  regions.sort((a, b) => a[0] - b[0])
  for (let i = 1; i < regions.length; i++) if (regions[i - 1][1] > regions[i][0]) throw rejected('package')
  return entries
}

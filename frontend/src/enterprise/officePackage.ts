import JSZip from 'jszip'
import type { OfficeFormat } from './officeCitation'

// An Office file is untrusted active content (S11e Spec §3.2a). The upstream renderers act on what a
// package holds: docx-preview writes an altChunk's HTML into an unsandboxed iframe, and external
// targets make the browser fetch them. Before a cited file reaches the preview, its package is
// rebuilt from an allow-list: only parts reachable from the package root through relationships
// we keep, canonical relationship and content-type parts, no altChunk elements. Anything we cannot
// read within the limits is refused, never shown as is.

export type OfficePackageProblem = 'package' | 'size' | 'structure'

export class OfficePackageRejected extends Error {
  constructor(readonly problem: OfficePackageProblem) {
    super(`Office package rejected: ${problem}`)
    this.name = 'OfficePackageRejected'
  }
}

export interface OfficePackageLimits {
  /** Downloaded bytes. */
  bytes: number
  /** Zip entries. */
  entries: number
  /** Bytes of all entries once inflated, counted while inflating (declared sizes can lie). */
  inflated: number
}

export const OFFICE_PACKAGE_LIMITS: OfficePackageLimits = {
  bytes: 128 * 1024 * 1024,
  entries: 10_000,
  inflated: 256 * 1024 * 1024,
}

const MAIN_TYPES: Record<OfficeFormat, string> = {
  docx: 'application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml',
  pptx: 'application/vnd.openxmlformats-officedocument.presentationml.presentation.main+xml',
  xlsx: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml',
}

// Relationship types (last path segment, lower case) that carry embedded documents, code or
// controls, or pull in other files. The relationship and the part it targets are dropped.
const DROPPED_RELATIONSHIPS = new Set([
  'afchunk', 'oleobject', 'control', 'activexcontrol', 'activexcontrolbinary',
  'vbaproject', 'vbaprojectsignature', 'vbaprojectsignatureagile', 'vbaprojectsignaturev3', 'wordvbadata',
  'keymapcustomizations', 'attachedtoolbars', 'extensibility', 'attachedtemplate', 'frame', 'subdocument',
  'externallink', 'externallinkpath', 'slideupdateinfo',
])

// Parts that are markup, code or OLE payloads, whatever relationship reaches them.
const DROPPED_CONTENT_TYPES = new Set([
  'text/html', 'application/xhtml+xml', 'message/rfc822', 'multipart/related', 'application/rtf', 'text/rtf',
  'application/vnd.ms-office.vbaproject', 'application/vnd.ms-office.vbaprojectsignature',
  'application/vnd.ms-word.vbadata+xml', 'application/vnd.ms-office.activex+xml', 'application/vnd.ms-office.activex',
  'application/vnd.openxmlformats-officedocument.oleobject', 'application/vnd.ms-word.keymapcustomizations+xml',
  'application/vnd.ms-word.attachedtoolbars',
])
const DROPPED_EXTENSIONS = new Set(['html', 'htm', 'xhtml', 'xht', 'mht', 'mhtml', 'rtf', 'bin', 'js', 'vbs', 'hta'])

const FOLLOWABLE = new Set(['http:', 'https:', 'mailto:'])
const RELATIONSHIPS_NS = 'http://schemas.openxmlformats.org/package/2006/relationships'
const CONTENT_TYPES_NS = 'http://schemas.openxmlformats.org/package/2006/content-types'
const CONTENT_TYPES = '[Content_Types].xml'

const ATTRIBUTE = /([\w:.-]+)\s*=\s*(?:"([^"]*)"|'([^']*)')/g
const ALT_CHUNK = /<(?:[\w.-]+:)?altChunk(?:\s+[\w:.-]+\s*=\s*(?:"[^"]*"|'[^']*'))*\s*(?:\/>|>[\s\S]*?<\/(?:[\w.-]+:)?altChunk\s*>)/g
const ALT_CHUNK_LEFT = /<(?:[\w.-]+:)?altChunk[\s/>]/

interface Relationship { id: string; type: string; target: string; external: boolean }

function rejected(problem: OfficePackageProblem): OfficePackageRejected {
  return new OfficePackageRejected(problem)
}

function decodeEntities(value: string): string {
  return value.replace(/&(#x[0-9a-f]+|#[0-9]+|amp|lt|gt|quot|apos);/gi, (raw, entity: string) => {
    const named: Record<string, string> = { amp: '&', lt: '<', gt: '>', quot: '"', apos: "'" }
    if (!entity.startsWith('#')) return named[entity.toLowerCase()] ?? raw
    const point = entity[1].toLowerCase() === 'x' ? parseInt(entity.slice(2), 16) : parseInt(entity.slice(1), 10)
    return Number.isInteger(point) && point > 0 && point <= 0x10ffff ? String.fromCodePoint(point) : raw
  })
}

function escapeAttribute(value: string): string {
  return value.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;')
}

/** Attributes of every element with the given local name, any prefix. */
function elements(xml: string, name: string): Record<string, string>[] {
  const found: Record<string, string>[] = []
  const pattern = new RegExp(`<(?:[\\w.-]+:)?${name}((?:\\s+[\\w:.-]+\\s*=\\s*(?:"[^"]*"|'[^']*'))*)\\s*/?>`, 'g')
  for (const match of xml.matchAll(pattern)) {
    const attributes: Record<string, string> = {}
    for (const [, key, double, single] of match[1].matchAll(ATTRIBUTE)) attributes[key] = decodeEntities(double ?? single)
    found.push(attributes)
  }
  return found
}

function extension(name: string): string {
  const base = name.slice(name.lastIndexOf('/') + 1)
  const dot = base.lastIndexOf('.')
  return dot < 0 ? '' : base.slice(dot + 1).toLowerCase()
}

function relationshipsPart(source: string): string {
  const slash = source.lastIndexOf('/')
  return `${source.slice(0, slash + 1)}_rels/${source.slice(slash + 1)}.rels`
}

/** The part a relative or absolute target names, or null if it leaves the package. */
function resolve(source: string, target: string): string | null {
  try {
    const base = `https://package.invalid/${source.slice(0, source.lastIndexOf('/') + 1)}`
    const url = new URL(target, base)
    if (url.origin !== 'https://package.invalid') return null
    return decodeURIComponent(url.pathname).replace(/^\/+/, '') || null
  } catch {
    return null
  }
}

function followable(target: string): boolean {
  try {
    return FOLLOWABLE.has(new URL(target).protocol)
  } catch {
    return false
  }
}

type Stream = { on(event: string, callback: (...args: never[]) => void): Stream; pause(): Stream; resume(): Stream }

/** Inflates one entry, counting bytes, and stops as soon as `budget` is exceeded. */
function inflatedSize(file: JSZip.JSZipObject, budget: number): Promise<number> {
  return new Promise((resolve, reject) => {
    let size = 0
    // `internalStream` is public JSZip API (ZipObject#internalStream) missing from its typings.
    const stream = (file as unknown as { internalStream(type: 'uint8array'): Stream }).internalStream('uint8array')
    stream
      .on('data', (chunk: Uint8Array) => {
        size += chunk.length
        if (size > budget) {
          stream.pause()
          reject(rejected('size'))
        }
      })
      .on('error', () => reject(rejected('package')))
      .on('end', () => resolve(size))
      .resume()
  })
}

/**
 * Rebuilds an Office package so that only inert parts reach the renderer. Throws
 * `OfficePackageRejected` when the file is not a readable package of `format` within `limits`.
 */
export async function sanitizeOfficePackage(
  data: ArrayBuffer, format: OfficeFormat, limits: OfficePackageLimits = OFFICE_PACKAGE_LIMITS,
): Promise<ArrayBuffer> {
  if (data.byteLength > limits.bytes) throw rejected('size')
  let zip: JSZip
  try {
    zip = await JSZip.loadAsync(data)
  } catch {
    throw rejected('package')
  }
  const entries = Object.values(zip.files).filter(file => !file.dir)
  if (entries.length > limits.entries) throw rejected('size')
  const byName = new Map<string, JSZip.JSZipObject>()
  for (const file of entries) {
    const key = file.name.toLowerCase()
    // Two names differing only in case would let the renderer read a part we did not inspect.
    if (byName.has(key)) throw rejected('structure')
    byName.set(key, file)
  }
  let budget = limits.inflated
  for (const file of entries) budget -= await inflatedSize(file, budget)

  const part = (name: string) => zip.file(name) ?? byName.get(name.toLowerCase()) ?? null
  const text = async (file: JSZip.JSZipObject) => {
    try {
      return await file.async('string')
    } catch {
      throw rejected('package')
    }
  }

  const typesFile = part(CONTENT_TYPES)
  if (!typesFile) throw rejected('structure')
  const typesXml = await text(typesFile)
  const defaults = new Map(elements(typesXml, 'Default')
    .filter(d => d.Extension && d.ContentType).map(d => [d.Extension.toLowerCase(), d.ContentType]))
  const overrides = new Map(elements(typesXml, 'Override')
    .filter(o => o.PartName && o.ContentType).map(o => [o.PartName.replace(/^\/+/, '').toLowerCase(), o.ContentType]))
  const contentType = (name: string) => overrides.get(name.toLowerCase()) ?? defaults.get(extension(name)) ?? ''
  const inert = (name: string) =>
    !DROPPED_CONTENT_TYPES.has(contentType(name).toLowerCase()) && !DROPPED_EXTENSIONS.has(extension(name))

  // Walk relationships from the package root; whatever is not reached is not kept.
  const keep = new Set<string>([typesFile.name])
  const rewritten = new Map<string, string>()
  const queue = ['']
  let main: string | null = null
  while (queue.length) {
    const source = queue.shift()!
    const relsFile = part(source ? relationshipsPart(source) : '_rels/.rels')
    if (!relsFile) continue
    keep.add(relsFile.name)
    const kept: Relationship[] = []
    for (const rel of elements(await text(relsFile), 'Relationship')) {
      const relationship = {
        id: rel.Id ?? '', type: rel.Type ?? '', target: rel.Target ?? '', external: rel.TargetMode?.toLowerCase() === 'external',
      }
      const kind = relationship.type.slice(relationship.type.lastIndexOf('/') + 1).toLowerCase()
      if (!relationship.id || DROPPED_RELATIONSHIPS.has(kind)) continue
      if (relationship.external) {
        // External targets are fetched by the renderer (a leaked request) or embed another file;
        // only links the reader may follow stay.
        if (kind === 'hyperlink' && followable(relationship.target)) kept.push(relationship)
        continue
      }
      const name = resolve(source, relationship.target)
      if (!name) continue
      const file = part(name)
      if (file && !inert(file.name)) continue
      kept.push(relationship)
      if (!source && kind === 'officedocument') {
        if (main !== null || !file) throw rejected('structure')
        main = file.name
      }
      if (file && !keep.has(file.name)) {
        keep.add(file.name)
        queue.push(file.name)
      }
    }
    rewritten.set(relsFile.name, `<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Relationships xmlns="${RELATIONSHIPS_NS}">`
      + kept.map(rel => `<Relationship Id="${escapeAttribute(rel.id)}" Type="${escapeAttribute(rel.type)}" `
        + `Target="${escapeAttribute(rel.target)}"${rel.external ? ' TargetMode="External"' : ''}/>`).join('')
      + '</Relationships>')
  }
  if (!main || contentType(main).toLowerCase() !== MAIN_TYPES[format]) throw rejected('structure')

  // altChunk elements are body content, not blocks: upstream counts only paragraphs and tables,
  // so removing them leaves every cited block number unchanged.
  if (format === 'docx') {
    for (const name of keep) {
      if (extension(name) !== 'xml' || !contentType(name).includes('wordprocessingml')) continue
      const xml = rewritten.get(name) ?? await text(part(name)!)
      if (!xml.includes('altChunk')) continue
      const clean = xml.replace(ALT_CHUNK, '')
      if (ALT_CHUNK_LEFT.test(clean)) throw rejected('structure')
      rewritten.set(name, clean)
    }
  }

  rewritten.set(typesFile.name, `<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Types xmlns="${CONTENT_TYPES_NS}">`
    + [...defaults].filter(([, type]) => !DROPPED_CONTENT_TYPES.has(type.toLowerCase()))
      .map(([ext, type]) => `<Default Extension="${escapeAttribute(ext)}" ContentType="${escapeAttribute(type)}"/>`).join('')
    + [...keep].filter(name => overrides.has(name.toLowerCase()))
      .map(name => `<Override PartName="/${escapeAttribute(name)}" ContentType="${escapeAttribute(overrides.get(name.toLowerCase())!)}"/>`).join('')
    + '</Types>')

  // Only files: removing a folder entry would also remove the kept parts under it.
  for (const file of entries) if (!keep.has(file.name)) zip.remove(file.name)
  for (const [name, xml] of rewritten) zip.file(name, xml)
  // Unchanged deflated parts are copied without inflating them again.
  return zip.generateAsync({ type: 'arraybuffer', compression: 'DEFLATE' })
}

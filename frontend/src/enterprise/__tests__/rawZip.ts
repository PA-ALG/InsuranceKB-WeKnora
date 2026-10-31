// A stored-only ZIP written byte by byte, so names and records can be what a zip library would
// never write (S11e Spec §3.2a). Structural fixtures only: entries hold plain text.

export interface RawRecord {
  name: string | Uint8Array
  data?: string
  flags?: number
  method?: number
  extra?: number[]
  attributes?: number
  /** The local header's name when it differs from the central directory's. */
  localName?: string | Uint8Array
  /** The local header's flags when they differ. */
  localFlags?: number
  /** A declared compressed size (both headers) other than the data length. */
  compressedSize?: number
  /** The local header's signature when it is not a local header's. */
  localSignature?: number
  /** The local name length field when it differs from the name written after it. */
  localNameLength?: number
  /** The local extra length field; no extra bytes are written. */
  localExtraLength?: number
  /** Whether this record's own local header is written (default true). */
  writeLocal?: boolean
  /** The central record's local header offset, from the directory start and the written local offsets. */
  localOffset?: number | ((directoryStart: number, offsets: number[]) => number)
}

export interface RawEnd { disk: number; directoryDisk: number; diskEntries: number; total: number; trailing: number[] }

const bytesOf = (value: string | Uint8Array) => (typeof value === 'string' ? [...new TextEncoder().encode(value)] : [...value])

export function rawZip(records: RawRecord[], end: Partial<RawEnd> = {}): ArrayBuffer {
  const out: number[] = []
  const u16 = (v: number) => out.push(v & 0xff, (v >>> 8) & 0xff)
  const u32 = (v: number) => out.push(v & 0xff, (v >>> 8) & 0xff, (v >>> 16) & 0xff, (v >>> 24) & 0xff)
  const encoded = records.map(r => {
    const data = bytesOf(r.data ?? '')
    return {
      ...r, data, nameBytes: bytesOf(r.name), localNameBytes: bytesOf(r.localName ?? r.name),
      compressed: r.compressedSize ?? data.length, offset: 0,
    }
  })
  for (const r of encoded) {
    r.offset = out.length
    if (r.writeLocal === false) continue
    u32(r.localSignature ?? 0x04034b50); u16(20); u16(r.localFlags ?? r.flags ?? 0x0800); u16(r.method ?? 0); u16(0); u16(0); u32(0)
    u32(r.compressed); u32(r.data.length); u16(r.localNameLength ?? r.localNameBytes.length); u16(r.localExtraLength ?? 0)
    out.push(...r.localNameBytes, ...r.data)
  }
  const directoryStart = out.length
  const offsets = encoded.map(r => r.offset)
  for (const r of encoded) {
    if (typeof r.localOffset === 'function') r.offset = r.localOffset(directoryStart, offsets)
    else if (r.localOffset !== undefined) r.offset = r.localOffset
  }
  for (const r of encoded) {
    const extra = r.extra ?? []
    u32(0x02014b50); u16(20); u16(20); u16(r.flags ?? 0x0800); u16(r.method ?? 0); u16(0); u16(0); u32(0)
    u32(r.compressed); u32(r.data.length); u16(r.nameBytes.length); u16(extra.length); u16(0)
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

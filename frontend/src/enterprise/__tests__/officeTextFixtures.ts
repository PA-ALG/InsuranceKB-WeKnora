// Synthetic Office packages for the S11h tests (Spec docs/design/slices/S11h-Office渲染失败时的文本视图.md).
// Every byte is written here; no business document is read or embedded.
import JSZip from 'jszip'

const REL = 'http://schemas.openxmlformats.org/officeDocument/2006/relationships'
const PKG_REL = 'http://schemas.openxmlformats.org/package/2006/relationships'
const OOXML = 'application/vnd.openxmlformats-officedocument'
export const NS = {
  a: 'http://schemas.openxmlformats.org/drawingml/2006/main',
  p: 'http://schemas.openxmlformats.org/presentationml/2006/main',
  w: 'http://schemas.openxmlformats.org/wordprocessingml/2006/main',
  x: 'http://schemas.openxmlformats.org/spreadsheetml/2006/main',
}

type Rel = [id: string, type: string, target: string]

function relsXml(list: Rel[]): string {
  return `<?xml version="1.0" encoding="UTF-8"?><Relationships xmlns="${PKG_REL}">${list
    .map(([id, type, target]) => `<Relationship Id="${id}" Type="${REL}/${type}" Target="${target}"/>`).join('')}</Relationships>`
}

async function pack(parts: Record<string, string>, overrides: Record<string, string>): Promise<ArrayBuffer> {
  const zip = new JSZip()
  zip.file('[Content_Types].xml', '<?xml version="1.0" encoding="UTF-8"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
    + '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
    + '<Default Extension="xml" ContentType="application/xml"/>'
    + Object.entries(overrides).map(([part, type]) => `<Override PartName="/${part}" ContentType="${type}"/>`).join('')
    + '</Types>')
  for (const [name, xml] of Object.entries(parts)) zip.file(name, xml)
  return zip.generateAsync({ type: 'arraybuffer', compression: 'DEFLATE' })
}

/** One text paragraph per entry; runs split a paragraph, `\n` inside a run becomes a line break. */
export function paragraphs(texts: string[]): string {
  return texts.map(text => `<a:p>${text.split('\n').map((run, i) =>
    `${i ? '<a:br/>' : ''}<a:r><a:rPr lang="zh-CN"/><a:t>${run}</a:t></a:r>`).join('')}</a:p>`).join('')
}

export function textBox(id: number, texts: string[]): string {
  return `<p:sp><p:nvSpPr><p:cNvPr id="${id}" name="Text ${id}"/><p:cNvSpPr txBox="1"/><p:nvPr/></p:nvSpPr>`
    + '<p:spPr><a:xfrm><a:off x="0" y="0"/><a:ext cx="100" cy="100"/></a:xfrm></p:spPr>'
    + `<p:txBody><a:bodyPr/><a:lstStyle/>${paragraphs(texts)}</p:txBody></p:sp>`
}

/** A table drawn in a graphic frame; each row lists its cells' texts. */
export function tableFrame(id: number, rows: string[][]): string {
  return `<p:graphicFrame><p:nvGraphicFramePr><p:cNvPr id="${id}" name="Table ${id}"/><p:cNvGraphicFramePr/><p:nvPr/></p:nvGraphicFramePr>`
    + '<p:xfrm><a:off x="0" y="0"/><a:ext cx="100" cy="100"/></p:xfrm>'
    + '<a:graphic><a:graphicData uri="http://schemas.openxmlformats.org/drawingml/2006/table"><a:tbl><a:tblGrid><a:gridCol w="100"/></a:tblGrid>'
    + rows.map(cells => `<a:tr h="10">${cells.map(cell => `<a:tc><a:txBody><a:bodyPr/>${paragraphs([cell])}</a:txBody></a:tc>`).join('')}</a:tr>`).join('')
    + '</a:tbl></a:graphicData></a:graphic></p:graphicFrame>'
}

export function group(id: number, children: string): string {
  return `<p:grpSp><p:nvGrpSpPr><p:cNvPr id="${id}" name="Group ${id}"/><p:cNvGrpSpPr/><p:nvPr/></p:nvGrpSpPr>`
    + '<p:grpSpPr><a:xfrm><a:off x="0" y="0"/><a:ext cx="100" cy="100"/><a:chOff x="0" y="0"/><a:chExt cx="100" cy="100"/></a:xfrm></p:grpSpPr>'
    + `${children}</p:grpSp>`
}

export interface SlideSpec { shapes: string; notes?: string[] }

const spTree = (root: string, shapes: string) => `<?xml version="1.0" encoding="UTF-8"?><p:${root} xmlns:a="${NS.a}" xmlns:r="${REL}" xmlns:p="${NS.p}">`
  + `<p:cSld><p:spTree><p:nvGrpSpPr><p:cNvPr id="1" name=""/><p:cNvGrpSpPr/><p:nvPr/></p:nvGrpSpPr><p:grpSpPr/>${shapes}</p:spTree></p:cSld></p:${root}>`

/**
 * A deck whose presentation lists the slides in `order` (indexes into `slides`), so presentation
 * order can differ from part names; slide i is stored as `ppt/slides/slide{i+1}.xml`. With
 * `master`/`layout`, every slide uses one layout of one master holding those shapes.
 */
export async function deck(
  slides: SlideSpec[], { order = slides.map((_, i) => i), master, layout }: { order?: number[]; master?: string; layout?: string } = {},
): Promise<ArrayBuffer> {
  const PML = `${OOXML}.presentationml`
  const themed = master !== undefined || layout !== undefined
  const parts: Record<string, string> = {
    '_rels/.rels': relsXml([['rId1', 'officeDocument', 'ppt/presentation.xml']]),
    'ppt/presentation.xml': `<?xml version="1.0" encoding="UTF-8"?><p:presentation xmlns:a="${NS.a}" xmlns:r="${REL}" xmlns:p="${NS.p}">`
      + (themed ? '<p:sldMasterIdLst><p:sldMasterId id="2147483648" r:id="rIdM"/></p:sldMasterIdLst>' : '')
      + `<p:sldIdLst>${order.map((index, at) => `<p:sldId id="${256 + at}" r:id="rId${index + 10}"/>`).join('')}</p:sldIdLst>`
      + '<p:sldSz cx="9144000" cy="6858000"/></p:presentation>',
    'ppt/_rels/presentation.xml.rels': relsXml([
      ...slides.map((_, i) => [`rId${i + 10}`, 'slide', `slides/slide${i + 1}.xml`] as Rel),
      ...(themed ? [['rIdM', 'slideMaster', 'slideMasters/slideMaster1.xml'] as Rel] : []),
    ]),
  }
  const overrides: Record<string, string> = { 'ppt/presentation.xml': `${PML}.presentation.main+xml` }
  if (themed) {
    parts['ppt/slideMasters/slideMaster1.xml'] = spTree('sldMaster', master ?? '')
      .replace('</p:sldMaster>', '<p:sldLayoutIdLst><p:sldLayoutId id="2147483649" r:id="rIdL"/></p:sldLayoutIdLst></p:sldMaster>')
    parts['ppt/slideMasters/_rels/slideMaster1.xml.rels'] = relsXml([['rIdL', 'slideLayout', '../slideLayouts/slideLayout1.xml']])
    parts['ppt/slideLayouts/slideLayout1.xml'] = spTree('sldLayout', layout ?? '')
    parts['ppt/slideLayouts/_rels/slideLayout1.xml.rels'] = relsXml([['rIdM', 'slideMaster', '../slideMasters/slideMaster1.xml']])
    overrides['ppt/slideMasters/slideMaster1.xml'] = `${PML}.slideMaster+xml`
    overrides['ppt/slideLayouts/slideLayout1.xml'] = `${PML}.slideLayout+xml`
  }
  slides.forEach((slide, i) => {
    const name = `ppt/slides/slide${i + 1}.xml`
    parts[name] = spTree('sld', slide.shapes)
    overrides[name] = `${PML}.slide+xml`
    const related: Rel[] = themed ? [['rIdL', 'slideLayout', '../slideLayouts/slideLayout1.xml']] : []
    if (slide.notes) {
      const notes = `ppt/notesSlides/notesSlide${i + 1}.xml`
      parts[notes] = spTree('notes', textBox(2, slide.notes))
      related.push(['rIdN', 'notesSlide', `../notesSlides/notesSlide${i + 1}.xml`])
      overrides[notes] = `${PML}.notesSlide+xml`
    }
    if (related.length) parts[`ppt/slides/_rels/slide${i + 1}.xml.rels`] = relsXml(related)
  })
  return pack(parts, overrides)
}

/** A document whose body is the given WordprocessingML. */
export async function manual(body: string): Promise<ArrayBuffer> {
  return pack({
    '_rels/.rels': relsXml([['rId1', 'officeDocument', 'word/document.xml']]),
    'word/document.xml': `<?xml version="1.0" encoding="UTF-8"?><w:document xmlns:w="${NS.w}"><w:body>${body}<w:sectPr/></w:body></w:document>`,
  }, { 'word/document.xml': `${OOXML}.wordprocessingml.document.main+xml` })
}

export const wp = (text: string) => `<w:p><w:r><w:t xml:space="preserve">${text}</w:t></w:r></w:p>`
export const wtable = (rows: string[][]) => `<w:tbl>${rows.map(cells =>
  `<w:tr>${cells.map(cell => `<w:tc>${wp(cell)}</w:tc>`).join('')}</w:tr>`).join('')}</w:tbl>`

/**
 * A workbook; each sheet maps row numbers to cells. A string cell is stored as a shared string,
 * a number as a value, `{ inline }` as an inline string.
 */
export async function workbook(sheets: Record<string, Record<number, (string | number | { inline: string })[]>>): Promise<ArrayBuffer> {
  const SML = `${OOXML}.spreadsheetml`
  const shared: string[] = []
  const names = Object.keys(sheets)
  const parts: Record<string, string> = {
    '_rels/.rels': relsXml([['rId1', 'officeDocument', 'xl/workbook.xml']]),
    'xl/workbook.xml': `<?xml version="1.0" encoding="UTF-8"?><workbook xmlns="${NS.x}" xmlns:r="${REL}"><sheets>${
      names.map((name, i) => `<sheet name="${name}" sheetId="${i + 1}" r:id="rId${i + 1}"/>`).join('')}</sheets></workbook>`,
    'xl/_rels/workbook.xml.rels': relsXml([
      ...names.map((_, i) => [`rId${i + 1}`, 'worksheet', `worksheets/sheet${i + 1}.xml`] as Rel),
      ['rIdS', 'sharedStrings', 'sharedStrings.xml'],
    ]),
  }
  const overrides: Record<string, string> = {
    'xl/workbook.xml': `${SML}.sheet.main+xml`, 'xl/sharedStrings.xml': `${SML}.sharedStrings+xml`,
  }
  const column = (index: number) => String.fromCharCode(65 + index)
  names.forEach((name, i) => {
    const rows = Object.entries(sheets[name]).map(([row, cells]) => `<row r="${row}">${cells.map((cell, c) => {
      const ref = `${column(c)}${row}`
      if (typeof cell === 'number') return `<c r="${ref}"><v>${cell}</v></c>`
      if (typeof cell === 'object') return `<c r="${ref}" t="inlineStr"><is><t>${cell.inline}</t></is></c>`
      shared.push(cell)
      return `<c r="${ref}" t="s"><v>${shared.length - 1}</v></c>`
    }).join('')}</row>`).join('')
    parts[`xl/worksheets/sheet${i + 1}.xml`] = `<?xml version="1.0" encoding="UTF-8"?><worksheet xmlns="${NS.x}"><sheetData>${rows}</sheetData></worksheet>`
    overrides[`xl/worksheets/sheet${i + 1}.xml`] = `${SML}.worksheet+xml`
  })
  parts['xl/sharedStrings.xml'] = `<?xml version="1.0" encoding="UTF-8"?><sst xmlns="${NS.x}">${
    shared.map(text => `<si><t>${text}</t></si>`).join('')}</sst>`
  return pack(parts, overrides)
}

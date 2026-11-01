// S11h acceptance (protected, written by Claude): the PPTX rebuild drops graphic frames inside
// groups, which @vue-office/pptx 1.0.1 cannot render and on which it stops the whole deck, and
// keeps everything else; the text view reads the same default-deny rebuild without that removal
// (Spec docs/design/slices/S11h-Office渲染失败时的文本视图.md §2.1, §2.2).
import JSZip from 'jszip'
import { describe, expect, it } from 'vitest'
import { OfficePackageRejected, readOfficePackage, sanitizeOfficePackage } from './officePackage'
import { deck, group, NS, tableFrame, textBox } from './__tests__/officeTextFixtures'

const SLIDE = 'ppt/slides/slide1.xml'
const LAYOUT = 'ppt/slideLayouts/slideLayout1.xml'
const MASTER = 'ppt/slideMasters/slideMaster1.xml'

// A top-level text box and table, and a group holding a table, a text box and a nested group
// holding another table.
const SHAPES = textBox(2, ['顶层文字']) + tableFrame(3, [['顶层表格']])
  + group(4, tableFrame(5, [['组合表格']]) + textBox(6, ['组合文字']) + group(7, tableFrame(8, [['嵌套表格']])))

async function part(bytes: ArrayBuffer, name: string): Promise<string> {
  return (await JSZip.loadAsync(bytes)).file(name)!.async('string')
}

const count = (xml: string, name: string) => xml.match(new RegExp(`<(?:[\\w.-]+:)?${name}[\\s/>]`, 'g'))?.length ?? 0

describe('pptx rebuild for the renderer', () => {
  it.each([SLIDE, LAYOUT, MASTER])('removes graphic frames inside groups from %s and keeps the rest', async name => {
    const rebuilt = await sanitizeOfficePackage(await deck([{ shapes: SHAPES }], { master: SHAPES, layout: SHAPES }), 'pptx')
    const xml = await part(rebuilt, name)
    expect(count(xml, 'graphicFrame')).toBe(1)
    expect(count(xml, 'grpSp')).toBe(2)
    for (const kept of ['顶层文字', '顶层表格', '组合文字']) expect(xml).toContain(kept)
    for (const dropped of ['组合表格', '嵌套表格']) expect(xml).not.toContain(dropped)
  })

  it('removes them under any prefix, empty ones included', async () => {
    const prefixed = group(4, tableFrame(5, [['组合表格']]) + textBox(6, ['组合文字']))
      .replaceAll('<p:', '<x:').replaceAll('</p:', '</x:')
      .replace('<x:grpSp>', `<x:grpSp xmlns:x="${NS.p}">`)
    const empty = group(9, '<p:graphicFrame/>' + textBox(10, ['另一组文字']))
    const rebuilt = await sanitizeOfficePackage(await deck([{ shapes: prefixed + empty }]), 'pptx')
    const xml = await part(rebuilt, SLIDE)
    expect(count(xml, 'graphicFrame')).toBe(0)
    expect(xml).not.toContain('组合表格')
    expect(xml).toContain('组合文字')
    expect(xml).toContain('另一组文字')
  })

  it('leaves slides without grouped frames as they were', async () => {
    const original = await deck([{ shapes: textBox(2, ['顶层文字']) + tableFrame(3, [['顶层表格']]) + group(4, textBox(5, ['组合文字'])) }])
    const rebuilt = await sanitizeOfficePackage(original, 'pptx')
    expect(await part(rebuilt, SLIDE)).toBe(await part(original, SLIDE))
  })

  it('refuses a deck whose grouped frame is never closed', async () => {
    const broken = '<p:grpSp><p:nvGrpSpPr><p:cNvPr id="4" name="G"/><p:cNvGrpSpPr/><p:nvPr/></p:nvGrpSpPr><p:grpSpPr/>'
      + '<p:graphicFrame><p:nvGraphicFramePr><p:cNvPr id="5" name="T"/><p:cNvGraphicFramePr/><p:nvPr/></p:nvGraphicFramePr></p:grpSp>'
    const rebuilt = sanitizeOfficePackage(await deck([{ shapes: broken }]), 'pptx')
    await expect(rebuilt).rejects.toBeInstanceOf(OfficePackageRejected)
    await expect(rebuilt).rejects.toMatchObject({ problem: 'structure' })
  })
})

describe('reading the rebuilt package for the text view', () => {
  it('keeps grouped frames and follows speaker notes', async () => {
    const parts = await readOfficePackage(await deck([{ shapes: SHAPES, notes: ['备注文字'] }]), 'pptx')
    expect(parts.main).toBe('ppt/presentation.xml')
    const slide = parts.related(parts.main).find(rel => rel.type.endsWith('/slide'))!
    expect(slide.name).toBe(SLIDE)
    const xml = await parts.text(SLIDE)
    for (const kept of ['顶层表格', '组合表格', '嵌套表格', '组合文字']) expect(xml).toContain(kept)
    const notes = parts.related(SLIDE).find(rel => rel.type.endsWith('/notesSlide'))!
    expect(await parts.text(notes.name)).toContain('备注文字')
  })

  it('reads only what the rebuild kept', async () => {
    const zip = await JSZip.loadAsync(await deck([{ shapes: SHAPES }]))
    zip.file('ppt/orphan.xml', '<?xml version="1.0" encoding="UTF-8"?><orphan>未被引用的部件</orphan>')
    const parts = await readOfficePackage(await zip.generateAsync({ type: 'arraybuffer' }), 'pptx')
    expect(await parts.text('ppt/orphan.xml')).toBeNull()
    expect(await parts.text('ppt/slides/slide9.xml')).toBeNull()
    expect(parts.related('ppt/orphan.xml')).toEqual([])
  })

  it('refuses what the rebuild refuses', async () => {
    await expect(readOfficePackage(new Uint8Array([80, 75, 3, 4]).buffer, 'pptx')).rejects.toBeInstanceOf(OfficePackageRejected)
  })
})

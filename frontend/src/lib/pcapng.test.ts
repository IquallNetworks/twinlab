import { describe, expect, it } from 'vitest'

import { attachmentFilename, completePcapng, completePcapngLength } from './pcapng'

/** A block: type, total length, a body padded to 4 bytes, length again. */
function block(type: number, bodyLength: number, littleEndian = true): Uint8Array {
  const length = 12 + Math.ceil(bodyLength / 4) * 4
  const bytes = new Uint8Array(length)
  const view = new DataView(bytes.buffer)
  view.setUint32(0, type, littleEndian)
  view.setUint32(4, length, littleEndian)
  view.setUint32(length - 4, length, littleEndian)
  return bytes
}

/** A Section Header Block: its body starts with the byte-order magic. */
function sectionHeader(littleEndian = true): Uint8Array {
  const bytes = block(0x0a0d0d0a, 16, littleEndian)
  new DataView(bytes.buffer).setUint32(8, 0x1a2b3c4d, littleEndian)
  return bytes
}

function concat(...parts: Uint8Array[]): Uint8Array {
  const out = new Uint8Array(parts.reduce((sum, part) => sum + part.length, 0))
  let at = 0
  for (const part of parts) {
    out.set(part, at)
    at += part.length
  }
  return out
}

describe('completePcapngLength', () => {
  const shb = sectionHeader()
  const idb = block(1, 8)
  const epb = block(6, 70)

  it('keeps a section made of whole blocks', () => {
    const whole = concat(shb, idb, epb, epb)
    expect(completePcapngLength(whole)).toBe(whole.length)
  })

  it('cuts a block the stop interrupted', () => {
    const whole = concat(shb, idb, epb)
    const cut = concat(whole, epb.slice(0, 30))
    expect(completePcapngLength(cut)).toBe(whole.length)
  })

  it('reads big-endian sections by their magic', () => {
    const whole = concat(sectionHeader(false), block(1, 8, false), block(6, 40, false))
    expect(completePcapngLength(concat(whole, new Uint8Array(5)))).toBe(whole.length)
  })

  it('gives nothing for a partial header or bytes that are not pcapng', () => {
    expect(completePcapngLength(shb.slice(0, 20))).toBe(0)
    expect(completePcapngLength(new TextEncoder().encode('{"code":"oops"}'))).toBe(0)
  })

  it('joins chunks split anywhere before cutting', () => {
    const whole = concat(shb, idb, epb)
    const chunks = [whole.slice(0, 7), whole.slice(7, 41), whole.slice(41), epb.slice(0, 9)]
    expect(Array.from(completePcapng(chunks))).toEqual(Array.from(whole))
  })
})

describe('attachmentFilename', () => {
  it('reads the quoted name', () => {
    expect(attachmentFilename('attachment; filename="lab1-20261117T120000Z.pcapng"')).toBe(
      'lab1-20261117T120000Z.pcapng',
    )
  })

  it('is null without one', () => {
    expect(attachmentFilename(null)).toBeNull()
    expect(attachmentFilename('inline')).toBeNull()
  })
})

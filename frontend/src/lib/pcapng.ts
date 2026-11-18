/** Just enough pcapng to save a capture that was stopped early (delta 36).
 *
 * The server streams one pcapng section; stopping it mid-flight leaves the
 * bytes cut wherever the network split them, usually inside a block. Cutting
 * at the last COMPLETE block gives a file Wireshark reads without a
 * truncation warning. Every block starts with its type and total length
 * (4 bytes each) and repeats the length at its end; the Section Header
 * Block's byte-order magic says which endianness those lengths use. */

const SECTION_HEADER = 0x0a0d0d0a
const BYTE_ORDER_MAGIC = 0x1a2b3c4d

/** The length of the longest prefix of `bytes` made of whole blocks; 0 when
 * not even the Section Header Block arrived whole, or when `bytes` is not a
 * pcapng section at all. */
export function completePcapngLength(bytes: Uint8Array): number {
  if (bytes.length < 12) return 0
  const view = new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength)
  // The SHB's type reads the same in both byte orders; its magic does not.
  if (view.getUint32(0, true) !== SECTION_HEADER) return 0
  let littleEndian: boolean
  if (view.getUint32(8, true) === BYTE_ORDER_MAGIC) littleEndian = true
  else if (view.getUint32(8, false) === BYTE_ORDER_MAGIC) littleEndian = false
  else return 0

  let offset = 0
  while (offset + 8 <= bytes.length) {
    const length = view.getUint32(offset + 4, littleEndian)
    // A block is at least type + length + trailing length, 4-byte aligned; a
    // length that says otherwise means the bytes are not what we think.
    if (length < 12 || length % 4 !== 0) break
    if (offset + length > bytes.length) break
    offset += length
  }
  return offset
}

/** Join a capture's chunks, cut at the last complete block. */
export function completePcapng(chunks: Uint8Array[]): Uint8Array<ArrayBuffer> {
  const total = chunks.reduce((sum, chunk) => sum + chunk.length, 0)
  const joined = new Uint8Array(total)
  let at = 0
  for (const chunk of chunks) {
    joined.set(chunk, at)
    at += chunk.length
  }
  return joined.slice(0, completePcapngLength(joined))
}

/** The file name from a `Content-Disposition: attachment; filename="..."`
 * header, or null when it names none. */
export function attachmentFilename(header: string | null): string | null {
  if (header === null) return null
  const match = /filename="([^"]+)"/.exec(header)
  return match ? match[1] : null
}

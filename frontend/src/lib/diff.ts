// Minimal LCS line diff — enough to render "what changed since deploy"
// (delta 19) without a diff dependency. Definitions are tens of lines, so the
// O(n·m) table is nothing.

export interface DiffLine {
  kind: 'same' | 'added' | 'removed'
  text: string
}

/** Line-by-line diff from `before` to `after` (removed = only in before,
 * added = only in after). */
export function diffLines(before: string, after: string): DiffLine[] {
  const a = before.split('\n')
  const b = after.split('\n')
  const m = a.length
  const n = b.length

  // lcs[i][j] = LCS length of a[i:] and b[j:].
  const lcs: number[][] = Array.from({ length: m + 1 }, () => new Array<number>(n + 1).fill(0))
  for (let i = m - 1; i >= 0; i--) {
    const row = lcs[i]
    const next = lcs[i + 1]
    if (row === undefined || next === undefined) continue
    for (let j = n - 1; j >= 0; j--) {
      row[j] =
        a[i] === b[j]
          ? (next[j + 1] ?? 0) + 1
          : Math.max(next[j] ?? 0, row[j + 1] ?? 0)
    }
  }

  const out: DiffLine[] = []
  let i = 0
  let j = 0
  while (i < m && j < n) {
    const lineA = a[i]
    const lineB = b[j]
    if (lineA === undefined || lineB === undefined) break
    if (lineA === lineB) {
      out.push({ kind: 'same', text: lineA })
      i++
      j++
    } else if ((lcs[i + 1]?.[j] ?? 0) >= (lcs[i]?.[j + 1] ?? 0)) {
      out.push({ kind: 'removed', text: lineA })
      i++
    } else {
      out.push({ kind: 'added', text: lineB })
      j++
    }
  }
  for (; i < m; i++) out.push({ kind: 'removed', text: a[i] ?? '' })
  for (; j < n; j++) out.push({ kind: 'added', text: b[j] ?? '' })
  return out
}

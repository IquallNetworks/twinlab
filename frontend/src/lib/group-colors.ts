// Group canvas colors (contract delta 20). Explicit choices persist on the
// shared layout resource; a group without one gets a deterministic default —
// hashed from its NAME so every browser and user derives the same color
// without a write. Pure module.

export interface GroupStyle {
  color: string // "#rrggbb" (server-enforced on save)
}

export type GroupStyles = Record<string, GroupStyle>

// Eight hues picked to read on both Schematic themes (mid-lightness, spaced
// around the wheel; the first is the identity amber).
export const GROUP_PALETTE = [
  '#f59e0b', // amber
  '#38bdf8', // sky
  '#a78bfa', // violet
  '#34d399', // emerald
  '#fb7185', // rose
  '#22d3ee', // cyan
  '#a3e635', // lime
  '#fb923c', // orange
] as const

export function defaultGroupColor(name: string): string {
  let hash = 0
  for (const ch of name) hash = (hash * 31 + (ch.codePointAt(0) ?? 0)) >>> 0
  return GROUP_PALETTE[hash % GROUP_PALETTE.length] as string
}

/** The color a group renders with: the explicit choice, else its default. */
export function groupColor(styles: GroupStyles, name: string): string {
  return styles[name]?.color ?? defaultGroupColor(name)
}

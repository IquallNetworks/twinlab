// Autocompletion over a lab's fact namespace, for the command and expectation
// fields a test templates (delta 32).
//
// Pure and CodeMirror-free on purpose: this decides WHAT to offer, the editor
// wrapper decides how. That keeps it exercisable by `pnpm check:test-suites`
// alongside the rest of the suite model.
//
// The namespace a template sees is `node` (the executing node) and
// `nodes.<name>`. Which node `node` is depends on where the test runs, so the
// completions use a REPRESENTATIVE target: on a multi-node test every target
// has the same promised core, and the `_extras` differ only by device — which
// the two-tier warning in the Facts dialog already covers.

/** A path segment offered at the cursor. `container` marks a key with more
 * beneath it, so the UI can hint that another `.` follows. */
export interface FactCompletion {
  label: string
  container: boolean
  /** Where it came from, for the completion's detail line. */
  detail: string
}

/** The Jinja filters worth offering after a `|`. Deliberately just the one
 * Twinlab adds — jinja's builtins are not the thing an author is reaching for
 * here, and a long list would bury it. */
const FILTERS: readonly FactCompletion[] = [
  { label: 'address', container: false, detail: "strip a CIDR's prefix length" },
]

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

/** Walk a dotted path into the namespace root. Returns the object whose keys
 * should be offered, or null when the path leads somewhere with no keys (a
 * scalar, a list, or a miss). */
function resolvePath(root: Record<string, unknown>, segments: readonly string[]): unknown {
  let current: unknown = root
  for (const segment of segments) {
    if (!isRecord(current)) return null
    current = current[segment]
  }
  return current
}

/** The namespace root a template addresses: `node` is the representative
 * target's own dict, `nodes` is every node by name. */
export function factRoot(
  facts: Record<string, Record<string, unknown>>,
  representative: string | undefined,
): Record<string, unknown> {
  const root: Record<string, unknown> = { nodes: facts }
  const own = representative === undefined ? undefined : facts[representative]
  if (own !== undefined) root.node = own
  return root
}

/** What the text before the cursor is asking for. `null` means "not inside a
 * template expression", which is most of the time — a command is mostly shell
 * words, and offering fact paths there would be noise. */
export interface CompletionRequest {
  /** Already-typed path segments, e.g. ["node", "ospf"]. */
  segments: string[]
  /** The partial word being typed after the last dot. */
  prefix: string
  /** Start offset of `prefix` in the document — where a pick replaces from. */
  from: number
  /** True when the cursor follows a `|`, so filters are what is wanted. */
  filter: boolean
}

// Inside `{{ … }}` (or `{% … %}`) with nothing having closed it since.
function insideExpression(before: string): boolean {
  const open = Math.max(before.lastIndexOf('{{'), before.lastIndexOf('{%'))
  if (open === -1) return false
  const close = Math.max(before.lastIndexOf('}}'), before.lastIndexOf('%}'))
  return close < open
}

export function completionRequest(before: string): CompletionRequest | null {
  if (!insideExpression(before)) return null

  const filterMatch = /\|\s*([A-Za-z_]*)$/.exec(before)
  if (filterMatch !== null) {
    const prefix = filterMatch[1] ?? ''
    return { segments: [], prefix, from: before.length - prefix.length, filter: true }
  }

  // A dotted path: identifiers joined by dots, ending in the partial word.
  const pathMatch = /([A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z0-9_]*)*)$/.exec(before)
  if (pathMatch === null) {
    // Right after `{{` with nothing typed: offer the roots.
    if (/\{\{\s*$|\{%\s*$/.test(before)) {
      return { segments: [], prefix: '', from: before.length, filter: false }
    }
    return null
  }
  const path = pathMatch[1] ?? ''
  const parts = path.split('.')
  const prefix = parts[parts.length - 1] ?? ''
  return {
    segments: parts.slice(0, -1),
    prefix,
    from: before.length - prefix.length,
    filter: false,
  }
}

/** The completions for a request, already filtered by its prefix. */
export function factCompletions(
  request: CompletionRequest,
  root: Record<string, unknown>,
): FactCompletion[] {
  if (request.filter) {
    return FILTERS.filter((f) => f.label.startsWith(request.prefix))
  }
  const target = resolvePath(root, request.segments)
  if (!isRecord(target)) return []
  const where = request.segments.length === 0 ? 'namespace' : request.segments.join('.')
  return Object.keys(target)
    .filter((key) => key.startsWith(request.prefix))
    .map((key) => ({
      label: key,
      container: isRecord(target[key]),
      // `_extras` is netlab-shaped and unpromised (delta 26) — the detail line
      // is the only place that warning fits at the point of use.
      detail: key === '_extras' ? 'netlab-shaped, no stability promise' : where,
    }))
}

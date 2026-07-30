// Per-lab permission slugs (the lab payloads carry the caller's effective,
// masked set — owner-implicit + global + per-lab grants). Shared by the lab
// tab surfaces, the tab nav, and the role-aware landing redirect.
export const PERM_LAB_READ = 'lab:read'
export const PERM_LAB_EDIT = 'lab:edit'
export const PERM_LAB_CONFIGURE = 'lab:configure'
export const PERM_LAB_VALIDATE = 'lab:validate'
export const PERM_LAB_TERMINAL = 'lab:terminal'
export const PERM_LAB_DESTROY = 'lab:destroy'
export const PERM_LAB_GRANT = 'lab:grant'

/** Where a caller lands when opening a lab: authors (lab:edit) start on
 * Overview, where the definition lives; anyone else with node access
 * (terminal — e.g. the lab_operator role, which also carries configure)
 * starts on Nodes — connect and operate, not authoring; viewers read the
 * Overview. */
export function defaultLabTab(permissions: string[]): 'overview' | 'nodes' {
  if (permissions.includes(PERM_LAB_EDIT)) return 'overview'
  if (permissions.includes(PERM_LAB_TERMINAL)) return 'nodes'
  return 'overview'
}

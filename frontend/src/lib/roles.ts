import type { Role } from '@/lib/schemas'

// The role catalog is served by the backend (GET /roles); these helpers pick the
// subset assignable at a given scope. Global roles go on users/groups; lab roles are
// granted per lab.
export function globalRoles(roles: Role[]): Role[] {
  return roles.filter((r) => r.scopes.includes('global'))
}

export function labRoles(roles: Role[]): Role[] {
  return roles.filter((r) => r.scopes.includes('lab'))
}

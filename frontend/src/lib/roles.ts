// The backend seeds these roles (twinlab_backend.auth.permissions.ROLE_DEFINITIONS)
// and validates role assignments against them, but exposes no endpoint to list
// them. Mirror the seed here for the assignment UI; revisit if a roles endpoint
// is added.
export const ASSIGNABLE_ROLES = ['admin', 'operator', 'viewer'] as const

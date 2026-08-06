import { z } from 'zod'

/** A lab name is pinned into the stored definition as netlab's topology
 * `name:`, which netlab validates as an identifier (`[A-Za-z_][A-Za-z0-9_-]`,
 * 16 characters), and it prefixes the lab's docker objects, whose names start
 * with an alphanumeric. The intersection — a leading letter, then letters,
 * digits, dash or underscore — is what the backend accepts at create; a wider
 * name would create a lab whose definition PUT can never succeed. */
export const LAB_NAME_RE = /^[A-Za-z][A-Za-z0-9_-]*$/
export const LAB_NAME_MAX = 16
export const LAB_NAME_HINT = 'Start with a letter; then letters, digits, dash or underscore'

export const labNameSchema = z
  .string()
  .min(1, 'A lab name is required')
  .max(LAB_NAME_MAX, `At most ${LAB_NAME_MAX} characters`)
  .regex(LAB_NAME_RE, LAB_NAME_HINT)

/** The same rule for the surfaces that validate by hand rather than through a
 * form schema. Null means the name is usable. */
export function labNameError(name: string): string | null {
  const parsed = labNameSchema.safeParse(name)
  return parsed.success ? null : (parsed.error.issues[0]?.message ?? 'Invalid lab name')
}

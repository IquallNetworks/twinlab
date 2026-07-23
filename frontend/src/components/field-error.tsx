// Renders TanStack Form field errors. With a Standard Schema validator (zod),
// each entry is an issue object with a `message`; fall back to String for safety.
export function FieldError({ errors }: { errors: unknown[] }) {
  if (errors.length === 0) return null
  const text = errors
    .map((e) =>
      e && typeof e === 'object' && 'message' in e ? String((e as { message: unknown }).message) : String(e),
    )
    .join(', ')
  return <p className="text-destructive text-sm">{text}</p>
}

/** Sign-in through OIDC providers (contract delta 33) — the pure pieces the
 * login page, the users admin and the provider admin share. docs/oidc.md is
 * the design record. */

/** The codes a failed provider sign-in redirects back with
 * (`/login?oidc_error=<code>`). The page renders ITS OWN text for each and
 * never repeats anything the provider sent: the redirect is attacker-reachable,
 * so echoing it would let anyone put words on Twinlab's login page. */
export const OIDC_ERROR_MESSAGES = {
  oidc_unavailable:
    'Sign-in through this provider is not available right now. It may be disabled or unreachable, or this deployment may not be set up for provider sign-in.',
  oidc_state_invalid:
    'The sign-in could not be matched to one started from this browser, or it took too long. Start it again from this page.',
  oidc_provider_error: 'The provider did not complete the sign-in (it may have been cancelled).',
  oidc_token_invalid:
    'The provider’s answer could not be verified, so the sign-in was refused. An administrator can find the reason in the Twinlab server log.',
  oidc_email_missing:
    'The provider did not share an email address, and Twinlab needs one to create your account.',
  oidc_email_unverified:
    'The provider did not confirm your email address is verified, so it cannot be used to sign you in.',
  oidc_email_in_use:
    'An account with your email address already exists, but this provider is not allowed to sign into it. Ask an administrator to link it.',
  oidc_no_account:
    'There is no Twinlab account for you yet, and this provider does not create one. Ask an administrator for access.',
  oidc_identity_conflict:
    'The account with your email address is already linked to a different identity at this provider. Ask an administrator to unlink it.',
  account_disabled: 'Your Twinlab account is deactivated. Ask an administrator to reactivate it.',
} as const

export type OidcErrorCode = keyof typeof OIDC_ERROR_MESSAGES

function isOidcErrorCode(code: string): code is OidcErrorCode {
  return Object.hasOwn(OIDC_ERROR_MESSAGES, code)
}

/** The message for a callback error code. An unknown code gets a generic line
 * rather than the code's own text — the code arrived in a URL anyone can craft. */
export function oidcErrorMessage(code: string): string {
  return isOidcErrorCode(code)
    ? OIDC_ERROR_MESSAGES[code]
    : 'Signing in through the provider failed.'
}

/** Where a provider button navigates. A plain link, not a fetch: the flow is a
 * chain of top-level redirects through the provider and back. */
export function providerLoginUrl(apiBase: string, name: string, next: string): string {
  return `${apiBase}/auth/oidc/${encodeURIComponent(name)}/login?${new URLSearchParams({ next })}`
}

/** The button glyph when no icon was uploaded: the display name's first letter. */
export function monogram(displayName: string): string {
  const first = [...displayName.trim()][0]
  return first === undefined ? '?' : first.toUpperCase()
}

// --- Icons: the server's own rule (svg/png/webp, <= 32 KiB), said sooner. ---

export const ICON_TYPES = ['image/svg+xml', 'image/png', 'image/webp'] as const
export type IconType = (typeof ICON_TYPES)[number]
export const MAX_ICON_BYTES = 32 * 1024

export function isIconType(type: string): type is IconType {
  return (ICON_TYPES as readonly string[]).includes(type)
}

/** Why a picked file cannot be an icon, or null when it can. The server
 * re-checks the bytes against the type; this only refuses what it would. */
export function iconFileProblem(file: { type: string; size: number }): string | null {
  if (!isIconType(file.type)) return 'Use an SVG, PNG or WebP image.'
  if (file.size === 0) return 'The file is empty.'
  if (file.size > MAX_ICON_BYTES) return `The icon must be at most ${MAX_ICON_BYTES / 1024} KiB.`
  return null
}

// --- Users (delta 33) ---

/** The server's structural email check: one @, a non-empty local part and
 * domain, no whitespace. No deliverability check — a provider verifies an
 * address better than a lookup can. */
export function isEmailAddress(value: string): boolean {
  const at = value.indexOf('@')
  if (at <= 0 || at === value.length - 1) return false
  if (value.indexOf('@', at + 1) !== -1) return false
  return !/\s/.test(value)
}

/** A migration placeholder (`<username>@users.invalid`): `.invalid` is
 * reserved (RFC 2606), so no provider can ever verify it — the account cannot
 * be tied to by email until a real address replaces it. */
export function isPlaceholderEmail(email: string): boolean {
  return email.toLowerCase().endsWith('.invalid')
}

/** A provider name: the slug in its callback URL, so immutable once created. */
export const PROVIDER_NAME_PATTERN = /^[a-z0-9][a-z0-9-]{0,31}$/

/** The default scopes, and why: `openid` makes it OIDC, `email` feeds tying and
 * creation, `profile` the display name and derived username. */
export const DEFAULT_SCOPES = ['openid', 'email', 'profile']

/** Space- or comma-separated scopes → a de-duplicated list. */
export function parseScopes(text: string): string[] {
  return [...new Set(text.split(/[\s,]+/).filter((scope) => scope !== ''))]
}

/** The provider form's secret choice. On edit the secret is WRITE-ONLY. */
export type SecretMode = 'keep' | 'set' | 'none'

/** The secret part of a replace body: the field OMITTED keeps the stored
 * secret, a string replaces it, null removes it (a public client). */
export function secretChange(
  mode: SecretMode,
  value: string,
): { client_secret?: string | null } {
  switch (mode) {
    case 'keep':
      return {}
    case 'set':
      return { client_secret: value }
    case 'none':
      return { client_secret: null }
  }
}

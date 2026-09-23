import { describe, expect, it } from 'vitest'

import {
  MAX_ICON_BYTES,
  OIDC_ERROR_MESSAGES,
  iconFileProblem,
  isEmailAddress,
  isPlaceholderEmail,
  monogram,
  oidcErrorMessage,
  parseScopes,
  PROVIDER_NAME_PATTERN,
  providerLoginUrl,
  secretChange,
} from '@/lib/oidc'

describe('oidc error messages', () => {
  it('covers every code the backend redirects with', () => {
    // backend auth/oidc/flow.py FailureCode + resolution.RefusalCode
    const backendCodes = [
      'oidc_unavailable',
      'oidc_state_invalid',
      'oidc_provider_error',
      'oidc_token_invalid',
      'oidc_email_missing',
      'oidc_email_unverified',
      'oidc_email_in_use',
      'oidc_no_account',
      'oidc_identity_conflict',
      'account_disabled',
    ]
    expect(Object.keys(OIDC_ERROR_MESSAGES).sort()).toEqual([...backendCodes].sort())
    for (const code of backendCodes) expect(oidcErrorMessage(code)).toBe(OIDC_ERROR_MESSAGES[code as keyof typeof OIDC_ERROR_MESSAGES])
  })

  it('never echoes an unknown code', () => {
    const crafted = 'Your account was suspended, call +1-555-SCAM'
    expect(oidcErrorMessage(crafted)).not.toContain(crafted)
    expect(oidcErrorMessage('toString')).toBe('Signing in through the provider failed.')
  })
})

describe('provider buttons', () => {
  it('link to the login navigation with an encoded next path', () => {
    expect(providerLoginUrl('/twinlab/api/v1', 'dex', '/labs/x?tab=nodes')).toBe(
      '/twinlab/api/v1/auth/oidc/dex/login?next=%2Flabs%2Fx%3Ftab%3Dnodes',
    )
  })

  it('fall back to a monogram', () => {
    expect(monogram('google')).toBe('G')
    expect(monogram('  Ärzte SSO')).toBe('Ä')
    expect(monogram('')).toBe('?')
  })
})

describe('icon files', () => {
  it('mirror the server rule', () => {
    expect(iconFileProblem({ type: 'image/png', size: 1024 })).toBeNull()
    expect(iconFileProblem({ type: 'image/svg+xml', size: MAX_ICON_BYTES })).toBeNull()
    expect(iconFileProblem({ type: 'image/gif', size: 10 })).not.toBeNull()
    expect(iconFileProblem({ type: 'image/webp', size: MAX_ICON_BYTES + 1 })).not.toBeNull()
    expect(iconFileProblem({ type: 'image/png', size: 0 })).not.toBeNull()
  })
})

describe('user fields', () => {
  it('check email structure like the server', () => {
    expect(isEmailAddress('ana@example.com')).toBe(true)
    for (const bad of ['ana', '@example.com', 'ana@', 'a na@example.com', 'a@b@c']) {
      expect(isEmailAddress(bad)).toBe(false)
    }
  })

  it('flag migration placeholders', () => {
    expect(isPlaceholderEmail('admin@users.invalid')).toBe(true)
    expect(isPlaceholderEmail('admin@example.com')).toBe(false)
  })
})

describe('provider fields', () => {
  it('names are callback-URL slugs', () => {
    expect(PROVIDER_NAME_PATTERN.test('google')).toBe(true)
    expect(PROVIDER_NAME_PATTERN.test('corp-sso-2')).toBe(true)
    for (const bad of ['Google', '-x', 'a_b', 'x'.repeat(33), '']) {
      expect(PROVIDER_NAME_PATTERN.test(bad)).toBe(false)
    }
  })

  it('scopes parse from free text', () => {
    expect(parseScopes('openid email,profile  email')).toEqual(['openid', 'email', 'profile'])
    expect(parseScopes('  ')).toEqual([])
  })
})

describe('client secret on replace', () => {
  it('omits the field to keep it, sends null to remove it', () => {
    expect(secretChange('keep', 'ignored')).toEqual({})
    expect('client_secret' in secretChange('keep', 'x')).toBe(false)
    expect(secretChange('set', 's3cret')).toEqual({ client_secret: 's3cret' })
    expect(secretChange('none', 'ignored')).toEqual({ client_secret: null })
  })
})

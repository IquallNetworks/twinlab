import { useForm } from '@tanstack/react-form'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useNavigate } from '@tanstack/react-router'
import { Copy } from 'lucide-react'
import { toast } from 'sonner'
import { z } from 'zod'

import { FieldError } from '@/components/field-error'
import { ProviderButton } from '@/components/oidc/provider-button'
import { PasswordInput } from '@/components/password-input'
import { ThemeToggle } from '@/components/theme-toggle'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Wordmark } from '@/components/wordmark'
import { api } from '@/lib/api'
import { API_BASE } from '@/lib/base-path'
import { copyText } from '@/lib/clipboard'
import { toastError } from '@/lib/error-toast'
import { oidcErrorMessage, providerLoginUrl } from '@/lib/oidc'
import { loginProvidersQueryOptions, meQueryOptions } from '@/lib/queries'
import { useDocumentTitle } from '@/lib/use-document-title'

const loginSchema = z.object({
  username: z.string().min(1, 'Username is required'),
  password: z.string().min(1, 'Password is required'),
})

/** A failed provider sign-in, as the callback reported it. The text is the
 * page's own for the code (lib/oidc.ts) — never provider-supplied. Copyable,
 * like every failure in the UI: the code is what an admin needs to look up. */
function OidcError({ code }: { code: string }) {
  const message = oidcErrorMessage(code)
  return (
    <div
      role="alert"
      className="flex items-start gap-2 rounded-md border border-destructive/50 bg-destructive/5 p-3 text-sm text-destructive"
    >
      <p className="flex-1">
        {message} <span className="font-mono text-xs opacity-80">({code})</span>
      </p>
      <button
        type="button"
        title="Copy error"
        aria-label="Copy error"
        className="shrink-0 opacity-70 hover:opacity-100"
        onClick={() =>
          void copyText(`${message}\n${code}`).then((ok) =>
            ok ? toast.success('Copied') : toast.error('Copy failed'),
          )
        }
      >
        <Copy className="size-4" />
      </button>
    </div>
  )
}

/** One button per enabled provider, below the password form and outside it.
 * Nothing renders while there are none (or the list cannot be read): password
 * sign-in must never wait on, or be blocked by, provider sign-in. */
function ProviderSignIn() {
  const { data: providers } = useQuery(loginProvidersQueryOptions)
  if (providers === undefined || providers.length === 0) return null
  return (
    <div className="flex flex-col gap-3">
      <div className="flex items-center gap-3 font-mono text-[0.65rem] tracking-wide text-muted-foreground uppercase">
        <span className="h-px flex-1 bg-border" />
        or
        <span className="h-px flex-1 bg-border" />
      </div>
      {providers.map((provider) => (
        <ProviderButton
          key={provider.name}
          displayName={provider.display_name}
          icon={provider.icon}
          href={providerLoginUrl(API_BASE, provider.name, '/')}
        />
      ))}
    </div>
  )
}

export function LoginPage({ oidcError }: { oidcError?: string }) {
  useDocumentTitle('Sign in')
  const navigate = useNavigate()
  const queryClient = useQueryClient()

  const login = useMutation({
    mutationFn: (value: z.infer<typeof loginSchema>) => api.login(value.username, value.password),
    onSuccess: async (info) => {
      queryClient.setQueryData(meQueryOptions.queryKey, info)
      await navigate({ to: '/' })
    },
    onError: (err) => toastError(err, 'Login failed'),
  })

  const form = useForm({
    defaultValues: { username: '', password: '' },
    validators: { onSubmit: loginSchema },
    onSubmit: async ({ value }) => {
      await login.mutateAsync(value)
    },
  })

  return (
    <div className="relative grid min-h-screen place-items-center px-4">
      <div className="absolute top-3 right-3 flex items-center gap-1">
        <ThemeToggle />
      </div>

      <div className="flex w-full max-w-sm flex-col gap-6">
        <h1 className="sr-only">Sign in to Twinlab</h1>
        <div className="flex justify-center">
          <Wordmark className="scale-125" />
        </div>

        <Card>
          <CardHeader>
            <CardTitle className="font-heading">Sign in</CardTitle>
            <CardDescription>Use your Twinlab account credentials.</CardDescription>
          </CardHeader>
          <CardContent className="flex flex-col gap-4">
            {oidcError !== undefined && <OidcError code={oidcError} />}
            <form
              className="flex flex-col gap-4"
              onSubmit={(e) => {
                e.preventDefault()
                e.stopPropagation()
                void form.handleSubmit()
              }}
            >
              <form.Field name="username">
                {(field) => (
                  <div className="flex flex-col gap-2">
                    <Label htmlFor={field.name}>Username</Label>
                    <Input
                      id={field.name}
                      name={field.name}
                      autoComplete="username"
                      value={field.state.value}
                      onBlur={field.handleBlur}
                      onChange={(e) => field.handleChange(e.target.value)}
                    />
                    <FieldError errors={field.state.meta.errors} />
                  </div>
                )}
              </form.Field>

              <form.Field name="password">
                {(field) => (
                  <div className="flex flex-col gap-2">
                    <Label htmlFor={field.name}>Password</Label>
                    <PasswordInput
                      id={field.name}
                      name={field.name}
                      autoComplete="current-password"
                      value={field.state.value}
                      onBlur={field.handleBlur}
                      onChange={(e) => field.handleChange(e.target.value)}
                    />
                    <FieldError errors={field.state.meta.errors} />
                  </div>
                )}
              </form.Field>

              <form.Subscribe selector={(s) => ({ canSubmit: s.canSubmit, isSubmitting: s.isSubmitting })}>
                {({ canSubmit, isSubmitting }) => (
                  <Button type="submit" disabled={!canSubmit || isSubmitting}>
                    {isSubmitting ? 'Signing in…' : 'Sign in'}
                  </Button>
                )}
              </form.Subscribe>
            </form>
            <ProviderSignIn />
          </CardContent>
        </Card>

        <p className="text-center font-mono text-[0.65rem] tracking-wide text-muted-foreground uppercase">
          declarative, reproducible network twins
        </p>
      </div>
    </div>
  )
}

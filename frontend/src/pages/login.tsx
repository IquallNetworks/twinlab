import { useForm } from '@tanstack/react-form'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useNavigate } from '@tanstack/react-router'
import { z } from 'zod'

import { FieldError } from '@/components/field-error'
import { PasswordInput } from '@/components/password-input'
import { ThemeToggle } from '@/components/theme-toggle'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Wordmark } from '@/components/wordmark'
import { api } from '@/lib/api'
import { toastError } from '@/lib/error-toast'
import { meQueryOptions } from '@/lib/queries'
import { useDocumentTitle } from '@/lib/use-document-title'

const loginSchema = z.object({
  username: z.string().min(1, 'Username is required'),
  password: z.string().min(1, 'Password is required'),
})

export function LoginPage() {
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
          <CardContent>
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
          </CardContent>
        </Card>

        <p className="text-center font-mono text-[0.65rem] tracking-wide text-muted-foreground uppercase">
          declarative, reproducible network twins
        </p>
      </div>
    </div>
  )
}

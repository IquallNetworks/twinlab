import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useForm } from '@tanstack/react-form'
import { useNavigate } from '@tanstack/react-router'
import { toast } from 'sonner'
import { z } from 'zod'

import { FieldError } from '@/components/field-error'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { api } from '@/lib/api'
import { meQueryOptions } from '@/lib/queries'

const loginSchema = z.object({
  username: z.string().min(1, 'Username is required'),
  password: z.string().min(1, 'Password is required'),
})

export function LoginPage() {
  const navigate = useNavigate()
  const queryClient = useQueryClient()

  const login = useMutation({
    mutationFn: (value: z.infer<typeof loginSchema>) => api.login(value.username, value.password),
    onSuccess: async (info) => {
      queryClient.setQueryData(meQueryOptions.queryKey, info)
      await navigate({ to: '/' })
    },
    onError: (err) => toast.error(err instanceof Error ? err.message : 'Login failed'),
  })

  const form = useForm({
    defaultValues: { username: '', password: '' },
    validators: { onSubmit: loginSchema },
    onSubmit: async ({ value }) => {
      await login.mutateAsync(value)
    },
  })

  return (
    <div className="flex min-h-screen items-center justify-center px-4">
      <Card className="w-full max-w-sm">
        <CardHeader>
          <CardTitle>Sign in to Twinlab</CardTitle>
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
                  <Input
                    id={field.name}
                    name={field.name}
                    type="password"
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
    </div>
  )
}

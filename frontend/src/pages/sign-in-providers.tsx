import { useForm } from '@tanstack/react-form'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Copy, Pencil } from 'lucide-react'
import { useState } from 'react'
import { toast } from 'sonner'
import { z } from 'zod'

import { FieldError } from '@/components/field-error'
import { ProviderButton, ProviderGlyph } from '@/components/oidc/provider-button'
import { PasswordInput } from '@/components/password-input'
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
  AlertDialogTrigger,
} from '@/components/ui/alert-dialog'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Checkbox } from '@/components/ui/checkbox'
import {
  Dialog,
  DialogClose,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { Skeleton } from '@/components/ui/skeleton'
import { api } from '@/lib/api'
import { copyText } from '@/lib/clipboard'
import { toastError } from '@/lib/error-toast'
import {
  DEFAULT_SCOPES,
  ICON_TYPES,
  PROVIDER_NAME_PATTERN,
  iconFileProblem,
  parseScopes,
  secretChange,
  type SecretMode,
} from '@/lib/oidc'
import { oidcProvidersQueryOptions, principalsQueryOptions } from '@/lib/queries'
import type { OidcProvider } from '@/lib/schemas'
import { useDocumentTitle } from '@/lib/use-document-title'

// docs/oidc.md, "What trust_email actually trusts" — shown beside the switch.
const TRUST_EMAIL_WARNING =
  'Setting this asserts that every address this issuer can put in an email claim belongs to the person signing in. That holds for a tenant that controls its whole mail domain; it does not hold for a multi-tenant issuer, or one where users can edit their own email attribute.'

// A radix Select item cannot carry the empty string; this stands for "none".
const NO_GROUP = '__none__'

function CopyValue({ value, label }: { value: string; label: string }) {
  return (
    <Button
      type="button"
      variant="ghost"
      size="icon"
      className="size-7"
      title={`Copy ${label}`}
      aria-label={`Copy ${label}`}
      onClick={() =>
        void copyText(value).then((ok) =>
          ok ? toast.success(`Copied ${label}`) : toast.error('Copy failed'),
        )
      }
    >
      <Copy className="size-4" />
    </Button>
  )
}

// Mirrors the server's own rules; the wire stays the authority.
const providerFormSchema = z
  .object({
    name: z.string().regex(PROVIDER_NAME_PATTERN, 'Lowercase letters, digits and dashes; 1–32'),
    display_name: z.string().trim().min(1, 'Required').max(64, 'At most 64 characters'),
    issuer: z
      .string()
      .max(512, 'At most 512 characters')
      .refine((v) => /^https?:\/\/\S+$/.test(v), 'An http(s) URL, exactly as the provider names itself'),
    client_id: z.string().min(1, 'Required').max(255, 'At most 255 characters'),
    secret_mode: z.enum(['keep', 'set', 'none']),
    client_secret: z.string().max(4096, 'At most 4096 characters'),
    scopes: z
      .string()
      .refine((v) => parseScopes(v).includes('openid'), 'The scopes must include openid'),
    allow_create_users: z.boolean(),
    allow_email_tying: z.boolean(),
    trust_email: z.boolean(),
    default_group_id: z.string(),
    enabled: z.boolean(),
  })
  .refine((v) => v.secret_mode !== 'set' || v.client_secret !== '', {
    message: 'Enter the client secret',
    path: ['client_secret'],
  })
type ProviderFormValues = z.infer<typeof providerFormSchema>

function initialValues(provider: OidcProvider | null): ProviderFormValues {
  if (provider === null) {
    return {
      name: '',
      display_name: '',
      issuer: '',
      client_id: '',
      secret_mode: 'set',
      client_secret: '',
      scopes: DEFAULT_SCOPES.join(' '),
      // All three off by default: a provider that can only sign in users who
      // are already linked is the safe starting point.
      allow_create_users: false,
      allow_email_tying: false,
      trust_email: false,
      default_group_id: NO_GROUP,
      enabled: true,
    }
  }
  return {
    name: provider.name,
    display_name: provider.display_name,
    issuer: provider.issuer,
    client_id: provider.client_id,
    secret_mode: 'keep',
    client_secret: '',
    scopes: provider.scopes.join(' '),
    allow_create_users: provider.allow_create_users,
    allow_email_tying: provider.allow_email_tying,
    trust_email: provider.trust_email,
    default_group_id: provider.default_group?.id ?? NO_GROUP,
    enabled: provider.enabled,
  }
}

function SwitchField({
  id,
  checked,
  onChange,
  label,
  hint,
}: {
  id: string
  checked: boolean
  onChange: (checked: boolean) => void
  label: string
  hint: string
}) {
  return (
    <div className="flex items-start gap-2">
      <Checkbox id={id} checked={checked} onCheckedChange={(c) => onChange(c === true)} />
      <div className="flex flex-col gap-0.5">
        <Label htmlFor={id} className="font-normal">
          {label}
        </Label>
        <p className="text-xs text-muted-foreground">{hint}</p>
      </div>
    </div>
  )
}

/** Create or edit a provider. `name` and `issuer` are fixed once created: the
 * name is part of the callback URL registered at the provider, and linked
 * identities are keyed by the provider, so re-pointing it at another issuer
 * would sign one issuer's people into another's accounts. The client secret is
 * write-only — on edit it is kept, replaced or removed, never shown. */
function ProviderFormDialog({
  provider,
  trigger,
}: {
  provider: OidcProvider | null
  trigger: React.ReactNode
}) {
  const [open, setOpen] = useState(false)
  const queryClient = useQueryClient()
  const { data: principals } = useQuery(principalsQueryOptions)
  const creating = provider === null

  const save = useMutation({
    mutationFn: (value: ProviderFormValues) => {
      const common = {
        display_name: value.display_name.trim(),
        issuer: value.issuer,
        client_id: value.client_id,
        scopes: parseScopes(value.scopes),
        allow_create_users: value.allow_create_users,
        allow_email_tying: value.allow_email_tying,
        trust_email: value.trust_email,
        default_group_id: value.default_group_id === NO_GROUP ? null : value.default_group_id,
        enabled: value.enabled,
      }
      if (creating) {
        return api.createOidcProvider({
          ...common,
          name: value.name,
          client_secret: value.secret_mode === 'set' ? value.client_secret : null,
        })
      }
      return api.replaceOidcProvider(provider.name, {
        ...common,
        ...secretChange(value.secret_mode, value.client_secret),
      })
    },
    onSuccess: async (saved) => {
      await queryClient.invalidateQueries({ queryKey: oidcProvidersQueryOptions.queryKey })
      toast.success(creating ? `Added ${saved.display_name}` : `Saved ${saved.display_name}`)
      setOpen(false)
    },
    onError: (err) => toastError(err, 'Could not save the provider'),
  })

  const form = useForm({
    defaultValues: initialValues(provider),
    validators: { onSubmit: providerFormSchema },
    onSubmit: ({ value }) => save.mutate(value),
  })

  const idp = (field: string) => `provider-${provider?.name ?? 'new'}-${field}`

  return (
    <Dialog
      open={open}
      onOpenChange={(next) => {
        setOpen(next)
        if (next) form.reset(initialValues(provider))
      }}
    >
      <DialogTrigger asChild>{trigger}</DialogTrigger>
      <DialogContent className="max-h-[90vh] overflow-y-auto sm:max-w-xl">
        <form
          onSubmit={(e) => {
            e.preventDefault()
            e.stopPropagation()
            void form.handleSubmit()
          }}
        >
          <DialogHeader>
            <DialogTitle>{creating ? 'Add sign-in provider' : `Edit ${provider.display_name}`}</DialogTitle>
            <DialogDescription>
              {creating
                ? 'Twinlab reads the issuer’s discovery document when you save, so a mistyped issuer is refused here rather than at someone’s first sign-in.'
                : 'The name and the issuer are fixed once created. To change the issuer, add a new provider.'}
            </DialogDescription>
          </DialogHeader>

          <div className="flex flex-col gap-4 py-4">
            <div className="grid gap-4 sm:grid-cols-2">
              <form.Field name="name">
                {(field) => (
                  <div className="flex flex-col gap-2">
                    <Label htmlFor={idp('name')}>Name</Label>
                    <Input
                      id={idp('name')}
                      className="font-mono"
                      disabled={!creating}
                      placeholder="google"
                      value={field.state.value}
                      onBlur={field.handleBlur}
                      onChange={(e) => field.handleChange(e.target.value)}
                    />
                    <FieldError errors={field.state.meta.errors} />
                  </div>
                )}
              </form.Field>
              <form.Field name="display_name">
                {(field) => (
                  <div className="flex flex-col gap-2">
                    <Label htmlFor={idp('display')}>Button label</Label>
                    <Input
                      id={idp('display')}
                      placeholder="Google"
                      value={field.state.value}
                      onBlur={field.handleBlur}
                      onChange={(e) => field.handleChange(e.target.value)}
                    />
                    <FieldError errors={field.state.meta.errors} />
                  </div>
                )}
              </form.Field>
            </div>

            <form.Field name="issuer">
              {(field) => (
                <div className="flex flex-col gap-2">
                  <Label htmlFor={idp('issuer')}>Issuer</Label>
                  <Input
                    id={idp('issuer')}
                    className="font-mono"
                    disabled={!creating}
                    placeholder="https://accounts.google.com"
                    value={field.state.value}
                    onBlur={field.handleBlur}
                    onChange={(e) => field.handleChange(e.target.value)}
                  />
                  <FieldError errors={field.state.meta.errors} />
                </div>
              )}
            </form.Field>

            <form.Field name="client_id">
              {(field) => (
                <div className="flex flex-col gap-2">
                  <Label htmlFor={idp('client')}>Client ID</Label>
                  <Input
                    id={idp('client')}
                    className="font-mono"
                    value={field.state.value}
                    onBlur={field.handleBlur}
                    onChange={(e) => field.handleChange(e.target.value)}
                  />
                  <FieldError errors={field.state.meta.errors} />
                </div>
              )}
            </form.Field>

            <form.Field name="secret_mode">
              {(modeField) => (
                <div className="flex flex-col gap-2">
                  <Label htmlFor={idp('secret-mode')}>Client secret</Label>
                  <Select
                    value={modeField.state.value}
                    onValueChange={(v) => modeField.handleChange(v as SecretMode)}
                  >
                    <SelectTrigger id={idp('secret-mode')} className="w-full">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      {!creating && (
                        <SelectItem value="keep">
                          {provider.has_client_secret
                            ? 'Keep the stored secret'
                            : 'Keep it a public client (no secret)'}
                        </SelectItem>
                      )}
                      <SelectItem value="set">
                        {creating || !provider.has_client_secret ? 'Set a secret' : 'Replace the secret'}
                      </SelectItem>
                      <SelectItem value="none">
                        {creating ? 'None — a public client (PKCE only)' : 'Remove it — a public client'}
                      </SelectItem>
                    </SelectContent>
                  </Select>
                  {modeField.state.value === 'set' && (
                    <form.Field name="client_secret">
                      {(field) => (
                        <>
                          <PasswordInput
                            id={idp('secret')}
                            aria-label="Client secret value"
                            autoComplete="off"
                            value={field.state.value}
                            onBlur={field.handleBlur}
                            onChange={(e) => field.handleChange(e.target.value)}
                          />
                          <FieldError errors={field.state.meta.errors} />
                        </>
                      )}
                    </form.Field>
                  )}
                  <p className="text-xs text-muted-foreground">
                    Stored encrypted and never shown again.
                  </p>
                </div>
              )}
            </form.Field>

            <form.Field name="scopes">
              {(field) => (
                <div className="flex flex-col gap-2">
                  <Label htmlFor={idp('scopes')}>Scopes</Label>
                  <Input
                    id={idp('scopes')}
                    className="font-mono"
                    value={field.state.value}
                    onBlur={field.handleBlur}
                    onChange={(e) => field.handleChange(e.target.value)}
                  />
                  <p className="text-xs text-muted-foreground">
                    Space-separated. email feeds tying and account creation; profile the display
                    name.
                  </p>
                  <FieldError errors={field.state.meta.errors} />
                </div>
              )}
            </form.Field>

            <div className="flex flex-col gap-3 rounded-md border p-3">
              <form.Field name="allow_create_users">
                {(field) => (
                  <SwitchField
                    id={idp('create')}
                    checked={field.state.value}
                    onChange={field.handleChange}
                    label="Create accounts"
                    hint="Someone with no Twinlab account and a verified email gets one, with no access beyond the default group."
                  />
                )}
              </form.Field>
              <form.Field name="allow_email_tying">
                {(field) => (
                  <SwitchField
                    id={idp('tie')}
                    checked={field.state.value}
                    onChange={field.handleChange}
                    label="Tie to existing accounts by email"
                    hint="A verified email signs into the Twinlab account that holds it, and links the two."
                  />
                )}
              </form.Field>
              <form.Field name="trust_email">
                {(field) => (
                  <div className="flex flex-col gap-1">
                    <SwitchField
                      id={idp('trust')}
                      checked={field.state.value}
                      onChange={field.handleChange}
                      label="Trust this issuer’s emails"
                      hint="Count an email as verified when the provider does not say either way (for example Microsoft Entra ID). An explicit “unverified” is still refused."
                    />
                    <p className="ml-6 text-xs text-amber-600 dark:text-amber-400">
                      {TRUST_EMAIL_WARNING}
                    </p>
                  </div>
                )}
              </form.Field>
              <form.Field name="enabled">
                {(field) => (
                  <SwitchField
                    id={idp('enabled')}
                    checked={field.state.value}
                    onChange={field.handleChange}
                    label="Enabled"
                    hint="A disabled provider is hidden from the login page and refuses sign-in; its links are kept."
                  />
                )}
              </form.Field>
            </div>

            <form.Field name="default_group_id">
              {(field) => (
                <div className="flex flex-col gap-2">
                  <Label htmlFor={idp('group')}>Default group for new accounts</Label>
                  <Select value={field.state.value} onValueChange={field.handleChange}>
                    <SelectTrigger id={idp('group')} className="w-full">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value={NO_GROUP}>None</SelectItem>
                      {(principals?.groups ?? []).map((group) => (
                        <SelectItem key={group.id} value={group.id}>
                          {group.name}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                  <p className="text-xs text-muted-foreground">
                    Joined when this provider creates an account — never re-applied later.
                  </p>
                </div>
              )}
            </form.Field>
          </div>

          <DialogFooter>
            <DialogClose asChild>
              <Button type="button" variant="outline">
                Cancel
              </Button>
            </DialogClose>
            <Button type="submit" disabled={save.isPending}>
              {save.isPending ? 'Saving…' : creating ? 'Add provider' : 'Save'}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}

/** Upload or clear the button icon, previewing the button exactly as the login
 * page will render it. The file is checked here against the server's rule; the
 * server re-checks the bytes themselves. */
function IconDialog({ provider }: { provider: OidcProvider }) {
  const [open, setOpen] = useState(false)
  const [picked, setPicked] = useState<{ file: File; preview: string } | null>(null)
  const [problem, setProblem] = useState<string | null>(null)
  const queryClient = useQueryClient()

  function reset() {
    if (picked !== null) URL.revokeObjectURL(picked.preview)
    setPicked(null)
    setProblem(null)
  }

  const done = async (message: string) => {
    await queryClient.invalidateQueries({ queryKey: oidcProvidersQueryOptions.queryKey })
    await queryClient.invalidateQueries({ queryKey: ['login-providers'] })
    toast.success(message)
    reset()
    setOpen(false)
  }

  const upload = useMutation({
    mutationFn: (file: File) => api.setOidcProviderIcon(provider.name, file, file.type),
    onSuccess: () => done('Icon saved'),
    onError: (err) => toastError(err, 'Could not save the icon'),
  })
  const clear = useMutation({
    mutationFn: () => api.clearOidcProviderIcon(provider.name),
    onSuccess: () => done('Icon cleared'),
    onError: (err) => toastError(err, 'Could not clear the icon'),
  })

  const previewIcon = picked?.preview ?? provider.icon

  return (
    <Dialog
      open={open}
      onOpenChange={(next) => {
        setOpen(next)
        if (!next) reset()
      }}
    >
      <DialogTrigger asChild>
        <Button variant="outline" size="sm">
          Icon
        </Button>
      </DialogTrigger>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Icon for {provider.display_name}</DialogTitle>
          <DialogDescription>
            SVG, PNG or WebP, up to 32 KiB. Without one the button shows the label’s first letter.
            Twinlab ships no brand logos — use the mark the provider publishes for sign-in buttons.
          </DialogDescription>
        </DialogHeader>
        <div className="flex flex-col gap-4 py-2">
          <div className="flex flex-col gap-2">
            <Label>Preview</Label>
            <ProviderButton displayName={provider.display_name} icon={previewIcon} />
          </div>
          <div className="flex flex-col gap-2">
            <Label htmlFor={`icon-${provider.name}`}>Image file</Label>
            <Input
              id={`icon-${provider.name}`}
              type="file"
              accept={ICON_TYPES.join(',')}
              onChange={(e) => {
                reset()
                const file = e.target.files?.[0]
                if (file === undefined) return
                const why = iconFileProblem(file)
                if (why !== null) {
                  setProblem(why)
                  return
                }
                setPicked({ file, preview: URL.createObjectURL(file) })
              }}
            />
            {problem !== null && <p className="text-sm text-destructive">{problem}</p>}
          </div>
        </div>
        <DialogFooter>
          {provider.icon !== null && (
            <Button
              type="button"
              variant="ghost"
              className="mr-auto"
              disabled={clear.isPending}
              onClick={() => clear.mutate()}
            >
              Clear icon
            </Button>
          )}
          <DialogClose asChild>
            <Button type="button" variant="outline">
              Cancel
            </Button>
          </DialogClose>
          <Button
            type="button"
            disabled={picked === null || upload.isPending}
            onClick={() => picked !== null && upload.mutate(picked.file)}
          >
            {upload.isPending ? 'Saving…' : 'Save icon'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

/** Deleting drops the provider's LINKS and keeps its users — so a user it
 * created is left with only a random password nobody knows. The dialog names
 * how many are affected; it does not block, because removing a compromised
 * provider must always be possible. */
function DeleteProviderButton({ provider }: { provider: OidcProvider }) {
  const queryClient = useQueryClient()
  const del = useMutation({
    mutationFn: () => api.deleteOidcProvider(provider.name),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: oidcProvidersQueryOptions.queryKey })
      toast.success(`Deleted ${provider.display_name}`)
    },
    onError: (err) => toastError(err, 'Could not delete the provider'),
  })
  const linked = provider.linked_users
  return (
    <AlertDialog>
      <AlertDialogTrigger asChild>
        <Button variant="ghost" size="sm" disabled={del.isPending}>
          Delete
        </Button>
      </AlertDialogTrigger>
      <AlertDialogContent>
        <AlertDialogHeader>
          <AlertDialogTitle>Delete {provider.display_name}?</AlertDialogTitle>
          <AlertDialogDescription>
            {linked === 0
              ? 'No account is linked to it.'
              : `${linked} ${linked === 1 ? 'account is' : 'accounts are'} linked to it. The accounts stay, but anyone who signs in only through this provider will have no way in until an administrator resets their password or they are linked elsewhere.`}{' '}
            To stop sign-in without losing the links, disable it instead.
          </AlertDialogDescription>
        </AlertDialogHeader>
        <AlertDialogFooter>
          <AlertDialogCancel>Cancel</AlertDialogCancel>
          <AlertDialogAction onClick={() => del.mutate()}>Delete</AlertDialogAction>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  )
}

function ProviderCard({ provider }: { provider: OidcProvider }) {
  return (
    <Card>
      <CardHeader className="flex flex-row items-start justify-between gap-4">
        <div className="flex min-w-0 items-center gap-3">
          <ProviderGlyph displayName={provider.display_name} icon={provider.icon} />
          <div className="min-w-0">
            <CardTitle className="text-base">{provider.display_name}</CardTitle>
            <div className="truncate font-mono text-xs text-muted-foreground">
              {provider.name} · {provider.issuer}
            </div>
          </div>
        </div>
        <div className="flex shrink-0 items-center gap-2">
          <ProviderFormDialog
            provider={provider}
            trigger={
              <Button variant="outline" size="sm">
                <Pencil className="size-3.5" />
                Edit
              </Button>
            }
          />
          <IconDialog provider={provider} />
          <DeleteProviderButton provider={provider} />
        </div>
      </CardHeader>
      <CardContent className="flex flex-col gap-3 text-sm">
        <div className="flex flex-wrap gap-1">
          <Badge variant={provider.enabled ? 'secondary' : 'outline'}>
            {provider.enabled ? 'enabled' : 'disabled'}
          </Badge>
          {provider.allow_create_users && <Badge variant="outline">creates accounts</Badge>}
          {provider.allow_email_tying && <Badge variant="outline">ties by email</Badge>}
          {provider.trust_email && (
            <Badge variant="outline" className="border-amber-500/60 text-amber-600 dark:text-amber-400">
              trusts emails
            </Badge>
          )}
          {!provider.has_client_secret && <Badge variant="outline">public client</Badge>}
          {!provider.client_secret_readable && (
            <Badge variant="destructive" title="OIDC_SECRET_KEY changed or was lost — edit the provider and set the secret again">
              secret unreadable
            </Badge>
          )}
          <span className="ml-1 text-xs text-muted-foreground">
            {provider.linked_users} linked {provider.linked_users === 1 ? 'account' : 'accounts'}
            {provider.default_group !== null && ` · new accounts join ${provider.default_group.name}`}
          </span>
        </div>
        {!provider.client_secret_readable && (
          <p className="text-xs text-destructive">
            The stored client secret no longer decrypts, so sign-in through this provider fails.
            Edit the provider and set the secret again.
          </p>
        )}
        <div className="flex flex-col gap-1">
          <span className="text-xs font-medium text-muted-foreground">
            Redirect URI to register at the provider
          </span>
          {provider.callback_url !== null ? (
            <div className="flex items-center gap-1">
              <code className="truncate rounded bg-muted px-2 py-1 font-mono text-xs">
                {provider.callback_url}
              </code>
              <CopyValue value={provider.callback_url} label="redirect URI" />
            </div>
          ) : (
            <p className="text-xs text-muted-foreground">
              Not available: this deployment has no PUBLIC_ORIGIN, so provider sign-in is off.
              Set it in the stack’s .env and restart.
            </p>
          )}
        </div>
      </CardContent>
    </Card>
  )
}

/** Sign-in providers (contract delta 33, docs/oidc.md): OIDC providers people
 * may sign in through. Gated by user:manage, since a provider decides who
 * gets an account. */
export function SignInProvidersPage() {
  useDocumentTitle('Sign-in providers')
  const { data: providers, isPending, isError, error } = useQuery(oidcProvidersQueryOptions)

  return (
    <div className="flex flex-col gap-6">
      <div className="flex items-end justify-between gap-4">
        <div className="flex flex-col gap-1">
          <h1 className="font-heading text-2xl font-semibold">Sign-in providers</h1>
          <p className="text-sm text-muted-foreground">
            OIDC providers people can sign in through, beside their Twinlab password.
          </p>
        </div>
        <ProviderFormDialog provider={null} trigger={<Button>Add provider</Button>} />
      </div>

      {isError ? (
        <p className="text-sm text-destructive">
          {error instanceof Error ? error.message : 'Failed to load providers'}
        </p>
      ) : isPending ? (
        <Skeleton className="h-32 w-full" />
      ) : providers.length === 0 ? (
        <div className="border border-dashed p-10 text-center text-sm text-muted-foreground">
          No providers yet. Add one to offer “Sign in with …” on the login page.
        </div>
      ) : (
        providers.map((provider) => <ProviderCard key={provider.name} provider={provider} />)
      )}
    </div>
  )
}

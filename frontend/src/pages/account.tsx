import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Copy, Download, Trash2 } from 'lucide-react'
import { useState } from 'react'
import { toast } from 'sonner'

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
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import {
  Dialog,
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
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import { Textarea } from '@/components/ui/textarea'
import { api } from '@/lib/api'
import { copyText } from '@/lib/clipboard'
import { formatDateTime } from '@/lib/format'
import { apiKeysQueryOptions, sshAccessQueryOptions, sshKeysQueryOptions } from '@/lib/queries'
import { JUMP_HOST_ALIAS, jumpCoordinates, sshConfigBlock } from '@/lib/ssh'
import { useDocumentTitle } from '@/lib/use-document-title'

function CopyButton({ value, label }: { value: string; label: string }) {
  return (
    <Button
      variant="ghost"
      size="icon"
      className="size-7"
      title={`Copy ${label}`}
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

/** A one-time secret (Bearer key / private key): shown exactly once, never
 * retrievable again — the reveal replaces the create form in its dialog. */
function SecretReveal({ secret, hint }: { secret: string; hint: string }) {
  return (
    <div className="flex flex-col gap-2">
      <div className="flex items-start gap-2">
        <pre className="bg-muted max-h-64 flex-1 overflow-auto rounded-md p-3 font-mono text-xs whitespace-pre-wrap break-all">
          {secret}
        </pre>
        <CopyButton value={secret} label="secret" />
      </div>
      <p className="text-muted-foreground text-xs">{hint}</p>
    </div>
  )
}

function DeleteKeyAction({
  title,
  description,
  onDelete,
  pending,
}: {
  title: string
  description: string
  onDelete: () => void
  pending: boolean
}) {
  return (
    <AlertDialog>
      <AlertDialogTrigger asChild>
        <Button
          variant="ghost"
          size="icon"
          className="text-muted-foreground hover:text-destructive size-7"
          disabled={pending}
          title={title}
        >
          <Trash2 className="size-4" />
        </Button>
      </AlertDialogTrigger>
      <AlertDialogContent>
        <AlertDialogHeader>
          <AlertDialogTitle>{title}</AlertDialogTitle>
          <AlertDialogDescription>{description}</AlertDialogDescription>
        </AlertDialogHeader>
        <AlertDialogFooter>
          <AlertDialogCancel>Cancel</AlertDialogCancel>
          <AlertDialogAction onClick={onDelete}>Delete</AlertDialogAction>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  )
}

function ApiKeysCard() {
  const queryClient = useQueryClient()
  const { data: keys, isPending, isError, error } = useQuery(apiKeysQueryOptions)
  const [open, setOpen] = useState(false)
  const [name, setName] = useState('')
  const [secret, setSecret] = useState<string | null>(null)

  const create = useMutation({
    mutationFn: () => api.createApiKey(name.trim()),
    onSuccess: async (created) => {
      await queryClient.invalidateQueries({ queryKey: apiKeysQueryOptions.queryKey })
      setSecret(created.key)
    },
    onError: (err) => toast.error(err instanceof Error ? err.message : 'Create failed'),
  })

  const del = useMutation({
    mutationFn: (keyId: string) => api.deleteApiKey(keyId),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: apiKeysQueryOptions.queryKey })
      toast.success('API key revoked')
    },
    onError: (err) => toast.error(err instanceof Error ? err.message : 'Revoke failed'),
  })

  function onOpenChange(next: boolean) {
    setOpen(next)
    if (next) {
      setName('')
      setSecret(null)
    }
  }

  return (
    <Card>
      <CardHeader className="flex flex-row items-center justify-between">
        <CardTitle className="text-base">API keys</CardTitle>
        <Dialog open={open} onOpenChange={onOpenChange}>
          <DialogTrigger asChild>
            <Button variant="outline" size="sm">
              New API key
            </Button>
          </DialogTrigger>
          <DialogContent>
            <DialogHeader>
              <DialogTitle>New API key</DialogTitle>
              <DialogDescription>
                A Bearer credential for scripts and CI (send it as{' '}
                <code>Authorization: Bearer &lt;key&gt;</code>).
              </DialogDescription>
            </DialogHeader>
            {secret === null ? (
              <>
                <div className="flex flex-col gap-2">
                  <Label htmlFor="api-key-name">Name</Label>
                  <Input
                    id="api-key-name"
                    value={name}
                    autoComplete="off"
                    placeholder="ci-runner"
                    onChange={(e) => setName(e.target.value)}
                  />
                </div>
                <DialogFooter>
                  <Button variant="outline" onClick={() => setOpen(false)}>
                    Cancel
                  </Button>
                  <Button
                    onClick={() => create.mutate()}
                    disabled={name.trim() === '' || create.isPending}
                  >
                    {create.isPending ? 'Creating…' : 'Create'}
                  </Button>
                </DialogFooter>
              </>
            ) : (
              <>
                <SecretReveal
                  secret={secret}
                  hint="This key is shown only once — store it now. It is kept hashed server-side."
                />
                <DialogFooter>
                  <Button onClick={() => setOpen(false)}>Done</Button>
                </DialogFooter>
              </>
            )}
          </DialogContent>
        </Dialog>
      </CardHeader>
      <CardContent>
        {isPending ? (
          <p className="text-muted-foreground text-sm">Loading…</p>
        ) : isError ? (
          <p className="text-destructive text-sm">
            {error instanceof Error ? error.message : 'Failed to load API keys'}
          </p>
        ) : keys.length === 0 ? (
          <p className="text-muted-foreground text-sm">No API keys.</p>
        ) : (
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Name</TableHead>
                <TableHead>Created</TableHead>
                <TableHead>Last used</TableHead>
                <TableHead className="w-0 text-right">Actions</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {keys.map((key) => (
                <TableRow key={key.id}>
                  <TableCell className="font-medium">{key.name}</TableCell>
                  <TableCell className="text-muted-foreground">
                    {formatDateTime(key.created_at)}
                  </TableCell>
                  <TableCell className="text-muted-foreground">
                    {key.last_used_at ? formatDateTime(key.last_used_at) : 'never'}
                  </TableCell>
                  <TableCell className="text-right">
                    <DeleteKeyAction
                      title={`Revoke ${key.name}?`}
                      description="Callers using this key lose access immediately."
                      onDelete={() => del.mutate(key.id)}
                      pending={del.isPending}
                    />
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        )}
      </CardContent>
    </Card>
  )
}

function downloadText(filename: string, content: string) {
  const url = URL.createObjectURL(new Blob([content], { type: 'text/plain' }))
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  a.click()
  URL.revokeObjectURL(url)
}

/** Register an existing public key (paste an authorized_keys line). */
function RegisterSshKeyDialog() {
  const queryClient = useQueryClient()
  const [open, setOpen] = useState(false)
  const [name, setName] = useState('')
  const [publicKey, setPublicKey] = useState('')

  const create = useMutation({
    mutationFn: () => api.createSshKey(name.trim(), publicKey.trim()),
    onSuccess: async (key) => {
      await queryClient.invalidateQueries({ queryKey: sshKeysQueryOptions.queryKey })
      toast.success(`Registered ${key.name} (${key.fingerprint})`)
      setOpen(false)
    },
    onError: (err) => toast.error(err instanceof Error ? err.message : 'Register failed'),
  })

  function onOpenChange(next: boolean) {
    setOpen(next)
    if (next) {
      setName('')
      setPublicKey('')
    }
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogTrigger asChild>
        <Button variant="outline" size="sm">
          Register key
        </Button>
      </DialogTrigger>
      <DialogContent className="sm:max-w-xl">
        <DialogHeader>
          <DialogTitle>Register SSH public key</DialogTitle>
          <DialogDescription>
            Paste one OpenSSH public-key line (e.g. from <code>~/.ssh/id_ed25519.pub</code>). The
            matching private key stays with you.
          </DialogDescription>
        </DialogHeader>
        <div className="flex flex-col gap-4">
          <div className="flex flex-col gap-2">
            <Label htmlFor="ssh-key-name">Name</Label>
            <Input
              id="ssh-key-name"
              value={name}
              autoComplete="off"
              placeholder="laptop"
              onChange={(e) => setName(e.target.value)}
            />
          </div>
          <div className="flex flex-col gap-2">
            <Label htmlFor="ssh-key-public">Public key</Label>
            <Textarea
              id="ssh-key-public"
              className="min-h-24 font-mono text-xs"
              placeholder="ssh-ed25519 AAAA… user@host"
              value={publicKey}
              onChange={(e) => setPublicKey(e.target.value)}
              spellCheck={false}
            />
          </div>
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={() => setOpen(false)}>
            Cancel
          </Button>
          <Button
            onClick={() => create.mutate()}
            disabled={name.trim() === '' || publicKey.trim() === '' || create.isPending}
          >
            {create.isPending ? 'Registering…' : 'Register'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

/** Server-side keypair generation: the public half is registered, the private
 * half is returned exactly once (copy or download it here, never again). */
function GenerateSshKeyDialog() {
  const queryClient = useQueryClient()
  const [open, setOpen] = useState(false)
  const [name, setName] = useState('')
  const [privateKey, setPrivateKey] = useState<string | null>(null)

  const generate = useMutation({
    mutationFn: () => api.generateSshKey(name.trim()),
    onSuccess: async (generated) => {
      await queryClient.invalidateQueries({ queryKey: sshKeysQueryOptions.queryKey })
      setPrivateKey(generated.private_key)
    },
    onError: (err) => toast.error(err instanceof Error ? err.message : 'Generate failed'),
  })

  function onOpenChange(next: boolean) {
    setOpen(next)
    if (next) {
      setName('')
      setPrivateKey(null)
    }
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogTrigger asChild>
        <Button variant="outline" size="sm">
          Generate key
        </Button>
      </DialogTrigger>
      <DialogContent className="sm:max-w-xl">
        <DialogHeader>
          <DialogTitle>Generate SSH key</DialogTitle>
          <DialogDescription>
            Generates an ed25519 keypair server-side and registers the public half. The private key
            is returned only here and never stored.
          </DialogDescription>
        </DialogHeader>
        {privateKey === null ? (
          <>
            <div className="flex flex-col gap-2">
              <Label htmlFor="ssh-gen-name">Name</Label>
              <Input
                id="ssh-gen-name"
                value={name}
                autoComplete="off"
                placeholder="laptop"
                onChange={(e) => setName(e.target.value)}
              />
            </div>
            <DialogFooter>
              <Button variant="outline" onClick={() => setOpen(false)}>
                Cancel
              </Button>
              <Button
                onClick={() => generate.mutate()}
                disabled={name.trim() === '' || generate.isPending}
              >
                {generate.isPending ? 'Generating…' : 'Generate'}
              </Button>
            </DialogFooter>
          </>
        ) : (
          <>
            <SecretReveal
              secret={privateKey}
              hint="This private key is shown only once — save it now (chmod 600)."
            />
            <DialogFooter>
              <Button
                variant="outline"
                onClick={() => downloadText(`${name.trim() || 'twinlab'}.key`, privateKey)}
              >
                <Download className="size-4" />
                Download
              </Button>
              <Button onClick={() => setOpen(false)}>Done</Button>
            </DialogFooter>
          </>
        )}
      </DialogContent>
    </Dialog>
  )
}

function SshKeysCard() {
  const queryClient = useQueryClient()
  const { data: keys, isPending, isError, error } = useQuery(sshKeysQueryOptions)
  const { data: access } = useQuery(sshAccessQueryOptions)

  const del = useMutation({
    mutationFn: (keyId: string) => api.deleteSshKey(keyId),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: sshKeysQueryOptions.queryKey })
      toast.success('SSH key deleted')
    },
    onError: (err) => toast.error(err instanceof Error ? err.message : 'Delete failed'),
  })

  return (
    <Card>
      <CardHeader className="flex flex-row items-center justify-between">
        <CardTitle className="text-base">SSH keys</CardTitle>
        <div className="flex items-center gap-2">
          <RegisterSshKeyDialog />
          <GenerateSshKeyDialog />
        </div>
      </CardHeader>
      <CardContent className="flex flex-col gap-4">
        {(() => {
          // The recipe must route the identity through the hop: a bare
          // `ssh -i key -J jump@host ip` FAILS (-i never reaches the -J hop),
          // so we teach the ssh_config block + alias form instead.
          const jump = jumpCoordinates(access)
          return jump ? (
            <div className="flex flex-col gap-2">
              <p className="text-sm text-muted-foreground">
                Registered keys open SSH access to your labs&apos; nodes through the jump host. Add
                this once to <code className="font-mono text-xs">~/.ssh/config</code> (point{' '}
                <code className="font-mono text-xs">IdentityFile</code> at your key), then{' '}
                <code className="font-mono text-xs">
                  ssh -J {JUMP_HOST_ALIAS} &lt;node-user&gt;@&lt;node-ip&gt;
                </code>
                :
              </p>
              <div className="flex items-start gap-2">
                <pre className="flex-1 overflow-x-auto rounded-md bg-muted p-3 font-mono text-xs">
                  {sshConfigBlock(jump)}
                </pre>
                <CopyButton value={sshConfigBlock(jump)} label="config block" />
              </div>
            </div>
          ) : (
            <p className="text-sm text-muted-foreground">
              This deployment does not advertise a jump host.
            </p>
          )
        })()}

        {isPending ? (
          <p className="text-muted-foreground text-sm">Loading…</p>
        ) : isError ? (
          <p className="text-destructive text-sm">
            {error instanceof Error ? error.message : 'Failed to load SSH keys'}
          </p>
        ) : keys.length === 0 ? (
          <p className="text-muted-foreground text-sm">No SSH keys.</p>
        ) : (
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Name</TableHead>
                <TableHead>Algorithm</TableHead>
                <TableHead>Fingerprint</TableHead>
                <TableHead>Last offered</TableHead>
                <TableHead className="w-0 text-right">Actions</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {keys.map((key) => (
                <TableRow key={key.id}>
                  <TableCell className="font-medium">{key.name}</TableCell>
                  <TableCell className="font-mono text-xs">{key.algorithm}</TableCell>
                  <TableCell>
                    <div className="flex items-center gap-1">
                      <span className="font-mono text-xs">{key.fingerprint}</span>
                      <CopyButton value={key.fingerprint} label="fingerprint" />
                    </div>
                  </TableCell>
                  <TableCell className="text-muted-foreground">
                    {key.last_used_at ? formatDateTime(key.last_used_at) : 'never'}
                  </TableCell>
                  <TableCell className="text-right">
                    <DeleteKeyAction
                      title={`Delete ${key.name}?`}
                      description="New jump connections with this key are refused immediately; established sessions survive until they close."
                      onDelete={() => del.mutate(key.id)}
                      pending={del.isPending}
                    />
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        )}
      </CardContent>
    </Card>
  )
}

/** Self-service credentials: API keys (Bearer) and SSH keys for the jump host.
 * No permission gate — every authenticated user manages their own. */
export function AccountPage() {
  useDocumentTitle('Account')
  return (
    <div className="flex flex-col gap-6">
      <h1 className="font-heading text-2xl font-semibold">Account</h1>
      <ApiKeysCard />
      <SshKeysCard />
    </div>
  )
}

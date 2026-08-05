import { useState } from 'react'
import { toast } from 'sonner'

import { IdentitySwitcher, ThemeToggle } from '@/components/identity-switcher'
import { LabStatusBadge } from '@/components/lab/status-badge'
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
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from '@/components/ui/card'
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
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
  SheetTrigger,
} from '@/components/ui/sheet'
import { Skeleton } from '@/components/ui/skeleton'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { Textarea } from '@/components/ui/textarea'
import { Wordmark } from '@/components/wordmark'
import { ApiError } from '@/lib/api'
import { toastError } from '@/lib/error-toast'
import { jobStatusBadgeVariant } from '@/lib/format'
import { IDENTITY_LABELS, useIdentity } from '@/lib/identity'
import { useDocumentTitle } from '@/lib/use-document-title'

const COLOR_TOKENS = [
  'background',
  'foreground',
  'card',
  'primary',
  'secondary',
  'muted',
  'accent',
  'destructive',
  'border',
] as const

const LAB_STATUSES = ['created', 'deploying', 'deployed', 'destroyed'] as const
const JOB_STATUSES = ['running', 'succeeded', 'failed'] as const

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="flex flex-col gap-3">
      <h2 className="font-heading border-b pb-1 text-lg font-semibold">{title}</h2>
      {children}
    </section>
  )
}

/** Dev-only gallery: every primitive rendered under the active identity pack,
 * so the three bake-off candidates can be compared like-for-like. */
export function StyleguidePage() {
  useDocumentTitle('Styleguide')
  const { identity } = useIdentity()
  const [checked, setChecked] = useState(true)

  if (!import.meta.env.DEV) {
    return <p className="text-muted-foreground text-sm">The styleguide is a dev-only surface.</p>
  }

  return (
    <div className="flex flex-col gap-10">
      <div className="flex items-end justify-between">
        <div>
          <h1 className="font-heading text-2xl font-semibold">Styleguide</h1>
          <p className="text-muted-foreground text-sm">
            Identity under review: <span className="font-mono">{IDENTITY_LABELS[identity]}</span> —
            switch pack and theme from the header.
          </p>
        </div>
        <div className="flex items-center gap-1">
          <IdentitySwitcher />
          <ThemeToggle />
        </div>
      </div>

      <Section title="Wordmark">
        <div className="flex items-center gap-8 border bg-card/60 p-6">
          <Wordmark />
          <Wordmark className="scale-150 origin-left" />
        </div>
      </Section>

      <Section title="Color tokens">
        <div className="grid grid-cols-3 gap-2 sm:grid-cols-5">
          {COLOR_TOKENS.map((token) => (
            <div key={token} className="flex flex-col gap-1">
              <div
                className="h-12 border"
                style={{ backgroundColor: `var(--${token})` }}
              />
              <span className="font-mono text-[0.65rem] text-muted-foreground">--{token}</span>
            </div>
          ))}
        </div>
      </Section>

      <Section title="Typography">
        <div className="flex flex-col gap-2">
          <p className="font-heading text-3xl font-semibold">Heading — network twin laboratory</p>
          <p className="font-heading text-xl font-semibold">Subheading — deploy, impair, validate</p>
          <p className="max-w-prose text-sm">
            Body — Twinlab generates reproducible simulated network topologies from a declarative
            definition. The same definition must always produce the same environment.
          </p>
          <p className="font-mono text-sm">
            mono — ssh -J twinlab-jump vyos@10.77.4.101 · 3/4 nodes · SHA256:kX92…
          </p>
        </div>
      </Section>

      <Section title="Buttons">
        <div className="flex flex-wrap items-center gap-2">
          <Button>Deploy</Button>
          <Button variant="secondary">Configure</Button>
          <Button variant="outline">Cancel</Button>
          <Button variant="ghost">Ghost</Button>
          <Button variant="destructive">Destroy</Button>
          <Button variant="link">Link</Button>
          <Button disabled>Deploying…</Button>
          <Button size="sm" variant="outline">
            Small
          </Button>
        </div>
      </Section>

      <Section title="Badges & statuses">
        <div className="flex flex-wrap items-center gap-2">
          <Badge>default</Badge>
          <Badge variant="secondary">secondary</Badge>
          <Badge variant="outline">outline</Badge>
          <Badge variant="destructive">destructive</Badge>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          {LAB_STATUSES.map((status) => (
            <LabStatusBadge key={status} status={status} />
          ))}
        </div>
        <div className="flex flex-wrap items-center gap-2">
          {JOB_STATUSES.map((status) => (
            <Badge key={status} variant={jobStatusBadgeVariant(status)}>
              {status}
            </Badge>
          ))}
        </div>
      </Section>

      <Section title="Forms">
        <div className="grid max-w-2xl gap-4 sm:grid-cols-2">
          <div className="flex flex-col gap-2">
            <Label htmlFor="sg-name">Lab name</Label>
            <Input id="sg-name" className="font-mono" placeholder="mpls-l3vpn" />
          </div>
          <div className="flex flex-col gap-2">
            <Label htmlFor="sg-password">Password</Label>
            <PasswordInput id="sg-password" defaultValue="hunter2-but-longer" />
          </div>
          <div className="flex flex-col gap-2">
            <Label>Device</Label>
            <Select defaultValue="vyos">
              <SelectTrigger>
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="vyos">vyos</SelectItem>
                <SelectItem value="frr">frr</SelectItem>
                <SelectItem value="linux">linux</SelectItem>
              </SelectContent>
            </Select>
          </div>
          <div className="flex flex-col gap-2 sm:col-span-2">
            <Label htmlFor="sg-def">Definition</Label>
            <Textarea
              id="sg-def"
              className="font-mono text-sm"
              rows={3}
              defaultValue={'provider: clab\nnodes: [pe1, p1]\nlinks: [pe1-p1]'}
            />
          </div>
          <label className="flex items-center gap-2 text-sm">
            <Checkbox checked={checked} onCheckedChange={(v) => setChecked(v === true)} />
            Push initial configuration
          </label>
        </div>
      </Section>

      <Section title="Table">
        <div className="border bg-card/60">
          <Table>
            <TableHeader>
              <TableRow className="hover:bg-transparent">
                <TableHead>Name</TableHead>
                <TableHead>Status</TableHead>
                <TableHead>Nodes</TableHead>
                <TableHead>Mgmt IP</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              <TableRow>
                <TableCell className="font-mono text-sm font-medium">mpls-l3vpn</TableCell>
                <TableCell>
                  <LabStatusBadge status="deployed" />
                </TableCell>
                <TableCell className="font-mono text-sm">
                  <span className="text-primary">4</span>
                  <span className="text-muted-foreground">/4</span>
                </TableCell>
                <TableCell className="font-mono text-xs">10.77.4.0/24</TableCell>
              </TableRow>
              <TableRow>
                <TableCell className="font-mono text-sm font-medium">edge-scenarios</TableCell>
                <TableCell>
                  <LabStatusBadge status="deploying" />
                </TableCell>
                <TableCell className="font-mono text-sm">
                  <span className="text-primary">1</span>
                  <span className="text-muted-foreground">/3</span>
                </TableCell>
                <TableCell className="font-mono text-xs">10.77.5.0/24</TableCell>
              </TableRow>
              <TableRow>
                <TableCell className="font-mono text-sm font-medium">bgp-anycast</TableCell>
                <TableCell>
                  <LabStatusBadge status="created" />
                </TableCell>
                <TableCell className="font-mono text-sm">
                  <span className="text-muted-foreground">0/0</span>
                </TableCell>
                <TableCell className="font-mono text-xs text-muted-foreground">—</TableCell>
              </TableRow>
            </TableBody>
          </Table>
        </div>
      </Section>

      <Section title="Overlays & feedback">
        <div className="flex flex-wrap items-center gap-2">
          <Dialog>
            <DialogTrigger asChild>
              <Button variant="outline">Open dialog</Button>
            </DialogTrigger>
            <DialogContent className="sm:max-w-md">
              <DialogHeader>
                <DialogTitle className="font-heading">Deploy mpls-l3vpn</DialogTitle>
                <DialogDescription>
                  Deploys the stored definition through clab-api. Long operations run as jobs.
                </DialogDescription>
              </DialogHeader>
              <DialogFooter>
                <DialogClose asChild>
                  <Button variant="outline">Cancel</Button>
                </DialogClose>
                <Button>Deploy</Button>
              </DialogFooter>
            </DialogContent>
          </Dialog>
          <AlertDialog>
            <AlertDialogTrigger asChild>
              <Button variant="destructive">Open confirm</Button>
            </AlertDialogTrigger>
            <AlertDialogContent>
              <AlertDialogHeader>
                <AlertDialogTitle>Destroy mpls-l3vpn?</AlertDialogTitle>
                <AlertDialogDescription>
                  Tears down the running nodes. The record and definition survive for redeploy.
                </AlertDialogDescription>
              </AlertDialogHeader>
              <AlertDialogFooter>
                <AlertDialogCancel>Cancel</AlertDialogCancel>
                <AlertDialogAction>Destroy</AlertDialogAction>
              </AlertDialogFooter>
            </AlertDialogContent>
          </AlertDialog>
          <Sheet>
            <SheetTrigger asChild>
              <Button variant="outline">Open sheet</Button>
            </SheetTrigger>
            <SheetContent>
              <SheetHeader>
                <SheetTitle>Connect — pe1</SheetTitle>
                <SheetDescription>Slide-over drawer for per-node detail surfaces.</SheetDescription>
              </SheetHeader>
              <div className="px-4">
                <Tabs defaultValue="config">
                  <TabsList>
                    <TabsTrigger value="config">ssh_config</TabsTrigger>
                    <TabsTrigger value="proxy">ProxyCommand</TabsTrigger>
                  </TabsList>
                  <TabsContent value="config">
                    <pre className="overflow-x-auto rounded-md bg-muted p-3 font-mono text-xs">
                      {'Host twinlab-jump\n  HostName lab.example\n  Port 2222\n  User jump'}
                    </pre>
                  </TabsContent>
                  <TabsContent value="proxy">
                    <pre className="overflow-x-auto rounded-md bg-muted p-3 font-mono text-xs">
                      ssh -o ProxyCommand=&apos;…&apos; admin@10.77.4.101
                    </pre>
                  </TabsContent>
                </Tabs>
              </div>
            </SheetContent>
          </Sheet>
          <Button variant="outline" onClick={() => toast.success('Deploy succeeded — 4/4 nodes up')}>
            Success toast
          </Button>
          <Button
            variant="outline"
            onClick={() =>
              // The real error path: message + Copy action carrying the wire
              // facts (status/code/extras) for a paste-able report.
              toastError(
                new ApiError(409, 'another operation is running on this lab', 'job_in_flight', {
                  job_id: '0198f2ab-demo',
                  kind: 'deploy',
                }),
                'Operation failed',
              )
            }
          >
            Error toast
          </Button>
        </div>
      </Section>

      <Section title="Card & skeleton">
        <div className="grid max-w-2xl gap-4 sm:grid-cols-2">
          <Card>
            <CardHeader>
              <CardTitle className="font-heading">Operations</CardTitle>
              <CardDescription>Recent jobs on this lab.</CardDescription>
            </CardHeader>
            <CardContent className="flex flex-col gap-2">
              <div className="flex items-center justify-between font-mono text-xs">
                <span>deploy</span>
                <Badge variant={jobStatusBadgeVariant('succeeded')}>succeeded</Badge>
              </div>
              <div className="flex items-center justify-between font-mono text-xs">
                <span>configure</span>
                <Badge variant={jobStatusBadgeVariant('running')}>running</Badge>
              </div>
            </CardContent>
          </Card>
          <div className="flex flex-col gap-2">
            <Skeleton className="h-6 w-full" />
            <Skeleton className="h-6 w-4/5" />
            <Skeleton className="h-6 w-3/5" />
          </div>
        </div>
      </Section>
    </div>
  )
}

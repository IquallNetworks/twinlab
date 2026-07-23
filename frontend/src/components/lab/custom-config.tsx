import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { ChevronDown, ChevronRight } from 'lucide-react'
import { useState } from 'react'
import { toast } from 'sonner'

import { Badge } from '@/components/ui/badge'
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
import { Textarea } from '@/components/ui/textarea'
import { api } from '@/lib/api'
import { customConfigQueryOptions } from '@/lib/queries'
import type { BuiltinTemplate } from '@/lib/schemas'

/** An expandable entry showing a template's source files. Built-in entries carry
 * a description and a read-only badge; user entries are a single file each. */
function TemplateRow({
  title,
  description,
  files,
  builtin,
}: {
  title: string
  description?: string
  files: Record<string, string>
  builtin: boolean
}) {
  const [open, setOpen] = useState(false)
  return (
    <div className="rounded-md border p-3">
      <div className="flex flex-wrap items-center gap-2">
        <button
          type="button"
          className="text-muted-foreground hover:text-foreground"
          onClick={() => setOpen((v) => !v)}
          aria-label={open ? 'Collapse' : 'Expand'}
        >
          {open ? <ChevronDown className="size-4" /> : <ChevronRight className="size-4" />}
        </button>
        <span className="font-mono text-sm">{title}</span>
        <Badge variant={builtin ? 'default' : 'secondary'}>{builtin ? 'built-in' : 'user'}</Badge>
      </div>
      {description !== undefined && description !== '' && (
        <p className="text-muted-foreground mt-2 text-sm">{description}</p>
      )}
      {open && (
        <div className="mt-3 flex flex-col gap-3">
          {Object.entries(files).map(([path, content]) => (
            <div key={path}>
              <p className="text-muted-foreground mb-1 font-mono text-xs">{path}</p>
              <pre className="bg-muted overflow-x-auto rounded-md p-3 font-mono text-xs">
                {content}
              </pre>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

/** Author the user template fileset as JSON ({ "relpath.j2": "source" }). Parsed
 * here for syntax; the backend validates paths and rejects built-in collisions. */
function TemplatesEditor({ name, filesetJson }: { name: string; filesetJson: string }) {
  const queryClient = useQueryClient()
  const [open, setOpen] = useState(false)
  const [text, setText] = useState(filesetJson)

  const save = useMutation({
    mutationFn: (parsed: unknown) => api.putCustomConfig(name, parsed),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: customConfigQueryOptions(name).queryKey })
      toast.success('Saved custom config')
      setOpen(false)
    },
    onError: (err) => toast.error(err instanceof Error ? err.message : 'Failed to save templates'),
  })

  function onSave() {
    let parsed: unknown
    try {
      parsed = JSON.parse(text)
    } catch (e) {
      toast.error(e instanceof Error ? `Invalid JSON: ${e.message}` : 'Invalid JSON')
      return
    }
    save.mutate(parsed)
  }

  return (
    <Dialog
      open={open}
      onOpenChange={(next) => {
        setOpen(next)
        if (next) setText(filesetJson) // reset to the current fileset on open
      }}
    >
      <DialogTrigger asChild>
        <Button variant="outline" size="sm">
          Edit templates
        </Button>
      </DialogTrigger>
      <DialogContent className="flex flex-col sm:max-w-2xl">
        <DialogHeader>
          <DialogTitle>Edit custom-config templates</DialogTitle>
          <DialogDescription>
            A JSON map of template path → Jinja source, e.g.{' '}
            {'{ "nat/ios.j2": "ip nat ..." }'}. Reference a template by name from a node/group{' '}
            <span className="font-mono">config:</span> attribute in the definition. A path may not
            shadow a built-in.
          </DialogDescription>
        </DialogHeader>
        <Textarea
          className="min-h-48 flex-1 resize-none font-mono text-xs"
          value={text}
          onChange={(e) => setText(e.target.value)}
          spellCheck={false}
        />
        <DialogFooter>
          <Button variant="outline" onClick={() => setOpen(false)}>
            Cancel
          </Button>
          <Button onClick={onSave} disabled={save.isPending}>
            {save.isPending ? 'Saving…' : 'Save'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

/** Custom config: the seam for device config netlab doesn't model (MPLS-TE, IP
 * SLA, QoS, …). Built-in templates ship with Twinlab (read-only); user templates
 * are per-lab. Everyone with lab:read sees them; lab:create authors the user set.
 * They apply on the next configure/redeploy when referenced from `config:`. */
export function CustomConfig({ name, canEdit }: { name: string; canEdit: boolean }) {
  const { data, isPending, isError, error } = useQuery(customConfigQueryOptions(name))

  const userEntries = data ? Object.entries(data.custom_config) : []
  const filesetJson = data ? JSON.stringify(data.custom_config, null, 2) : '{}'
  const byName = (a: BuiltinTemplate, b: BuiltinTemplate) => a.name.localeCompare(b.name)

  return (
    <Card>
      <CardHeader className="flex flex-row items-center justify-between">
        <CardTitle className="text-base">Custom config</CardTitle>
        {canEdit && data && <TemplatesEditor name={name} filesetJson={filesetJson} />}
      </CardHeader>
      <CardContent className="flex flex-col gap-3">
        {isPending ? (
          <p className="text-muted-foreground text-sm">Loading…</p>
        ) : isError ? (
          <p className="text-destructive text-sm">
            {error instanceof Error ? error.message : 'Failed to load custom config'}
          </p>
        ) : (
          <>
            {[...data.builtin].sort(byName).map((t) => (
              <TemplateRow
                key={t.name}
                title={t.name}
                description={t.description}
                files={t.files}
                builtin
              />
            ))}
            {userEntries.length === 0 ? (
              <p className="text-muted-foreground text-sm">
                No user templates{canEdit ? ' — add some with “Edit templates”.' : '.'}
              </p>
            ) : (
              userEntries.map(([path, content]) => (
                <TemplateRow key={path} title={path} files={{ [path]: content }} builtin={false} />
              ))
            )}
          </>
        )}
      </CardContent>
    </Card>
  )
}

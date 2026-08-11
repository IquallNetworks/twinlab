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
import { CodeEditor } from '@/components/code-editor'
import { api } from '@/lib/api'
import { toastError } from '@/lib/error-toast'
import { customConfigQueryOptions } from '@/lib/queries'
import type { ConfigTemplate, TemplateVariant } from '@/lib/schemas'

/** The scope a variant declares (delta 27): a node, a device, or universal.
 * netlab's lookup precedence — node beats device beats universal — falls out
 * of the filenames the backend materializes, so the label is documentation. */
function variantScope(variant: TemplateVariant): string {
  if (variant.node != null) return `node: ${variant.node}`
  if (variant.device != null) return `device: ${variant.device}`
  return 'universal'
}

/** An expandable entry showing a template record: its tier, description, and
 * each scoped variant's Jinja source. */
function TemplateRow({ template }: { template: ConfigTemplate }) {
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
        <span className="font-mono text-sm">{template.name}</span>
        <Badge variant={template.tier === 'builtin' ? 'default' : 'secondary'}>
          {template.tier === 'builtin' ? 'built-in' : 'user'}
        </Badge>
      </div>
      {template.description !== '' && (
        <p className="text-muted-foreground mt-2 text-sm">{template.description}</p>
      )}
      {open && (
        <div className="mt-3 flex flex-col gap-3">
          {template.variants.map((variant) => (
            <div key={variantScope(variant)}>
              <p className="text-muted-foreground mb-1 font-mono text-xs">
                {variantScope(variant)}
              </p>
              <CodeEditor value={variant.source} language="jinja2" className="max-h-64" />
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

/** Author the user template records as JSON — a list of {name, description,
 * variants: [{source, device? | node?}]}. Parsed here for syntax; the backend
 * validates shapes (one scope per variant, catalog devices, unique names) and
 * rejects built-in name collisions. */
function TemplatesEditor({ name, templatesJson }: { name: string; templatesJson: string }) {
  const queryClient = useQueryClient()
  const [open, setOpen] = useState(false)
  const [text, setText] = useState(templatesJson)

  const save = useMutation({
    mutationFn: (parsed: unknown) => api.putCustomConfig(name, parsed),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: customConfigQueryOptions(name).queryKey })
      toast.success('Saved custom config')
      setOpen(false)
    },
    onError: (err) => toastError(err, 'Failed to save templates'),
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
        if (next) setText(templatesJson) // reset to the current records on open
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
            A JSON list of template records, e.g.{' '}
            {'[{ "name": "nat", "description": "", "variants": [{ "source": "...", "device": "vyos" }] }]'}
            . A variant applies to one <span className="font-mono">node</span>, one{' '}
            <span className="font-mono">device</span>, or (with neither key) everywhere. Reference
            a template by name from a node/group <span className="font-mono">config:</span>{' '}
            attribute; a name may not shadow a built-in.
          </DialogDescription>
        </DialogHeader>
        <CodeEditor
          value={text}
          onChange={setText}
          language="json"
          lint
          className="min-h-48 max-h-[60vh] flex-1"
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
 * SLA, QoS, …). Built-in templates ship with Twinlab (read-only); user records
 * are per-lab. Everyone with lab:read sees them; lab:edit authors the user
 * tier. They apply on the next configure/redeploy when referenced from
 * `config:` — and only on nodes a variant matches. */
export function CustomConfig({ name, canEdit }: { name: string; canEdit: boolean }) {
  const { data, isPending, isError, error } = useQuery(customConfigQueryOptions(name))

  const user = data ? data.templates.filter((t) => t.tier === 'user') : []
  const templatesJson = JSON.stringify(
    user.map(({ tier: _tier, ...spec }) => ({
      ...spec,
      variants: spec.variants.map((v) => ({
        source: v.source,
        ...(v.device != null ? { device: v.device } : {}),
        ...(v.node != null ? { node: v.node } : {}),
      })),
    })),
    null,
    2,
  )

  return (
    <Card>
      <CardHeader className="flex flex-row items-center justify-between">
        <CardTitle className="text-base">Custom config</CardTitle>
        {canEdit && data && <TemplatesEditor name={name} templatesJson={templatesJson} />}
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
            {data.templates
              .filter((t) => t.tier === 'builtin')
              .map((t) => (
                <TemplateRow key={t.name} template={t} />
              ))}
            {user.length === 0 ? (
              <p className="text-muted-foreground text-sm">
                No user templates{canEdit ? ' — add some with “Edit templates”.' : '.'}
              </p>
            ) : (
              user.map((t) => <TemplateRow key={t.name} template={t} />)
            )}
          </>
        )}
      </CardContent>
    </Card>
  )
}

/** Import a lab from dumped running configs (contract delta 22).
 *
 * A two-step wizard over the pure definition factory: gather one config per
 * node (upload or paste, device chosen per file), analyze via POST
 * /import/network, then REVIEW — the inferred definition, per-node carry and
 * quarantine, the interface/name maps, every warning — before any lab
 * exists. Create composes the normal lifecycle: createLab ->
 * putCustomConfig -> updateLabDefinition (custom config FIRST: the
 * definition PUT validates its config: references against the stored
 * fileset), then lands on the Build tab.
 */
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useNavigate } from '@tanstack/react-router'
import { ArrowLeft, FileUp, Plus, Trash2, TriangleAlert } from 'lucide-react'
import { useRef, useState } from 'react'
import { toast } from 'sonner'

import { CodeEditor } from '@/components/code-editor'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { Textarea } from '@/components/ui/textarea'
import { api, type ImportSourceInput } from '@/lib/api'
import { toastError } from '@/lib/error-toast'
import { deviceCatalogQueryOptions } from '@/lib/queries'
import type { NetworkImport, QuarantineClass } from '@/lib/schemas'
import { useDocumentTitle } from '@/lib/use-document-title'

interface SourceDraft {
  id: number
  device: string
  name: string // optional override; '' = use the config's hostname
  content: string
  filename: string | null
}

const QUARANTINE_LABELS: Record<QuarantineClass, string> = {
  mgmt: 'management',
  auth: 'authentication',
  telemetry: 'telemetry',
  hardware: 'hardware',
}

let nextId = 1

function SourceRow({
  draft,
  devices,
  onChange,
  onRemove,
  removable,
}: {
  draft: SourceDraft
  devices: { device: string; label: string }[]
  onChange: (next: SourceDraft) => void
  onRemove: () => void
  removable: boolean
}) {
  const fileRef = useRef<HTMLInputElement>(null)
  const loadFile = (file: File | undefined) => {
    if (!file) return
    file
      .text()
      .then((text) => onChange({ ...draft, content: text, filename: file.name }))
      .catch(() => toast.error(`Could not read ${file.name}`))
  }
  return (
    <div className="flex flex-col gap-3 border p-4">
      <div className="flex flex-wrap items-end gap-3">
        <div className="flex flex-col gap-1.5">
          <Label htmlFor={`device-${draft.id}`}>Device</Label>
          <Select
            value={draft.device}
            onValueChange={(device) => onChange({ ...draft, device })}
          >
            <SelectTrigger id={`device-${draft.id}`} className="w-40">
              <SelectValue placeholder="Device" />
            </SelectTrigger>
            <SelectContent>
              {devices.map((d) => (
                <SelectItem key={d.device} value={d.device}>
                  {d.label}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
        <div className="flex flex-col gap-1.5">
          <Label htmlFor={`name-${draft.id}`}>Node name (optional)</Label>
          <Input
            id={`name-${draft.id}`}
            className="w-44 font-mono"
            placeholder="from hostname"
            value={draft.name}
            onChange={(e) => onChange({ ...draft, name: e.target.value })}
          />
        </div>
        <input
          ref={fileRef}
          type="file"
          className="hidden"
          onChange={(e) => loadFile(e.target.files?.[0])}
        />
        <Button type="button" variant="outline" size="sm" onClick={() => fileRef.current?.click()}>
          <FileUp className="size-3.5" />
          {draft.filename ?? 'Load file'}
        </Button>
        {removable && (
          <Button
            type="button"
            variant="ghost"
            size="icon-sm"
            className="ml-auto"
            aria-label="Remove source"
            onClick={onRemove}
          >
            <Trash2 className="size-3.5" />
          </Button>
        )}
      </div>
      <Textarea
        value={draft.content}
        onChange={(e) => onChange({ ...draft, content: e.target.value, filename: null })}
        placeholder="Paste the node's running config here (or load a file above)"
        className="min-h-28 font-mono text-xs"
        aria-label="Source config"
      />
    </div>
  )
}

function ReviewNodeCard({ node, result }: { node: string; result: NetworkImport }) {
  const carry = result.custom_config[`imported/${node}.j2`]
  const quarantine = result.quarantine[node] ?? []
  const mapping = result.interface_map[node] ?? {}
  const [showCarry, setShowCarry] = useState(false)
  return (
    <Card>
      <CardHeader>
        <CardTitle className="font-mono text-sm">{node}</CardTitle>
      </CardHeader>
      <CardContent className="flex flex-col gap-3 text-sm">
        {Object.keys(mapping).length > 0 && (
          <div>
            <p className="mb-1 text-xs tracking-wide text-muted-foreground uppercase">
              Interface map
            </p>
            <div className="flex flex-wrap gap-2 font-mono text-xs">
              {Object.entries(mapping).map(([source, target]) => (
                <span key={source} className="border px-1.5 py-0.5">
                  {source} → {target}
                </span>
              ))}
            </div>
          </div>
        )}
        {carry !== undefined && (
          <div>
            <button
              type="button"
              className="text-xs underline hover:text-primary"
              onClick={() => setShowCarry((v) => !v)}
            >
              {showCarry ? 'Hide carried config' : 'Show carried config'}
            </button>
            {showCarry && (
              <pre className="mt-2 max-h-56 overflow-auto border bg-muted/30 p-2 font-mono text-xs">
                {carry}
              </pre>
            )}
          </div>
        )}
        {quarantine.length > 0 && (
          <div className="flex flex-col gap-2">
            <p className="text-xs tracking-wide text-muted-foreground uppercase">
              Quarantined (kept, not applied — attach from Custom config later)
            </p>
            {quarantine.map((entry, index) => (
              <div key={index} className="border border-dashed p-2">
                <Badge variant="outline" className="mb-1">
                  {QUARANTINE_LABELS[entry.reason]}
                </Badge>
                <pre className="overflow-auto font-mono text-xs">{entry.content}</pre>
              </div>
            ))}
          </div>
        )}
      </CardContent>
    </Card>
  )
}

export function LabImportPage() {
  useDocumentTitle('Import lab')
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const { data: catalog } = useQuery(deviceCatalogQueryOptions)
  const importable = (catalog?.devices ?? []).filter((d) => d.config_import)

  const [sources, setSources] = useState<SourceDraft[]>([
    { id: nextId++, device: '', name: '', content: '', filename: null },
  ])
  const [result, setResult] = useState<NetworkImport | null>(null)
  const [labName, setLabName] = useState('')

  const analyze = useMutation({
    mutationFn: (inputs: ImportSourceInput[]) => api.importNetwork(inputs),
    onSuccess: setResult,
    onError: (err) => toastError(err, 'Import failed'),
  })

  const create = useMutation({
    mutationFn: async () => {
      if (result === null) throw new Error('nothing analyzed yet')
      const lab = await api.createLab(labName)
      // Custom config FIRST: the definition references the carry templates,
      // and the PUT's dry netlab create validates them against the STORED
      // fileset. A failure past this point leaves a partial record — say so.
      try {
        await api.putCustomConfig(lab.name, result.custom_config)
        await api.updateLabDefinition(lab.name, result.definition)
      } catch (err) {
        toastError(err, `Authoring ${lab.name} failed — the record exists, finish it manually`)
        return lab.name
      }
      toast.success(`Imported into ${lab.name}`)
      return lab.name
    },
    onSuccess: async (name) => {
      await queryClient.invalidateQueries({ queryKey: ['labs'] })
      await navigate({ to: '/labs/$name/build', params: { name } })
    },
    onError: (err) => toastError(err, 'Creating the lab failed'),
  })

  const ready = sources.every((s) => s.device !== '' && s.content.trim() !== '')
  const renames = Object.entries(result?.name_map ?? {}).filter(([from, to]) => from !== to)
  // Every imported node, whether or not it has mapped interfaces/quarantine.
  const nodes =
    result === null
      ? []
      : Array.from(
          new Set([
            ...Object.values(result.name_map),
            ...Object.keys(result.interface_map),
            ...Object.keys(result.quarantine),
          ]),
        )

  return (
    <div className="mx-auto flex max-w-4xl flex-col gap-6">
      <div className="flex items-center gap-3">
        <Button
          type="button"
          variant="ghost"
          size="icon-sm"
          aria-label="Back to labs"
          onClick={() => void navigate({ to: '/labs' })}
        >
          <ArrowLeft className="size-4" />
        </Button>
        <div>
          <h1 className="font-heading text-2xl font-semibold">Import from config files</h1>
          <p className="text-sm text-muted-foreground">
            One dumped running config per node. Links are inferred from shared subnets — the
            logical topology; nothing in a config is dropped: it is modeled, carried, or
            quarantined.
          </p>
        </div>
      </div>

      {result === null ? (
        <>
          <div className="flex flex-col gap-3">
            {sources.map((draft) => (
              <SourceRow
                key={draft.id}
                draft={draft}
                devices={importable}
                onChange={(next) =>
                  setSources((prev) => prev.map((s) => (s.id === next.id ? next : s)))
                }
                onRemove={() => setSources((prev) => prev.filter((s) => s.id !== draft.id))}
                removable={sources.length > 1}
              />
            ))}
          </div>
          <div className="flex gap-3">
            <Button
              type="button"
              variant="outline"
              onClick={() =>
                setSources((prev) => [
                  ...prev,
                  { id: nextId++, device: prev.at(-1)?.device ?? '', name: '', content: '', filename: null },
                ])
              }
            >
              <Plus className="size-3.5" />
              Add source
            </Button>
            <Button
              type="button"
              disabled={!ready || analyze.isPending}
              onClick={() =>
                analyze.mutate(
                  sources.map((s) => ({
                    device: s.device,
                    content: s.content,
                    ...(s.name.trim() !== '' ? { name: s.name.trim() } : {}),
                  })),
                )
              }
            >
              {analyze.isPending ? 'Analyzing…' : 'Analyze'}
            </Button>
          </div>
        </>
      ) : (
        <>
          {result.warnings.length > 0 && (
            <div className="border border-primary/40 bg-primary/5 p-3">
              <p className="mb-1 flex items-center gap-1.5 text-xs font-medium tracking-wide uppercase">
                <TriangleAlert className="size-3.5 text-primary" />
                {result.warnings.length} warning{result.warnings.length === 1 ? '' : 's'}
              </p>
              <ul className="flex flex-col gap-0.5 text-sm">
                {result.warnings.map((warning, index) => (
                  <li key={index}>
                    {warning.node !== null && (
                      <span className="font-mono text-xs">{warning.node}: </span>
                    )}
                    {warning.message}
                  </li>
                ))}
              </ul>
            </div>
          )}
          {renames.length > 0 && (
            <p className="text-sm text-muted-foreground">
              Renamed for netlab:{' '}
              <span className="font-mono text-xs">
                {renames.map(([from, to]) => `${from} → ${to}`).join(', ')}
              </span>
            </p>
          )}

          <Card>
            <CardHeader>
              <CardTitle className="text-sm">Inferred definition</CardTitle>
            </CardHeader>
            <CardContent>
              <CodeEditor
                value={result.definition}
                language="yaml"
                readOnly
                className="max-h-80"
              />
            </CardContent>
          </Card>

          {nodes.map((node) => (
            <ReviewNodeCard key={node} node={node} result={result} />
          ))}

          <div className="flex items-end gap-3 border-t pt-4">
            <div className="flex flex-col gap-1.5">
              <Label htmlFor="import-lab-name">Lab name</Label>
              <Input
                id="import-lab-name"
                className="w-56 font-mono"
                value={labName}
                onChange={(e) => setLabName(e.target.value)}
                placeholder="my-imported-lab"
              />
            </div>
            <Button
              type="button"
              disabled={labName.trim() === '' || create.isPending}
              onClick={() => create.mutate()}
            >
              {create.isPending ? 'Creating…' : 'Create lab'}
            </Button>
            <Button type="button" variant="outline" onClick={() => setResult(null)}>
              Back to sources
            </Button>
          </div>
        </>
      )}
    </div>
  )
}

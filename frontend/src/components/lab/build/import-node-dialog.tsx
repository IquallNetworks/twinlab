/** Builder: add one node from a dumped running config (delta 22).
 *
 * POST /import/node parses the config into a stampable fragment (device +
 * loopback pin; everything else classified). The fragment stamps through the
 * same parseNodeFragment path templates use, and the carry + quarantine are
 * saved into the lab's custom config UNATTACHED — with a single config file
 * there is no peer to infer links from, so the carry keeps SOURCE interface
 * names (the contract QUIRK): the user wires links first, then reviews and
 * attaches the carry via the node's `config:`.
 */
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { FileUp } from 'lucide-react'
import { useRef, useState } from 'react'
import { toast } from 'sonner'

import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Label } from '@/components/ui/label'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { Textarea } from '@/components/ui/textarea'
import { api } from '@/lib/api'
import { toastError } from '@/lib/error-toast'
import { customConfigQueryOptions, deviceCatalogQueryOptions } from '@/lib/queries'

const rawWrap = (text: string) => `{% raw %}\n${text}${text.endsWith('\n') ? '' : '\n'}{% endraw %}\n`

export function ImportNodeDialog({
  labName,
  open,
  onOpenChange,
  onStamp,
}: {
  labName: string
  open: boolean
  onOpenChange: (open: boolean) => void
  /** Stamp the fragment into the doc; returns the assigned node name, or
   * null when the fragment was rejected (the callee toasts why). */
  onStamp: (fragment: string, device: string) => string | null
}) {
  const queryClient = useQueryClient()
  const { data: catalog } = useQuery(deviceCatalogQueryOptions)
  const importable = (catalog?.devices ?? []).filter((d) => d.config_import)
  const [device, setDevice] = useState('')
  const [content, setContent] = useState('')
  const [filename, setFilename] = useState<string | null>(null)
  const fileRef = useRef<HTMLInputElement>(null)

  const run = useMutation({
    mutationFn: async () => {
      const result = await api.importNode(device, content)
      const stamped = onStamp(result.fragment, device)
      if (stamped === null) return null
      // Nothing is dropped: carry + quarantine land as node variants of the
      // `imported` / `imported_quarantine` records (delta 27), deliberately
      // unreferenced until the user wires links.
      if (result.config !== '' || result.quarantine.length > 0) {
        const current = await api.getCustomConfig(labName)
        const specs = current.templates
          .filter((template) => template.tier === 'user')
          .map(({ tier: _tier, ...spec }) => ({
            ...spec,
            variants: spec.variants.map((variant) => ({ ...variant })),
          }))
        const upsert = (name: string, description: string, source: string) => {
          const variant = { source, node: stamped }
          const existing = specs.find((spec) => spec.name === name)
          if (existing === undefined) {
            specs.push({ name, description, variants: [variant] })
          } else {
            existing.variants = [
              ...existing.variants.filter((entry) => entry.node !== stamped),
              variant,
            ]
          }
        }
        if (result.config !== '') {
          upsert(
            'imported',
            'Config carried from imported sources, applied verbatim via `config: [imported]`.',
            result.config,
          )
        }
        if (result.quarantine.length > 0) {
          upsert(
            'imported_quarantine',
            'Config quarantined at import (mgmt/auth/telemetry/hardware) — unreferenced; ' +
              'attach deliberately per node if wanted.',
            rawWrap(result.quarantine.map((entry) => entry.content).join('\n')),
          )
        }
        await api.putCustomConfig(labName, specs)
        await queryClient.invalidateQueries({
          queryKey: customConfigQueryOptions(labName).queryKey,
        })
      }
      return { stamped, warnings: result.warnings, kept: result.config !== '' }
    },
    onSuccess: (outcome) => {
      if (outcome === null) return
      onOpenChange(false)
      setContent('')
      setFilename(null)
      toast.success(`Stamped ${outcome.stamped}`, {
        description: outcome.kept
          ? `Its remaining config is saved UNATTACHED as the imported template's ` +
            `${outcome.stamped} variant — wire the node’s links, review the interface ` +
            'names, then attach it via the node’s config list.'
          : undefined,
      })
      for (const warning of outcome.warnings) toast.warning(warning.message)
    },
    onError: (err) => toastError(err, 'Import failed'),
  })

  const loadFile = (file: File | undefined) => {
    if (!file) return
    file
      .text()
      .then((text) => {
        setContent(text)
        setFilename(file.name)
      })
      .catch(() => toast.error(`Could not read ${file.name}`))
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-xl">
        <DialogHeader>
          <DialogTitle>Add node from config file</DialogTitle>
          <DialogDescription>
            One dumped running config. The device and loopback are modeled; the rest of the
            config is kept for review — links cannot be inferred from a single file.
          </DialogDescription>
        </DialogHeader>
        <div className="flex flex-col gap-3">
          <div className="flex items-end gap-3">
            <div className="flex flex-col gap-1.5">
              <Label htmlFor="import-node-device">Device</Label>
              <Select value={device} onValueChange={setDevice}>
                <SelectTrigger id="import-node-device" className="w-40">
                  <SelectValue placeholder="Device" />
                </SelectTrigger>
                <SelectContent>
                  {importable.map((d) => (
                    <SelectItem key={d.device} value={d.device}>
                      {d.label}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <input
              ref={fileRef}
              type="file"
              className="hidden"
              onChange={(e) => loadFile(e.target.files?.[0])}
            />
            <Button
              type="button"
              variant="outline"
              size="sm"
              onClick={() => fileRef.current?.click()}
            >
              <FileUp className="size-3.5" />
              {filename ?? 'Load file'}
            </Button>
          </div>
          <Textarea
            value={content}
            onChange={(e) => {
              setContent(e.target.value)
              setFilename(null)
            }}
            placeholder="Paste the node's running config here"
            className="min-h-40 font-mono text-xs"
            aria-label="Source config"
          />
        </div>
        <DialogFooter>
          <Button type="button" variant="outline" onClick={() => onOpenChange(false)}>
            Cancel
          </Button>
          <Button
            type="button"
            disabled={device === '' || content.trim() === '' || run.isPending}
            onClick={() => run.mutate()}
          >
            {run.isPending ? 'Importing…' : 'Import node'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

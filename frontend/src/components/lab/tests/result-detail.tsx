import { ChevronDown, ChevronRight, Copy } from 'lucide-react'
import { useState } from 'react'
import { toast } from 'sonner'

import { StatusIcon } from '@/components/lab/tests/status-badge'
import { Button } from '@/components/ui/button'
import { copyText } from '@/lib/clipboard'
import type { TestResult } from '@/lib/schemas'
import { formatElapsed, readStatus } from '@/lib/test-results'

function CopyButton({ value, label }: { value: string; label: string }) {
  return (
    <Button
      variant="ghost"
      size="icon"
      className="size-6"
      title={`Copy ${label}`}
      onClick={() =>
        void copyText(value).then((ok) =>
          ok ? toast.success(`Copied ${label}`) : toast.error('Copy failed'),
        )
      }
    >
      <Copy className="size-3.5" />
    </Button>
  )
}

/** A labelled block of machine text: the command as it ran, the raw output,
 * the diff. Bordered, because it scrolls — an unbordered `max-h` block clips
 * mid-line and reads as a rendering bug rather than as a viewport. */
function Block({
  label,
  value,
  copyLabel,
}: {
  label: string
  value: string
  copyLabel?: string
}) {
  return (
    <div>
      <div className="mb-1 flex items-center gap-1">
        <p className="text-muted-foreground">{label}</p>
        {copyLabel !== undefined && <CopyButton value={value} label={copyLabel} />}
      </div>
      <pre className="bg-muted/50 max-h-64 overflow-auto rounded border p-2 font-mono">{value}</pre>
    </div>
  )
}

/** One node's result, opened out. The three things that answer "why did this
 * happen": the verdict's reason, the command as it ACTUALLY ran (rendered from
 * facts and adapted to the device's CLI — the artifact to paste into a
 * terminal), and the raw output.
 *
 * The output is the part the old table never showed, and it is usually the
 * whole answer. */
export function ResultDetail({ result }: { result: TestResult }) {
  const status = readStatus(result.status)
  // A compare that HELD is fourteen lines of JSON saying so. It is the diff on
  // a failure that carries the answer, so a pass folds it away rather than
  // burying the output under it.
  const [showDiff, setShowDiff] = useState(status !== 'pass')

  return (
    <div className="flex flex-col gap-2 text-xs">
      {/* Not the status badge again — the pill that opened this said it. What
          this line adds is the reason and the timing. */}
      <div className="flex flex-wrap items-baseline gap-2">
        <span className="flex items-center gap-1 font-mono">
          <StatusIcon status={result.status} />
          {result.node}
        </span>
        {result.detail !== '' && (
          <span className={status === 'pass' ? 'text-muted-foreground' : 'text-foreground'}>
            {result.detail}
          </span>
        )}
        <span className="text-muted-foreground ml-auto">{formatElapsed(result.elapsed_ms)}</span>
      </div>
      {result.command !== '' && (
        <Block label="Command" value={result.command} copyLabel="command" />
      )}
      <Block
        label="Output"
        value={result.output.trim() === '' ? 'No output.' : result.output}
        copyLabel={result.output.trim() === '' ? undefined : 'output'}
      />
      {result.diff != null && (
        <div>
          <button
            type="button"
            className="text-muted-foreground hover:text-foreground mb-1 flex items-center gap-1"
            onClick={() => setShowDiff((current) => !current)}
            aria-expanded={showDiff}
          >
            {showDiff ? (
              <ChevronDown className="size-3.5" />
            ) : (
              <ChevronRight className="size-3.5" />
            )}
            Compare diff
          </button>
          {showDiff && (
            <pre className="bg-muted/50 max-h-64 overflow-auto rounded border p-2 font-mono">
              {JSON.stringify(result.diff, null, 2)}
            </pre>
          )}
        </div>
      )}
    </div>
  )
}

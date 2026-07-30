import { toast } from 'sonner'

import { ApiError } from '@/lib/api'
import { copyText } from '@/lib/clipboard'

/** The paste-able report behind the Copy action: the message the user saw plus
 * the wire facts a bug report needs (HTTP status, error code, extras — e.g.
 * netlab's stderr rides in extras). */
function report(err: unknown, message: string): string {
  if (err instanceof ApiError) {
    const lines = [message, `HTTP ${err.status}${err.code !== null ? ` ${err.code}` : ''}`]
    if (err.extras !== null && Object.keys(err.extras).length > 0) {
      lines.push(JSON.stringify(err.extras, null, 2))
    }
    return lines.join('\n')
  }
  if (err instanceof Error && err.message !== message) return `${message}\n${err.message}`
  return message
}

/** `toast.error` for a failed operation, with a Copy action so the issue can be
 * pasted into a report — toasts are transient and unselectable, so without
 * this the details are gone the moment they scroll away. */
export function toastError(err: unknown, fallback: string): void {
  const message = err instanceof Error ? err.message : fallback
  const text = report(err, message)
  toast.error(message, {
    action: {
      label: 'Copy',
      onClick: () => {
        void copyText(text).then((ok) =>
          ok ? toast.success('Copied') : toast.error('Copy failed'),
        )
      },
    },
  })
}

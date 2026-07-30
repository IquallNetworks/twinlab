import { useEffect } from 'react'

/** Per-page browser-tab titles ("Twinlab — <title>"). Pages call it once at
 * the top; the lab detail layout owns the lab's name (tabs need no finer
 * grain). Resets to the bare product name on unmount so a page that forgets
 * to set one never inherits a stale title. */
export function useDocumentTitle(title?: string) {
  useEffect(() => {
    document.title = title === undefined ? 'Twinlab' : `Twinlab — ${title}`
    return () => {
      document.title = 'Twinlab'
    }
  }, [title])
}

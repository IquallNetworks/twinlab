/** Copy text to the clipboard, returning whether it succeeded.
 *
 * `navigator.clipboard` is only defined in a secure context, and Twinlab is
 * routinely reached over plain HTTP on a LAN (e.g. http://192.168.x.x:5173),
 * where it is absent. Fall back to a hidden-textarea + execCommand there so the
 * copy button still works. */
export async function copyText(text: string): Promise<boolean> {
  if (navigator.clipboard?.writeText) {
    try {
      await navigator.clipboard.writeText(text)
      return true
    } catch {
      // Secure-context API present but blocked; try the legacy path below.
    }
  }
  try {
    const textarea = document.createElement('textarea')
    textarea.value = text
    textarea.style.position = 'fixed'
    textarea.style.opacity = '0'
    document.body.appendChild(textarea)
    textarea.select()
    const ok = document.execCommand('copy')
    document.body.removeChild(textarea)
    return ok
  } catch {
    return false
  }
}

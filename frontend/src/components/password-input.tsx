import { Eye, EyeOff } from 'lucide-react'
import * as React from 'react'
import { useId, useState } from 'react'

import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { cn } from '@/lib/utils'

/** A password field with a reveal toggle. Typing a password you can't read is
 * how typos become "wrong password" — every password input in the app uses
 * this. The value is never revealed by default, and the toggle is per-field
 * (revealing one doesn't reveal the others in the same form).
 *
 * `type` is owned here; everything else forwards to the underlying input. */
export function PasswordInput({
  className,
  disabled,
  ...props
}: Omit<React.ComponentProps<typeof Input>, 'type'>) {
  const [revealed, setRevealed] = useState(false)
  // Names the field for the toggle's accessible label when the caller gave no
  // id — screen readers otherwise hear a bare "Show password" with no owner.
  const fallbackId = useId()
  const inputId = props.id ?? fallbackId

  return (
    <div className="relative">
      <Input
        {...props}
        id={inputId}
        type={revealed ? 'text' : 'password'}
        disabled={disabled}
        className={cn('pr-9', className)}
      />
      <Button
        type="button"
        variant="ghost"
        size="icon"
        // Not a tab stop: keyboard users move through the form's fields, and a
        // toggle between every password box is friction. Reachable by click,
        // and by keyboard through the browser's own reveal affordances.
        tabIndex={-1}
        disabled={disabled}
        aria-controls={inputId}
        aria-pressed={revealed}
        aria-label={revealed ? 'Hide password' : 'Show password'}
        title={revealed ? 'Hide password' : 'Show password'}
        className="text-muted-foreground hover:text-foreground absolute inset-y-0 right-0 h-full w-9 rounded-l-none hover:bg-transparent"
        onClick={() => setRevealed((on) => !on)}
      >
        {revealed ? <EyeOff className="size-4" /> : <Eye className="size-4" />}
      </Button>
    </div>
  )
}

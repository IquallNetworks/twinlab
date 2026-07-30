import { Moon, Palette, Sun } from 'lucide-react'
import { useTheme } from 'next-themes'
import { useEffect, useState } from 'react'

import { Button } from '@/components/ui/button'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuLabel,
  DropdownMenuRadioGroup,
  DropdownMenuRadioItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { IDENTITIES, IDENTITY_LABELS, useIdentity, type Identity } from '@/lib/identity'

/** Bake-off affordance: switch the active identity pack live. Goes away once
 * a winner is picked (docs/frontend-rework.md, Phase 1 exit). */
export function IdentitySwitcher({ className }: { className?: string }) {
  const { identity, setIdentity } = useIdentity()

  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button variant="ghost" size="icon" title="Identity (bake-off)" className={className}>
          <Palette className="size-4" />
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end">
        <DropdownMenuLabel>Identity bake-off</DropdownMenuLabel>
        <DropdownMenuSeparator />
        <DropdownMenuRadioGroup
          value={identity}
          onValueChange={(value) => setIdentity(value as Identity)}
        >
          {IDENTITIES.map((id) => (
            <DropdownMenuRadioItem key={id} value={id}>
              {IDENTITY_LABELS[id]}
            </DropdownMenuRadioItem>
          ))}
        </DropdownMenuRadioGroup>
      </DropdownMenuContent>
    </DropdownMenu>
  )
}

/** Light/dark toggle. Rendered only after mount: the resolved theme is not
 * known during SSR-style first paint, and next-themes recommends deferring. */
export function ThemeToggle({ className }: { className?: string }) {
  const { resolvedTheme, setTheme } = useTheme()
  const [mounted, setMounted] = useState(false)
  useEffect(() => setMounted(true), [])
  if (!mounted) return <Button variant="ghost" size="icon" disabled className={className} />

  const dark = resolvedTheme === 'dark'
  return (
    <Button
      variant="ghost"
      size="icon"
      title={dark ? 'Switch to light' : 'Switch to dark'}
      onClick={() => setTheme(dark ? 'light' : 'dark')}
      className={className}
    >
      {dark ? <Sun className="size-4" /> : <Moon className="size-4" />}
    </Button>
  )
}

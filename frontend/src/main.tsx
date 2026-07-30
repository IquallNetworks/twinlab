import { QueryClientProvider } from '@tanstack/react-query'
import { RouterProvider } from '@tanstack/react-router'
import { ThemeProvider } from 'next-themes'
import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'

import { Toaster } from '@/components/ui/sonner'
import { IdentityProvider, initIdentity } from '@/lib/identity'
import { queryClient, router } from '@/router'

import './index.css'

const root = document.getElementById('root')
if (!root) throw new Error('missing #root element')

// Stamp the persisted identity on <html> before React renders so the first
// paint is already in the right pack (no identity flash).
const identity = initIdentity()

createRoot(root).render(
  <StrictMode>
    <ThemeProvider attribute="class" defaultTheme="system" enableSystem>
      <IdentityProvider initial={identity}>
        <QueryClientProvider client={queryClient}>
          <RouterProvider router={router} />
        </QueryClientProvider>
        <Toaster />
      </IdentityProvider>
    </ThemeProvider>
  </StrictMode>,
)

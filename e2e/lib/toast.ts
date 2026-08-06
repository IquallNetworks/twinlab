import { expect, type Locator, type Page } from '@playwright/test'

// sonner renders toasts into a portal as [data-sonner-toast] elements. Error
// toasts additionally carry a "Copy" action button — match on the message
// text, not the whole toast content.
export function toast(page: Page, text: string | RegExp): Locator {
  return page.locator('[data-sonner-toast]').filter({ hasText: text })
}

// Toasts auto-dismiss after a few seconds — assert promptly after the action.
export async function expectToast(page: Page, text: string | RegExp): Promise<void> {
  await expect(toast(page, text).first()).toBeVisible()
}

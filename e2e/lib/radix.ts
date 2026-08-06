import type { Locator, Page } from '@playwright/test'

// Radix Select is not a native <select> — selectOption() cannot drive it. The
// trigger is a role=combobox button; picking opens a portal at document.body
// with role=option items, so the option lookup must go through the page.
export async function selectOption(
  page: Page,
  trigger: Locator,
  option: string | RegExp,
): Promise<void> {
  await trigger.click()
  await page.getByRole('option', { name: option }).click()
}

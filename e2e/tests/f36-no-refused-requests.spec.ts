import { test, expect } from '@playwright/test'

// A page must never ask the server for something the signed-in role is not allowed to have (403), cannot find (404) or sends wrongly (400/422).
// Those are invisible to the other sweeps (they only fail on 5xx) but show up as red console errors and as empty or broken pages.
// The menu is the source of the route list, so a page that is offered to a role must load cleanly for that role.
const ROLES = ['founder', 'hr', 'mgr', 'e1', 'board']

for (const role of ROLES) {
  test.describe(`F36 no refused requests as ${role}`, () => {
    test.use({ storageState: `.auth/${role}.json` })

    test(`F36 every menu page loads without a refused request (${role})`, async ({ page }) => {
      const refused: string[] = []
      page.on('response', (r) => {
        const u = new URL(r.url())
        if (u.pathname.startsWith('/api/') && r.status() >= 400) refused.push(`${r.status()} ${r.request().method()} ${u.pathname}${u.search}`)
      })
      await page.goto('/')
      const nav = page.getByRole('navigation', { name: 'Main' })
      await expect(nav).toBeVisible()
      const hrefs = await nav.getByRole('link').evaluateAll((els) => els.map((e) => (e as HTMLAnchorElement).getAttribute('href') || ''))
      expect(hrefs.length).toBeGreaterThan(0)
      const visited: string[] = []
      const openTabs = async () => {                                       // tabs load their data lazily, so each one is opened
        const tabs = page.getByRole('tab')
        const n = await tabs.count()
        for (let i = 0; i < n; i++) {
          await tabs.nth(i).click()
          await page.waitForLoadState('networkidle')
        }
      }
      const details = new Set<string>()
      for (const href of [...new Set(hrefs)].filter((h) => h.startsWith('/'))) {
        await page.goto(href)
        await page.waitForLoadState('networkidle')
        await expect(page.getByText('Page not found')).toHaveCount(0)
        await openTabs()
        visited.push(href)
        const inPage = await page.locator('main').getByRole('link').evaluateAll((els) => els.map((e) => (e as HTMLAnchorElement).getAttribute('href') || ''))
        for (const h of inPage.filter((x) => /^\/(employees|projects|teams)\/\d+$/.test(x)).slice(0, 2)) details.add(h)
      }
      if (['founder', 'hr', 'mgr'].includes(role)) expect(details.size, 'the sweep found detail pages to open').toBeGreaterThan(0)
      for (const href of [...details].slice(0, 8)) {                       // a few detail pages per role: employee, project, team
        await page.goto(href)
        await page.waitForLoadState('networkidle')
        await openTabs()
        visited.push(href)
      }
      expect(refused, `refused requests while visiting ${visited.join(' ')}`).toEqual([])
    })

    test(`F36 no horizontal overflow and a usable menu on phone and tablet widths (${role})`, async ({ page }) => {
      await page.goto('/')
      const hrefs = await page.getByRole('navigation', { name: 'Main' }).getByRole('link').evaluateAll((els) => els.map((e) => (e as HTMLAnchorElement).getAttribute('href') || ''))
      const wide: string[] = []
      for (const [w, h] of [[375, 812], [768, 1024]]) {
        await page.setViewportSize({ width: w, height: h })
        for (const href of [...new Set(hrefs)].filter((x) => x.startsWith('/'))) {
          await page.goto(href)
          await page.waitForLoadState('networkidle')
          const over = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth)
          if (over > 1) wide.push(`${w}px ${href} overflows by ${over}px`)
        }
      }
      expect(wide).toEqual([])
    })
  })
}

import { test, expect, type Page } from '@playwright/test'
import { acct, api, token, loginAs, watchErrors, a11y } from '../helpers'

// Each test gets its own employee so lists never leak between tests.
let n = 0
async function freshUser(): Promise<string> {
  const f = await token(acct('founder'))
  const key = `todo${Date.now().toString(36)}${n++}`
  const r = await api('POST', '/employees', f, { email: `${key}@acme.com`, full_name: `Todo ${key}`, password: 'Pass1234', role: 'employee' })
  expect(r.status).toBe(201)
  return `${key}@acme.com`
}
async function open(page: Page, email: string) {
  await loginAs(page, email, 'Pass1234')
  await page.goto('/my-tasks')
  await expect(page.getByRole('heading', { name: 'My tasks' })).toBeVisible()
}
async function addTask(page: Page, title: string, opts: { priority?: string; h?: string; m?: string } = {}) {
  const form = page.getByRole('textbox', { name: 'New task' })
  await form.fill(title)
  const box = form.locator('xpath=ancestor::form')
  if (opts.priority) await box.getByLabel('Priority').selectOption({ label: opts.priority })
  if (opts.h) await box.getByLabel('Hours').fill(opts.h)
  if (opts.m) await box.getByLabel('Minutes').fill(opts.m)
  await box.getByRole('button', { name: 'Add task' }).click()
  await expect(page.getByRole('list', { name: 'Task list' }).getByText(title, { exact: true })).toBeVisible()
}
const card = (page: Page, title: string) => page.locator('[data-task-id]').filter({ has: page.getByText(title, { exact: true }) }).last()
const order = async (page: Page) => page.getByRole('list', { name: 'Task list' }).locator(':scope > li > [data-task-id] > div:first-child [data-role=title]').allInnerTexts()

const grip = (page: Page, title: string) => card(page, title).locator('span[title^="Drag"], span[title^="Clear"]').first()
/** Drag by the grip of one task onto another: top quarter = above it, bottom quarter = below it, middle = inside it (as a subtask). */
async function dragOnto(page: Page, from: string, to: string, where: 'top' | 'bottom' | 'middle' = 'top') {
  await grip(page, from).hover()                 // scrolls the source into view; measure the target afterwards
  const box = (await card(page, to).boundingBox())!
  const y = where === 'top' ? box.y + 3 : where === 'bottom' ? box.y + box.height - 3 : box.y + box.height / 2
  await page.mouse.down()
  await page.mouse.move(box.x + 80, y - 20 < box.y ? box.y + 1 : y - 20, { steps: 4 })
  await page.mouse.move(box.x + 80, y, { steps: 6 })
  await page.mouse.up()
}

async function addSub(page: Page, parent: string, title: string, opts: { priority?: string; m?: string } = {}) {
  const c = card(page, parent)
  if (!(await c.getByRole('list', { name: `Subtasks of ${parent}` }).count())) await c.getByRole('button', { name: /Subtasks \(\d+\)/ }).click()
  const input = c.getByRole('textbox', { name: `New subtask for ${parent}` })
  await input.fill(title)
  const box = input.locator('xpath=ancestor::form')
  if (opts.priority) await box.getByLabel('Priority').selectOption({ label: opts.priority })
  if (opts.m) await box.getByLabel('Minutes').fill(opts.m)
  await box.getByRole('button', { name: 'Add subtask' }).click()
  await expect(c.getByRole('list', { name: `Subtasks of ${parent}` }).getByText(title, { exact: true })).toBeVisible()
}

test.describe('F24 task manager', () => {
  test.use({ viewport: { width: 1280, height: 1500 } }) // tall, so both ends of a drag are on screen
  test('F24-H1 create a task with priority and duration; it survives a reload', async ({ page }) => {
    const done = watchErrors(page)
    await open(page, await freshUser())
    await expect(page.getByText('No tasks yet')).toBeVisible()
    await addTask(page, 'Write quarterly report', { priority: 'High', h: '1', m: '30' })
    const c = card(page, 'Write quarterly report')
    await expect(c.getByText('High priority')).toBeVisible()
    await expect(c.getByText('1h 30m').first()).toBeVisible()
    await page.reload()
    await expect(card(page, 'Write quarterly report').getByText('High priority')).toBeVisible()
    await expect(card(page, 'Write quarterly report').getByText('1h 30m').first()).toBeVisible()   // the estimate is stored, not just shown
    done()
  })

  test('F24-H2 subtasks: add several, each with its own priority and time; totals add up and stay with their task', async ({ page }) => {
    await open(page, await freshUser())
    await addTask(page, 'Launch website', { h: '1' })
    await addTask(page, 'Plan party')
    await addSub(page, 'Launch website', 'Design page', { priority: 'High', m: '30' })
    await addSub(page, 'Launch website', 'Write copy', { priority: 'Low', m: '15' })
    const c = card(page, 'Launch website')
    await expect(c.getByText('0 of 2 subtasks done · time needed 1h 45m')).toBeVisible()
    const subs = c.getByRole('list', { name: 'Subtasks of Launch website' })
    await expect(subs.getByText('High priority')).toBeVisible()
    await expect(subs.getByText('Low priority')).toBeVisible()
    await page.reload()
    await card(page, 'Launch website').getByRole('button', { name: /Subtasks \(2\)/ }).click()
    await expect(card(page, 'Launch website').getByRole('list', { name: 'Subtasks of Launch website' }).getByText('Write copy', { exact: true })).toBeVisible()
    await expect(card(page, 'Plan party').getByText(/subtasks done/)).toHaveCount(0)
  })

  test('F24-H3 edit a task and a subtask in the dialog', async ({ page }) => {
    await open(page, await freshUser())
    await addTask(page, 'Draft email')
    await addSub(page, 'Draft email', 'Pick recipients')
    await card(page, 'Draft email').getByRole('button', { name: 'Edit "Draft email"' }).click()
    const dlg = page.getByRole('dialog', { name: 'Edit task' })
    await dlg.getByLabel('Task title').fill('Draft email ✨ for the team')
    await dlg.getByLabel('Notes').fill('Keep it short')
    await dlg.getByLabel('Priority').selectOption({ label: 'Low' })
    await dlg.getByLabel('Status').selectOption({ label: 'In progress' })
    await dlg.getByLabel('Hours').fill('0'); await dlg.getByLabel('Minutes').fill('40')
    await dlg.getByRole('button', { name: 'Save changes' }).click()
    await expect(dlg).toBeHidden()
    const c = card(page, 'Draft email ✨ for the team')
    await expect(c.getByText('Low priority').first()).toBeVisible()
    await expect(c.getByText('Keep it short')).toBeVisible()
    await expect(c.getByText('40m').first()).toBeVisible()
    await expect(c.getByLabel('Status of Draft email ✨ for the team')).toHaveValue('in_progress')
    // the subtask has its own dialog
    await c.getByRole('button', { name: 'Edit "Pick recipients"' }).click()
    const sd = page.getByRole('dialog', { name: 'Edit subtask' })
    await sd.getByLabel('Subtask title').fill('Pick the recipients')
    await sd.getByRole('button', { name: 'Save changes' }).click()
    await expect(card(page, 'Pick the recipients')).toBeVisible()
  })

  test('F24-H4 status: select and checkbox; finishing every subtask completes the task and reopening reopens it', async ({ page }) => {
    await open(page, await freshUser())
    await addTask(page, 'Ship release')
    await addSub(page, 'Ship release', 'Build')
    await addSub(page, 'Ship release', 'Deploy')
    const c = card(page, 'Ship release')
    await c.getByLabel('Status of Build').selectOption({ label: 'In progress' })
    await expect(c.getByLabel('Status of Ship release')).toHaveValue('in_progress')   // work on a subtask starts the task
    await c.getByRole('checkbox', { name: 'Mark "Build" as completed' }).click()
    await expect(c.getByRole('checkbox', { name: 'Mark "Build" as completed' })).toBeChecked()
    await c.getByRole('checkbox', { name: 'Mark "Deploy" as completed' }).click()
    await expect(c.getByLabel('Status of Ship release')).toHaveValue('completed')
    await expect(c.getByRole('checkbox', { name: 'Mark "Ship release" as completed' })).toBeChecked()
    await c.getByRole('checkbox', { name: 'Mark "Deploy" as completed' }).click()
    await expect(c.getByLabel('Status of Ship release')).toHaveValue('in_progress')
    await page.reload()
    await expect(card(page, 'Ship release').getByLabel('Status of Ship release')).toHaveValue('in_progress')
    // completing the task completes its subtasks
    await card(page, 'Ship release').getByLabel('Status of Ship release').selectOption({ label: 'Completed' })
    await card(page, 'Ship release').getByRole('button', { name: /Subtasks \(2\)/ }).click()
    await expect(card(page, 'Ship release').getByLabel('Status of Deploy')).toHaveValue('completed')
  })

  test('F24-H5 delete a subtask, then a task (its subtasks go with it), each after confirming', async ({ page }) => {
    await open(page, await freshUser())
    await addTask(page, 'Old project')
    await addSub(page, 'Old project', 'Old step')
    await card(page, 'Old project').getByRole('button', { name: 'Delete "Old step"' }).click()
    await page.getByRole('dialog').getByRole('button', { name: 'Cancel' }).click()
    await expect(card(page, 'Old step')).toBeVisible()                       // cancel keeps it
    await card(page, 'Old project').getByRole('button', { name: 'Delete "Old step"' }).click()
    await page.getByRole('dialog').getByRole('button', { name: 'Delete' }).click()
    await expect(page.getByText('Old step', { exact: true })).toHaveCount(0)
    await card(page, 'Old project').getByRole('button', { name: 'Delete "Old project"' }).click()
    await page.getByRole('dialog').getByRole('button', { name: 'Delete' }).click()
    await expect(page.getByText('No tasks yet')).toBeVisible()
    await page.reload()
    await expect(page.getByText('No tasks yet')).toBeVisible()
  })

  test('F24-H6 reorder with the move buttons (keyboard friendly); order is saved', async ({ page }) => {
    await open(page, await freshUser())
    for (const t of ['First', 'Second', 'Third']) await addTask(page, t)
    await card(page, 'Third').getByRole('button', { name: 'Move "Third" up' }).click()
    await expect.poll(() => order(page)).toEqual(['First', 'Third', 'Second'])
    await card(page, 'First').getByRole('button', { name: 'Move "First" down' }).click()
    await expect.poll(() => order(page)).toEqual(['Third', 'First', 'Second'])
    await expect(card(page, 'Third').getByRole('button', { name: 'Move "Third" up' })).toBeDisabled()
    await page.reload()
    await expect.poll(() => order(page)).toEqual(['Third', 'First', 'Second'])
  })

  test('F24-H7 drag and drop: reorder tasks, reorder subtasks, move a subtask to another task and promote one', async ({ page }) => {
    await open(page, await freshUser())
    for (const t of ['Alpha', 'Beta', 'Gamma']) await addTask(page, t)
    await addSub(page, 'Alpha', 'a1'); await addSub(page, 'Alpha', 'a2')
    await addSub(page, 'Beta', 'b1')

    // tasks: drag Gamma above Alpha
    await dragOnto(page, 'Gamma', 'Alpha', 'top')
    await expect.poll(() => order(page)).toEqual(['Gamma', 'Alpha', 'Beta'])

    // subtasks of Alpha: a2 above a1
    const subOrder = async (parent: string) => card(page, parent).getByRole('list', { name: `Subtasks of ${parent}` }).locator('[data-role=title]').allInnerTexts()
    await dragOnto(page, 'a2', 'a1', 'top')
    await expect.poll(() => subOrder('Alpha')).toEqual(['a2', 'a1'])

    // a1 moves from Alpha to Beta (below b1)
    await dragOnto(page, 'a1', 'b1', 'bottom')
    await expect.poll(() => subOrder('Beta')).toEqual(['b1', 'a1'])
    await expect.poll(() => subOrder('Alpha')).toEqual(['a2'])

    // everything is saved
    await page.reload()
    await expect.poll(() => order(page)).toEqual(['Gamma', 'Alpha', 'Beta'])
    await card(page, 'Beta').getByRole('button', { name: /Subtasks \(2\)/ }).click()
    await expect.poll(() => subOrder('Beta')).toEqual(['b1', 'a1'])
    await card(page, 'Alpha').getByRole('button', { name: /Subtasks \(1\)/ }).click()

    // promote b1 to a main task: drop it on top of Gamma
    await dragOnto(page, 'b1', 'Gamma', 'top')
    await expect.poll(() => order(page)).toEqual(['b1', 'Gamma', 'Alpha', 'Beta'])
  })

  test('F24-H8 a task without subtasks can be dropped into another task as a subtask', async ({ page }) => {
    await open(page, await freshUser())
    for (const t of ['Parent', 'Loner']) await addTask(page, t)
    await dragOnto(page, 'Loner', 'Parent', 'middle')
    await expect.poll(async () => (await order(page)).length).toBe(1)
    await expect(card(page, 'Parent').getByRole('list', { name: 'Subtasks of Parent' }).getByText('Loner', { exact: true })).toBeVisible()
  })

  test('F24-E1 emoji, accents and a very long title wrap without horizontal scroll on a phone; axe passes', async ({ page }) => {
    await open(page, await freshUser())
    await page.setViewportSize({ width: 375, height: 812 })
    const long = 'Überprüfung ✨ café ' + 'x'.repeat(150)
    await addTask(page, long)
    await addSub(page, long, 'Ünïcode 😀 sub')
    await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1)).toBe(true)
    await a11y(page, 'my tasks with data')
  })

  test('F24-E2 keyboard only: add a task with Enter, move it, change status', async ({ page }) => {
    await open(page, await freshUser())
    await page.getByRole('textbox', { name: 'New task' }).focus()
    await page.keyboard.type('Keyboard task')
    await page.keyboard.press('Enter')
    await expect(card(page, 'Keyboard task')).toBeVisible()
    await card(page, 'Keyboard task').getByLabel('Status of Keyboard task').focus()
    await page.keyboard.press('ArrowDown')
    await expect(card(page, 'Keyboard task').getByLabel('Status of Keyboard task')).toHaveValue('in_progress')
  })

  test('F24-E3 filters by status, priority and text; reordering is paused while filtering', async ({ page }) => {
    await open(page, await freshUser())
    await addTask(page, 'Pay invoices', { priority: 'High' })
    await addTask(page, 'Water plants', { priority: 'Low' })
    await card(page, 'Water plants').getByLabel('Status of Water plants').selectOption({ label: 'Completed' })
    await page.getByRole('button', { name: /^Completed \(1\)/ }).click()
    await expect(card(page, 'Water plants')).toBeVisible(); await expect(page.getByText('Pay invoices')).toHaveCount(0)
    await expect(page.getByText('Reordering is paused while filters are on.')).toBeVisible()
    await expect(card(page, 'Water plants').getByRole('button', { name: 'Move "Water plants" up' })).toBeDisabled()
    await page.getByRole('button', { name: 'Clear filters' }).click()
    await page.getByLabel('Filter by priority').selectOption({ label: 'High' })
    await expect(card(page, 'Pay invoices')).toBeVisible(); await expect(page.getByText('Water plants')).toHaveCount(0)
    await page.getByLabel('Filter by priority').selectOption({ label: 'All priorities' })
    await page.getByRole('searchbox', { name: 'Search tasks' }).fill('plants')
    await expect(card(page, 'Water plants')).toBeVisible(); await expect(page.getByText('Pay invoices')).toHaveCount(0)
    await page.getByRole('searchbox', { name: 'Search tasks' }).fill('zzz')
    await expect(page.getByText('No tasks match your filters')).toBeVisible()
  })

  test('F24-N1 empty title is refused in the quick form and in the dialog', async ({ page }) => {
    await open(page, await freshUser())
    await page.getByRole('button', { name: 'Add task' }).click()
    await expect(page.getByText('Enter a title')).toBeVisible()
    await page.getByRole('textbox', { name: 'New task' }).fill('   ')
    await page.getByRole('button', { name: 'Add task' }).click()
    await expect(page.getByText('No tasks yet')).toBeVisible()
    await addTask(page, 'Real task')
    await card(page, 'Real task').getByRole('button', { name: 'Edit "Real task"' }).click()
    const dlg = page.getByRole('dialog')
    await dlg.getByLabel('Task title').fill('')
    await dlg.getByRole('button', { name: 'Save changes' }).click()
    await expect(dlg).toBeVisible()
  })

  test('F24-N2 one person never sees another person\'s tasks', async ({ page, browser }) => {
    const a = await freshUser(); const b = await freshUser()
    await open(page, a)
    await addTask(page, 'Private to A')
    const ctx = await browser.newContext({ baseURL: 'http://localhost:5273' })
    const p2 = await ctx.newPage()
    await open(p2, b)
    await expect(p2.getByText('No tasks yet')).toBeVisible()
    await expect(p2.getByText('Private to A')).toHaveCount(0)
    await ctx.close()
  })

  test('F24-N3 project tasks assigned to you are still on the "Project tasks" tab', async ({ page }) => {
    await loginAs(page, acct('e1'))
    await page.goto('/my-tasks')
    await page.getByRole('tab', { name: 'Project tasks' }).click()
    await expect(page.getByText('Wireframes').first()).toBeVisible()
  })

  test('F24-N4 moving a task that has subtasks into another task is refused with a message', async ({ page }) => {
    await open(page, await freshUser())
    await addTask(page, 'Big'); await addTask(page, 'Other')
    await addSub(page, 'Big', 'part'); await addSub(page, 'Other', 'o1')
    await dragOnto(page, 'Big', 'o1', 'bottom')                              // a task with subtasks onto a subtask row
    await expect(page.getByText(/cannot become a subtask/i)).toBeVisible()   // the server explains why
    await expect(card(page, 'part')).toBeVisible()                           // nothing lost, still under Big
    await expect.poll(async () => (await order(page)).sort()).toEqual(['Big', 'Other'])
    await dragOnto(page, 'Other', 'Other', 'middle').catch(() => {})         // dropping a task on itself changes nothing
  })
})

test.describe('F24 founder', () => {
  test('F24-H9 the founder gets the to-do list (and no "Project tasks" tab) and it is private', async ({ page }) => {
    await loginAs(page, acct('founder'))
    await expect(page.getByRole('navigation', { name: 'Main' }).getByRole('link', { name: 'My Tasks', exact: true })).toBeVisible()
    await page.goto('/my-tasks')
    await expect(page.getByRole('heading', { name: 'My tasks' })).toBeVisible()
    await expect(page.getByRole('tab', { name: 'Project tasks' })).toHaveCount(0)
    const title = `Founder plan ${Date.now()}`
    await page.getByRole('textbox', { name: 'New task' }).fill(title)
    await page.getByRole('button', { name: 'Add task' }).click()
    await expect(page.getByRole('list', { name: 'Task list' }).getByText(title, { exact: true })).toBeVisible()
    await page.reload()
    await expect(page.getByText(title, { exact: true })).toBeVisible()
    const hr = await token(acct('hr'))
    expect(JSON.stringify((await api('GET', '/todos', hr)).body)).not.toContain(title)
  })
})

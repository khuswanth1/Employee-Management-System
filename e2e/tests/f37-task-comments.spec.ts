import { test, expect } from '@playwright/test'
import { a11y, acct, api, loginAs, token, watchErrors } from '../helpers'

test('F37-C1 an assignee discusses a task in the dialog; the owner sees it, strangers cannot', async ({ page }) => {
  const m = await token(acct('mgr'))
  const dir = (await api('GET', '/employees/directory', m)).body.items
  const e3 = dir.find((u: any) => u.email === acct('e3'))
  const proj = await api('POST', '/projects', m, { name: 'Comment e2e project', member_ids: [e3.id] })
  expect(proj.status).toBe(201)
  const task = await api('POST', `/projects/${proj.body.id}/tasks`, m, { title: 'Discuss the rollout', assignee_id: e3.id })
  expect(task.status).toBe(201)

  const done = watchErrors(page)
  await loginAs(page, acct('e3'))
  await page.goto('/my-tasks')
  await page.getByRole('tab', { name: 'Project tasks' }).click()
  await page.getByText('Discuss the rollout').first().click()
  const dlg = page.getByRole('dialog')
  await expect(dlg.getByText('No comments yet')).toBeVisible()
  const post = dlg.getByRole('button', { name: 'Post comment' })
  await expect(post).toBeDisabled()
  await dlg.getByLabel('Write a comment').pressSequentially('Can we ship on Friday?')   // real keystrokes keep focus in the box
  await post.click()
  await expect(dlg.getByRole('region', { name: 'Comments' }).getByText('Can we ship on Friday?')).toBeVisible()
  await expect(dlg.getByLabel('Write a comment')).toHaveValue('')
  await a11y(page, 'task dialog with comments')

  await page.reload()                                                                     // it is stored, not just shown
  await page.getByRole('tab', { name: 'Project tasks' }).click()
  await page.getByText('Discuss the rollout').first().click()
  await expect(page.getByRole('dialog').getByText('Can we ship on Friday?')).toBeVisible()

  const owner = (await api('GET', `/tasks/${task.body.id}/comments`, m)).body
  expect(owner.items.map((c: any) => c.body)).toEqual(['Can we ship on Friday?'])
  const stranger = await token(acct('e2'))                                                // not a member of this restricted project
  expect((await api('GET', `/tasks/${task.body.id}/comments`, stranger)).status).toBe(404)
  const note = (await api('GET', '/notifications', m)).body.items.find((n: any) => n.title === 'New comment on a task' && n.body.includes('Friday'))
  expect(note).toBeTruthy()
  done()
})

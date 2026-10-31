import { useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { Alert, Avatar, Button, Card, Field, Input, PageHeader, PasswordInput } from '../../components/ui'
import { api, fieldErrors } from '../../lib/api'
import { ROLE_LABEL } from '../../lib/format'
import { useAction } from '../../lib/hooks'
import { useAuth } from './AuthContext'
import ResignationCard from './ResignationCard'
import SecurityCard from './SecurityCard'

/** Center-crop to a 256px square JPEG: small upload, and re-encoding strips metadata and any embedded payload. */
async function toAvatarBlob(file) {
  if (!/^image\/(jpeg|png|webp)$/.test(file.type)) throw new Error('Please choose a JPEG, PNG or WebP image')
  const bmp = await createImageBitmap(file)
  const s = Math.min(bmp.width, bmp.height)
  const canvas = document.createElement('canvas')
  canvas.width = canvas.height = 256
  canvas.getContext('2d').drawImage(bmp, (bmp.width - s) / 2, (bmp.height - s) / 2, s, s, 0, 0, 256, 256)
  const blob = await new Promise((res) => canvas.toBlob(res, 'image/jpeg', 0.9))
  return new File([blob], 'avatar.jpg', { type: 'image/jpeg' })
}

export default function ProfilePage() {
  const { user, refresh } = useAuth()
  const fileRef = useRef(null)
  const upload = useAction(async (file) => api.upload('/auth/me/avatar', await toAvatarBlob(file)), { success: 'Profile photo updated', onSuccess: () => refresh() })
  const remove = useAction(() => api.del('/auth/me/avatar'), { success: 'Profile photo removed', onSuccess: () => refresh() })
  const pick = (e) => { const f = e.target.files?.[0]; e.target.value = ''; if (f) upload.mutate(f) }
  const [p, setP] = useState({ full_name: user.full_name, designation: user.designation || '', phone: user.phone || '' })
  const saveProfile = useAction(() => api.patch('/auth/me', { full_name: p.full_name, designation: p.designation || null, phone: p.phone || null }), { invalidate: ['/employees'], success: 'Profile saved', onSuccess: () => refresh() })
  const pe = fieldErrors(saveProfile.error)
  const setProf = (k) => (e) => setP((s) => ({ ...s, [k]: e.target.value }))
  const [f, setF] = useState({ current_password: '', new_password: '', confirm: '' })
  const change = useAction(() => api.post('/auth/change-password', { current_password: f.current_password, new_password: f.new_password }), {
    success: 'Password changed', onSuccess: () => setF({ current_password: '', new_password: '', confirm: '' }),
  })
  const fe = fieldErrors(change.error)
  const mismatch = f.confirm && f.confirm !== f.new_password
  const set = (k) => (e) => setF((s) => ({ ...s, [k]: e.target.value }))
  return (
    <>
      <PageHeader title="My profile" />
      <div className="grid max-w-4xl gap-6 md:grid-cols-2">
        <Card title="Account">
          <div className="mb-5 flex items-center gap-4">
            <Avatar name={user.full_name} size={20} userId={user.id} v={user.avatar_v} />
            <div className="space-y-2">
              <div className="flex gap-2">
                <Button variant="secondary" loading={upload.isPending} onClick={() => fileRef.current?.click()}>{user.avatar_v ? 'Change photo' : 'Upload photo'}</Button>
                {user.avatar_v && <Button variant="ghost" loading={remove.isPending} onClick={() => remove.mutate()}>Remove</Button>}
              </div>
              <p className="text-xs text-slate-500">JPEG, PNG or WebP. Everyone in your company can see it.</p>
              <input ref={fileRef} type="file" accept="image/jpeg,image/png,image/webp" className="sr-only" aria-label="Profile photo" onChange={pick} />
            </div>
          </div>
          <form className="space-y-4" onSubmit={(e) => { e.preventDefault(); saveProfile.mutate() }}>
            {saveProfile.error && !Object.keys(pe).length && <Alert>{saveProfile.error.message}</Alert>}
            <Field label="Full name" required error={pe.full_name}><Input value={p.full_name} onChange={setProf('full_name')} required minLength={2} maxLength={200} /></Field>
            <Field label="Designation" error={pe.designation}><Input value={p.designation} onChange={setProf('designation')} maxLength={120} /></Field>
            <Field label="Phone" error={pe.phone}><Input type="tel" value={p.phone} onChange={setProf('phone')} maxLength={40} /></Field>
            <dl className="space-y-2 text-sm">
              {[['Email', user.email], ['Role', ROLE_LABEL[user.role]], ['Company', user.company?.name]].map(([k, v]) => (
                <div key={k} className="flex justify-between gap-4"><dt className="text-slate-500">{k}</dt><dd className="font-medium">{v}</dd></div>))}
            </dl>
            <p className="text-xs text-slate-500">Email, role and reporting line are managed by HR or a founder.</p>
            {user.role !== 'board_member' && <p className="text-sm"><Link className="font-medium text-brand-700 hover:underline" to={`/employees/${user.id}`}>Personal details, emergency contact and documents</Link></p>}
            <Button type="submit" loading={saveProfile.isPending}>Save profile</Button>
          </form>
        </Card>
        <Card title="Change password">
          <form className="space-y-4" onSubmit={(e) => { e.preventDefault(); if (!mismatch) change.mutate() }}>
            {change.error && !Object.keys(fe).length && <Alert>{change.error.message}</Alert>}
            <Field label="Current password" required><PasswordInput autoComplete="current-password" value={f.current_password} onChange={set('current_password')} required /></Field>
            <Field label="New password" required error={fe.new_password} hint="10+ characters with upper/lower case and a digit"><PasswordInput autoComplete="new-password" value={f.new_password} onChange={set('new_password')} required /></Field>
            <Field label="Confirm new password" required error={mismatch ? 'Passwords do not match' : undefined}><PasswordInput autoComplete="new-password" value={f.confirm} onChange={set('confirm')} required /></Field>
            <Button type="submit" loading={change.isPending}>Update password</Button>
          </form>
        </Card>
        <SecurityCard />
        <ResignationCard />
      </div>
    </>
  )
}

import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { useState } from 'react'
import { describe, expect, it, vi } from 'vitest'
import TagInput from './TagInput'
import { FormSection, Table, TableSkeleton, Tabs } from './ui'

const cols = [{ key: 'name', header: 'Name', sortKey: 'full_name' }, { key: 'note', header: 'Note' }]
const rows = [{ id: 1, name: 'Ada', note: 'x' }]

describe('Table', () => {
  it('marks the sorted column and reports header clicks', async () => {
    const onSort = vi.fn()
    render(<Table caption="People" columns={cols} rows={rows} sort={{ key: 'full_name', order: 'desc' }} onSort={onSort} />)
    expect(screen.getByRole('columnheader', { name: /name/i })).toHaveAttribute('aria-sort', 'descending')
    expect(screen.getByRole('columnheader', { name: /note/i })).not.toHaveAttribute('aria-sort')
    await userEvent.click(screen.getByRole('button', { name: /name/i }))
    expect(onSort).toHaveBeenCalledWith('full_name')
  })

  it('opens a clickable row with the keyboard', async () => {
    const onRowClick = vi.fn()
    render(<Table caption="People" columns={cols} rows={rows} onRowClick={onRowClick} />)
    screen.getByRole('row', { name: /ada/i }).focus()
    await userEvent.keyboard('{Enter}')
    expect(onRowClick).toHaveBeenCalledWith(rows[0])
  })
})

describe('TagInput', () => {
  const Harness = ({ start = [] }) => { const [v, setV] = useState(start); return <><TagInput label="Skills" value={v} onChange={setV} /><output data-testid="out">{v.join('|')}</output></> }

  it('adds on Enter, ignores duplicates, removes with the chip button', async () => {
    render(<Harness />)
    const box = screen.getByLabelText(/add to skills/i)
    await userEvent.type(box, 'Python{Enter}python{Enter}SQL,')
    expect(screen.getByTestId('out')).toHaveTextContent('Python|SQL')
    await userEvent.click(screen.getByRole('button', { name: 'Remove Python' }))
    expect(screen.getByTestId('out')).toHaveTextContent(/^SQL$/)
  })
})

describe('Tabs', () => {
  it('moves selection with the arrow keys', async () => {
    const Harness = () => { const [v, setV] = useState('a'); return <Tabs value={v} onChange={setV} tabs={[{ id: 'a', label: 'A' }, { id: 'b', label: 'B' }]} /> }
    render(<Harness />)
    screen.getByRole('tab', { name: 'A' }).focus()
    await userEvent.keyboard('{ArrowRight}')
    expect(screen.getByRole('tab', { name: 'B' })).toHaveAttribute('aria-selected', 'true')
  })
})

describe('misc', () => {
  it('FormSection labels its group and the skeleton is announced as loading', () => {
    render(<><FormSection title="Contract"><p>field</p></FormSection><TableSkeleton rows={2} cols={2} /></>)
    expect(screen.getByRole('region', { name: 'Contract' })).toBeInTheDocument()
    expect(screen.getByRole('status', { name: 'Loading' })).toBeInTheDocument()
  })
})

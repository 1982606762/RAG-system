import { StrictMode, useState } from 'react'
import { expect, it } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import ReaderDrawer from '../src/components/ReaderDrawer'

function Workspace() {
  const [open, setOpen] = useState(false)
  return <><div className="workspace-shell"><button onClick={() => setOpen(true)}>打开资料</button></div>
    {open && <ReaderDrawer onClose={() => setOpen(false)}><button>下载</button><button onClick={() => setOpen(false)}>关闭资料</button></ReaderDrawer>}</>
}

it('traps keyboard focus, dismisses with Escape, and restores the workspace and trigger', async () => {
  const overflow = document.body.style.overflow
  const { container } = render(<StrictMode><Workspace /></StrictMode>)
  const trigger = screen.getByRole('button', { name: '打开资料' })
  await userEvent.click(trigger)
  expect(screen.getByRole('dialog')).toHaveFocus()
  expect(document.body.style.overflow).toBe('hidden')
  expect(container.querySelector('.workspace-shell')).toHaveAttribute('inert')
  await userEvent.tab()
  expect(screen.getByRole('button', { name: '下载' })).toHaveFocus()
  await userEvent.tab({ shift: true })
  expect(screen.getByRole('button', { name: '关闭资料' })).toHaveFocus()
  await userEvent.tab()
  expect(screen.getByRole('button', { name: '下载' })).toHaveFocus()
  await userEvent.keyboard('{Escape}')
  expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
  expect(trigger).toHaveFocus()
  expect(container.querySelector('.workspace-shell')).not.toHaveAttribute('inert')
  expect(document.body.style.overflow).toBe(overflow)
})

it('keeps the drawer open for content clicks and closes on the backdrop', async () => {
  const { container } = render(<Workspace />)
  await userEvent.click(screen.getByRole('button', { name: '打开资料' }))
  await userEvent.click(screen.getByRole('button', { name: '下载' }))
  expect(screen.getByRole('dialog')).toBeInTheDocument()
  await userEvent.click(container.querySelector('.reader-overlay')!)
  expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
  expect(screen.getByRole('button', { name: '打开资料' })).toHaveFocus()
})

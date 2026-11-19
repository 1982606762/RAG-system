import { useEffect, useRef, type ReactNode } from 'react'
import { useT } from '../i18n'

export default function ReaderDrawer({ children, onClose }: { children: ReactNode; onClose: () => void }) {
  const t = useT()
  const drawer = useRef<HTMLDivElement>(null)
  const close = useRef(onClose)
  close.current = onClose

  useEffect(() => {
    const previous = document.activeElement instanceof HTMLElement ? document.activeElement : null
    const overflow = document.body.style.overflow
    const background = document.querySelector('.workspace-shell')
    const wasInert = background?.hasAttribute('inert')
    background?.setAttribute('inert', '')
    document.body.style.overflow = 'hidden'
    function onKeyDown(event: KeyboardEvent) {
      if (event.key === 'Escape') { event.preventDefault(); close.current(); return }
      if (event.key !== 'Tab') return
      const elements = Array.from(drawer.current?.querySelectorAll<HTMLElement>(
        'button:not(:disabled), a[href], input:not(:disabled):not([type="hidden"]), select:not(:disabled), textarea:not(:disabled), iframe, summary, [tabindex="0"]',
      ) ?? []).filter(element => !element.closest('[hidden]'))
      const first = elements[0]
      const last = elements[elements.length - 1]
      if (!first) { event.preventDefault(); drawer.current?.focus(); return }
      if (event.shiftKey && (document.activeElement === first || !elements.includes(document.activeElement as HTMLElement))) {
        event.preventDefault(); last.focus()
      } else if (!event.shiftKey && (document.activeElement === last || !elements.includes(document.activeElement as HTMLElement))) {
        event.preventDefault(); first.focus()
      }
    }
    document.addEventListener('keydown', onKeyDown)
    drawer.current?.focus({ preventScroll: true })
    return () => {
      document.body.style.overflow = overflow
      if (!wasInert) background?.removeAttribute('inert')
      document.removeEventListener('keydown', onKeyDown)
      if (previous?.isConnected) previous.focus({ preventScroll: true })
    }
  }, [])

  return <div className="reader-overlay" onClick={event => { if (event.target === event.currentTarget) onClose() }}>
    <div className="reader-drawer" role="dialog" aria-modal="true" aria-label={t('documentDetails')} ref={drawer} tabIndex={-1}>
      {children}
    </div>
  </div>
}

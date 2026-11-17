import { useEffect, useMemo, useRef } from 'react'
import type { SourceLocation } from '../api'
import { useT } from '../i18n'

export default function OriginalText({ text, location }: { text: string; location?: SourceLocation | null }) {
  const t = useT()
  const mark = useRef<HTMLElement>(null)
  // String.slice uses UTF-16 units; Python's offsets count Unicode code points.
  const characters = useMemo(() => Array.from(text), [text])
  const range = location?.type === 'text' && Number.isInteger(location.start) && Number.isInteger(location.end)
    && location.start >= 0 && location.start < location.end && location.end <= characters.length ? location : null
  useEffect(() => { mark.current?.scrollIntoView({ behavior: 'smooth', block: 'center' }) }, [text, location])
  return <>
    {range && <p className="source-position">{t('originalLines')} {range.start_line}–{range.end_line}</p>}
    <pre className="original-text">{range ? <>
      {characters.slice(0, range.start).join('')}<mark ref={mark}>{characters.slice(range.start, range.end).join('')}</mark>
      {characters.slice(range.end).join('')}
    </> : text}</pre>
  </>
}

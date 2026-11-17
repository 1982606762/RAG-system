import { useEffect, useRef, useState } from 'react'
import { getPagePreview, type SourceLocation } from '../api'
import { useT } from '../i18n'

export function pageRegion(location?: SourceLocation | null) {
  const box = location?.type === 'page' ? location.bbox : undefined
  return box?.length === 4 && box.every(value => Number.isFinite(value) && value >= 0 && value <= 1)
    && box[0] < box[2] && box[1] < box[3] ? box : null
}

export function Region({ location }: { location?: SourceLocation | null }) {
  const t = useT()
  const region = useRef<HTMLDivElement>(null)
  const box = pageRegion(location)
  useEffect(() => { region.current?.scrollIntoView({ behavior: 'smooth', block: 'center' }) }, [location])
  return box && <div ref={region} className="source-region" role="img" aria-label={t('highlightedSource')}
    style={{ left: `${box[0] * 100}%`, top: `${box[1] * 100}%`, width: `${(box[2] - box[0]) * 100}%`, height: `${(box[3] - box[1]) * 100}%` }} />
}

export default function PagePreview({ id, page, location, fallbackUrl, filename, attempt }: {
  id: string; page: number; location?: SourceLocation | null; fallbackUrl: string; filename: string; attempt: number
}) {
  const t = useT()
  const [preview, setPreview] = useState<{ page: number; url: string } | null>(null)
  const [failed, setFailed] = useState(false)
  const [loaded, setLoaded] = useState(false)
  useEffect(() => {
    const controller = new AbortController()
    let url = ''
    setPreview(null)
    setFailed(false)
    setLoaded(false)
    getPagePreview(id, page, controller.signal).then(({ data }) => {
      if (controller.signal.aborted) return
      url = URL.createObjectURL(data)
      setPreview({ page, url })
    }).catch(() => { if (!controller.signal.aborted) setFailed(true) })
    return () => { controller.abort(); if (url) URL.revokeObjectURL(url) }
  }, [id, page, attempt])

  if (failed) return <>
    <p className="source-position" role="status">{t('pagePreviewFallback')}</p>
    <iframe className="pdf-preview" title={filename} src={`${fallbackUrl}#page=${page}`} />
  </>
  if (!preview || preview.page !== page) return <p className="source-position" role="status">{t('loadingDocument')}</p>
  return <div className="page-preview">
    <img src={preview.url} alt={`${filename} · ${t('page')} ${page}`} onLoad={() => setLoaded(true)} onError={() => setFailed(true)} />
    {loaded && location?.type === 'page' && location.page === page && <Region location={location} />}
  </div>
}

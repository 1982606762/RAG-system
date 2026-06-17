import { useState } from 'react'
import { uploadAsync, getTask } from '../api'
import { useT } from '../i18n'

// Each selected file becomes a "job" row. We kick off the async upload, get a
// task_id back, then poll /tasks/{id} every 1.5s until it finishes — that's
// the whole point of the Celery pipeline, made visible.
//
// UX additions: drag & drop, image thumbnails, and camera capture on mobile.

interface Job {
  id: number
  name: string
  status: string // uploading | queued | started | success | failed
  thumb?: string // object URL for an image preview (revoked on unmount-ish)
  result?: any
  error?: string
}

let counter = 0

export default function UploadPage() {
  const [jobs, setJobs] = useState<Job[]>([])
  const [dragging, setDragging] = useState(false)
  const t = useT()

  const update = (id: number, patch: Partial<Job>) =>
    setJobs((prev) => prev.map((j) => (j.id === id ? { ...j, ...patch } : j)))

  const poll = (id: number, taskId: string) => {
    const timer = setInterval(async () => {
      try {
        const data = await getTask(taskId)
        update(id, { status: data.status, result: data.result, error: data.error })
        if (data.status === 'success' || data.status === 'failed') {
          clearInterval(timer)
        }
      } catch {
        clearInterval(timer)
        update(id, { status: 'failed', error: t('upload.taskQueryFailed') })
      }
    }, 1500)
  }

  const onFiles = async (files: FileList | File[]) => {
    for (const file of Array.from(files)) {
      const id = ++counter
      // Show a thumbnail immediately for images (instant visual feedback).
      const thumb = file.type.startsWith('image/')
        ? URL.createObjectURL(file)
        : undefined
      setJobs((prev) => [{ id, name: file.name, status: 'uploading', thumb }, ...prev])
      try {
        const { task_id } = await uploadAsync(file)
        update(id, { status: 'queued' })
        poll(id, task_id)
      } catch {
        update(id, { status: 'failed', error: t('upload.uploadFailed') })
      }
    }
  }

  // --- drag & drop handlers ---
  const onDrop = (e: React.DragEvent) => {
    e.preventDefault()
    setDragging(false)
    if (e.dataTransfer.files?.length) onFiles(e.dataTransfer.files)
  }

  return (
    <div className="page">
      <h2>{t('upload.title')}</h2>

      <label
        className={`dropzone ${dragging ? 'dragover' : ''}`}
        onDragOver={(e) => {
          e.preventDefault()
          setDragging(true)
        }}
        onDragLeave={() => setDragging(false)}
        onDrop={onDrop}
      >
        <input
          type="file"
          multiple
          hidden
          accept="image/*,application/pdf"
          onChange={(e) => e.target.files && onFiles(e.target.files)}
        />
        <div className="dropzone-main">
          {dragging ? t('upload.dropRelease') : t('upload.dropHint')}
        </div>
        <div className="dropzone-sub">{t('upload.dropSub')}</div>
      </label>

      {/* Mobile: a separate button that opens the camera directly. */}
      <label className="camera-btn">
        <input
          type="file"
          accept="image/*"
          capture="environment"
          hidden
          onChange={(e) => e.target.files && onFiles(e.target.files)}
        />
        {t('upload.camera')}
      </label>

      <ul className="jobs">
        {jobs.map((j) => (
          <li key={j.id} className={`job ${j.status}`}>
            {j.thumb ? (
              <img className="job-thumb" src={j.thumb} alt="" />
            ) : (
              <span className="job-thumb job-thumb-doc">PDF</span>
            )}
            <span className="job-name">{j.name}</span>
            <span className="job-status">{statusLabel(j, t)}</span>
          </li>
        ))}
      </ul>
    </div>
  )
}

// `t` is passed in because this helper lives outside the component and can't
// call the useT() hook itself.
function statusLabel(j: Job, t: (k: string) => string): string {
  switch (j.status) {
    case 'uploading':
      return t('upload.statusUploading')
    case 'queued':
    case 'pending':
      return t('upload.statusQueued')
    case 'started':
      return t('upload.statusStarted')
    case 'failed':
      return t('upload.statusFailedPrefix') + (j.error || '')
    case 'success': {
      if (j.result?.duplicate) return t('upload.statusDuplicate')
      const summary = j.result?.doc?.summary
      return t('upload.statusDone') + (summary ? `：${summary}` : '')
    }
    default:
      return j.status
  }
}

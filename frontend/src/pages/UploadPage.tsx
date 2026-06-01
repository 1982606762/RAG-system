import { useState } from 'react'
import { uploadAsync, getTask } from '../api'

// Each selected file becomes a "job" row. We kick off the async upload, get a
// task_id back, then poll /tasks/{id} every 1.5s until it finishes — that's
// the whole point of step 4's Celery pipeline, made visible.

interface Job {
  id: number
  name: string
  status: string // uploading | queued | started | success | failed
  result?: any
  error?: string
}

let counter = 0

export default function UploadPage() {
  const [jobs, setJobs] = useState<Job[]>([])

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
        update(id, { status: 'failed', error: '查询任务状态失败' })
      }
    }, 1500)
  }

  const onFiles = async (files: FileList) => {
    for (const file of Array.from(files)) {
      const id = ++counter
      setJobs((prev) => [{ id, name: file.name, status: 'uploading' }, ...prev])
      try {
        const { task_id } = await uploadAsync(file)
        update(id, { status: 'queued' })
        poll(id, task_id)
      } catch {
        update(id, { status: 'failed', error: '上传失败' })
      }
    }
  }

  return (
    <div className="page">
      <h2>上传文件</h2>
      <label className="dropzone">
        <input
          type="file"
          multiple
          hidden
          onChange={(e) => e.target.files && onFiles(e.target.files)}
        />
        点击选择文件（可多选）— 支持图片或 PDF
      </label>

      <ul className="jobs">
        {jobs.map((j) => (
          <li key={j.id} className={`job ${j.status}`}>
            <span className="job-name">{j.name}</span>
            <span className="job-status">{statusLabel(j)}</span>
          </li>
        ))}
      </ul>
    </div>
  )
}

function statusLabel(j: Job): string {
  switch (j.status) {
    case 'uploading':
      return '上传中…'
    case 'queued':
    case 'pending':
      return '排队中…'
    case 'started':
      return '分析中…'
    case 'failed':
      return '✗ 失败：' + (j.error || '')
    case 'success': {
      if (j.result?.duplicate) return '✓ 已存在（重复文件，已跳过）'
      const summary = j.result?.doc?.summary
      return '✓ 完成' + (summary ? `：${summary}` : '')
    }
    default:
      return j.status
  }
}

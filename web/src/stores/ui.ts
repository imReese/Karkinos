import { defineStore } from 'pinia'
import { ref } from 'vue'

export type NoticeTone = 'success' | 'error' | 'info'

export interface NoticeItem {
  id: number
  tone: NoticeTone
  title?: string
  message: string
}

interface NotifyOptions {
  tone?: NoticeTone
  title?: string
  message: string
  duration?: number
}

export const useUiStore = defineStore('ui', () => {
  const notices = ref<NoticeItem[]>([])
  let nextId = 1

  function notify({ tone = 'info', title, message, duration = 3200 }: NotifyOptions) {
    const id = nextId++
    notices.value.push({ id, tone, title, message })
    if (duration > 0) {
      window.setTimeout(() => {
        dismiss(id)
      }, duration)
    }
    return id
  }

  function dismiss(id: number) {
    notices.value = notices.value.filter((item) => item.id !== id)
  }

  function success(message: string, title = '已完成', duration?: number) {
    return notify({ tone: 'success', title, message, duration })
  }

  function error(message: string, title = '处理失败', duration?: number) {
    return notify({ tone: 'error', title, message, duration })
  }

  function info(message: string, title = '提示', duration?: number) {
    return notify({ tone: 'info', title, message, duration })
  }

  return {
    notices,
    notify,
    dismiss,
    success,
    error,
    info,
  }
})

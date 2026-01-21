import dayjs from 'dayjs'
import relativeTime from 'dayjs/plugin/relativeTime'
import zhCN from 'dayjs/locale/zh-cn'

dayjs.extend(relativeTime)
dayjs.locale(zhCN)

export function formatDate(date: string | null): string {
  if (!date) return '-'
  return dayjs(date).format('YYYY-MM-DD HH:mm:ss')
}

export function formatRelativeTime(date: string | null): string {
  if (!date) return '-'
  return dayjs(date).fromNow()
}

export function formatNumber(num: number): string {
  return num.toLocaleString('zh-CN')
}

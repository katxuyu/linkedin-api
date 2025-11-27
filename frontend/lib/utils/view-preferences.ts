type ViewMode = 'card' | 'list'

const VIEW_PREFERENCE_PREFIX = 'view_preference_'

export const save_view_preference = (page: string, view: ViewMode): void => {
  if (typeof window !== 'undefined') {
    try {
      localStorage.setItem(`${VIEW_PREFERENCE_PREFIX}${page}`, view)
    } catch (error) {
      console.error('Failed to save view preference:', error)
    }
  }
}

export const get_view_preference = (page: string): ViewMode => {
  if (typeof window !== 'undefined') {
    try {
      const stored = localStorage.getItem(`${VIEW_PREFERENCE_PREFIX}${page}`)
      if (stored === 'card' || stored === 'list') {
        return stored
      }
    } catch (error) {
      console.error('Failed to load view preference:', error)
    }
  }
  return 'card'
}


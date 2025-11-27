export const format_api_error = (error: unknown): string => {
  if (typeof error === 'string') {
    return error
  }
  
  if (error && typeof error === 'object') {
    const errObj = error as { response?: { data?: { detail?: unknown } }; message?: string }
    const detail = errObj.response?.data?.detail
    
    if (typeof detail === 'string') {
      return detail
    }
    
    if (Array.isArray(detail)) {
      return detail
        .map((err) => (typeof err === 'object' && err && 'msg' in err ? (err as { msg?: string }).msg : JSON.stringify(err)))
        .join(', ')
    }
    
    if (detail && typeof detail === 'object' && 'msg' in detail) {
      return (detail as { msg?: string }).msg || JSON.stringify(detail)
    }

    if (errObj.message) {
      return errObj.message
    }
  }
  
  return 'An unexpected error occurred'
}





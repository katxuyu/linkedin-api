export interface RetryOptions {
  max_retries?: number
  initial_delay_ms?: number
  max_delay_ms?: number
  backoff_multiplier?: number
  retryable_errors?: string[]
}

const DEFAULT_OPTIONS: Required<RetryOptions> = {
  max_retries: 3,
  initial_delay_ms: 500,
  max_delay_ms: 5000,
  backoff_multiplier: 2,
  retryable_errors: ['ECONNREFUSED', 'ETIMEDOUT', 'Network Error', 'ERR_NETWORK', 'Failed to fetch'],
}

const sleep = (ms: number): Promise<void> => {
  return new Promise((resolve) => setTimeout(resolve, ms))
}

const is_retryable_error = (error: unknown, retryable_errors: string[]): boolean => {
  if (!error) return false
  
  const error_message = error instanceof Error ? error.message : String(error)
  const error_code = (error as { code?: string })?.code
  
  const message_matches = retryable_errors.some((pattern) => error_message.includes(pattern))
  const code_matches = error_code ? retryable_errors.includes(error_code) : false
  
  return message_matches || code_matches
}

export const retry_with_backoff = async <T>(
  fn: () => Promise<T>,
  options: RetryOptions = {}
): Promise<T> => {
  const opts = { ...DEFAULT_OPTIONS, ...options }
  let last_error: unknown
  
  for (let attempt = 0; attempt <= opts.max_retries; attempt++) {
    try {
      return await fn()
    } catch (error) {
      last_error = error
      
      if (attempt === opts.max_retries) {
        break
      }
      
      if (!is_retryable_error(error, opts.retryable_errors)) {
        throw error
      }
      
      const delay = Math.min(
        opts.initial_delay_ms * Math.pow(opts.backoff_multiplier, attempt),
        opts.max_delay_ms
      )
      
      await sleep(delay)
    }
  }
  
  throw last_error
}
















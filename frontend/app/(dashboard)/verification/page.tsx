'use client'

import { useEffect, useMemo, useState } from 'react'
import { format, formatDistanceToNowStrict } from 'date-fns'
import Link from 'next/link'
import { toast } from 'sonner'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { CodeRequestDetail } from '@/types'
import { useCodeRequests, useSubmitCodeRequest } from '@/lib/hooks/useCodeRequests'

const OPERATOR_STORAGE_KEY = 'code-request-operator-name'

function formatRemaining(seconds: number): string {
  if (seconds <= 0) {
    return 'Expired'
  }
  const minutes = Math.floor(seconds / 60)
  const secs = seconds % 60
  if (minutes === 0) {
    return `${secs}s`
  }
  return `${minutes}m ${secs.toString().padStart(2, '0')}s`
}

function usePersistentOperatorName(): [string, (next: string) => void] {
  const [value, setValue] = useState(() => {
    if (typeof window === 'undefined') return ''
    return window.localStorage.getItem(OPERATOR_STORAGE_KEY) || ''
  })

  const update = (next: string) => {
    setValue(next)
    if (typeof window === 'undefined') return
    if (next.trim()) {
      window.localStorage.setItem(OPERATOR_STORAGE_KEY, next.trim())
    } else {
      window.localStorage.removeItem(OPERATOR_STORAGE_KEY)
    }
  }

  return [value, update]
}

export default function VerificationRequestsPage() {
  const { data, pending, succeeded, errored, isLoading, isRefetching, error, refetch, lastUpdated } = useCodeRequests()
  const submitMutation = useSubmitCodeRequest()
  const [operatorName, setOperatorName] = usePersistentOperatorName()
  const [inputs, setInputs] = useState<Record<number, string>>({})
  const [submittingId, setSubmittingId] = useState<number | null>(null)

  // Filter pending to only show non-expired requests
  const activePending = useMemo(
    () => pending.filter((r) => r.remaining_seconds > 0),
    [pending]
  )
  
  const sortedPending = useMemo(
    () => [...activePending].sort((a, b) => Date.parse(a.expires_at) - Date.parse(b.expires_at)),
    [activePending]
  )
  
  const sortedSucceeded = useMemo(
    () => [...succeeded].sort((a, b) => Date.parse(b.created_at) - Date.parse(a.created_at)),
    [succeeded]
  )
  
  // Combine errored with expired pending requests
  const expiredPending = useMemo(
    () => pending.filter((r) => r.remaining_seconds <= 0),
    [pending]
  )
  
  const sortedErrored = useMemo(
    () => [...errored, ...expiredPending].sort((a, b) => Date.parse(b.created_at) - Date.parse(a.created_at)),
    [errored, expiredPending]
  )

  const lastUpdatedLabel = lastUpdated ? formatDistanceToNowStrict(lastUpdated, { addSuffix: true }) : '—'

  const handleSubmit = async (requestId: number) => {
    const code = (inputs[requestId] || '').trim()
    if (!code) {
      toast.error('Enter the verification code before submitting.')
      return
    }
    if (!operatorName.trim()) {
      toast.error('Provide your name or initials before submitting codes.')
      return
    }

    try {
      setSubmittingId(requestId)
      const attempt = await submitMutation.mutateAsync({
        request_id: requestId,
        code,
        operator_name: operatorName.trim(),
      })
      
      // Check the result from the backend
      if (attempt.result === 'succeeded') {
        toast.success('✅ Verification code accepted! LinkedIn session authenticated.')
      } else if (attempt.result === 'failed') {
        // PIN was rejected by LinkedIn
        const errorMsg = attempt.error_details || 'LinkedIn rejected the verification code.'
        toast.error(`❌ Verification failed: ${errorMsg}`)
      } else {
        // Result is still null/pending (shouldn't happen with current backend)
        toast.info('Code submitted. Awaiting verification result...')
      }
      
      // Clear input regardless of result
      setInputs((prev) => ({
        ...prev,
        [requestId]: '',
      }))
      
      // Force immediate refetch to update the UI
      refetch()
    } catch (subError) {
      const message =
        (subError as { response?: { data?: { detail?: string } } }).response?.data?.detail ??
        (subError instanceof Error ? subError.message : 'Failed to submit code')
      toast.error(message)
    } finally {
      setSubmittingId(null)
    }
  }

  function renderRequestMeta(request: CodeRequestDetail) {
    return (
    <div className="text-sm text-gray-600 space-y-1">
      <div>
        <span className="font-semibold text-gray-800">Status:</span>{' '}
        <Badge variant={request.status === 'pending' ? 'secondary' : 'outline'}>
          {request.status.replaceAll('_', ' ')}
        </Badge>
      </div>
      {request.status_detail && (
        <div>
          <span className="font-semibold text-gray-800">Detail:</span> {request.status_detail}
        </div>
      )}
      {request.pending_reason && (
        <div>
          <span className="font-semibold text-gray-800">Reason:</span> {request.pending_reason}
        </div>
      )}
      <div>
        <span className="font-semibold text-gray-800">Requested:</span>{' '}
        {format(new Date(request.created_at), 'LLL d, yyyy HH:mm')}
      </div>
      <div>
        <span className="font-semibold text-gray-800">Resolved:</span>{' '}
        {request.resolved_at ? format(new Date(request.resolved_at), 'LLL d, yyyy HH:mm') : '—'}
      </div>
      {request.two_captcha_job_id && (
        <div>
          <span className="font-semibold text-gray-800">2Captcha job:</span> {request.two_captcha_job_id}
        </div>
      )}
    </div>
    )
  }

  function renderAttempts(request: CodeRequestDetail) {
    if (!request.attempts.length) {
      return <p className="text-sm text-gray-500">No attempts recorded.</p>
    }

    return (
      <div className="space-y-3">
        {request.attempts.map((attempt) => (
          <div key={attempt.id} className="rounded-md border border-gray-200 p-3">
            <div className="flex flex-wrap gap-2 items-center text-sm text-gray-700">
              <Badge variant="outline">{attempt.source}</Badge>
              {attempt.submitted_by && <span>Submitted by {attempt.submitted_by}</span>}
              <span>{format(new Date(attempt.submitted_at), 'LLL d, yyyy HH:mm')}</span>
            </div>
            <div className="mt-2 text-sm text-gray-600 space-y-1">
              {attempt.code_value && (
                <div>
                  <span className="font-semibold text-gray-800">Code:</span> {attempt.code_value}
                </div>
              )}
              {attempt.result && (
                <div>
                  <span className="font-semibold text-gray-800">Result:</span> {attempt.result}
                </div>
              )}
              {attempt.error_details && (
                <div className="text-red-600">
                  <span className="font-semibold text-gray-800">Error:</span> {attempt.error_details}
                </div>
              )}
            </div>
          </div>
        ))}
      </div>
    )
  }

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-4">
        <div>
          <h1 className="text-3xl font-semibold text-gray-900">Verification Requests</h1>
          <p className="text-gray-600">Monitor pending LinkedIn code requests and recent failures.</p>
        </div>
        <div className="flex items-center gap-3">
          <div className="text-sm text-gray-500">
            Last updated: <span className="text-gray-800 font-medium">{lastUpdatedLabel}</span>
          </div>
          <Button variant="outline" onClick={() => refetch()} disabled={isRefetching}>
            Refresh
          </Button>
        </div>
      </div>

      <Card>
        <CardHeader>
          <CardTitle>Operator identity</CardTitle>
        </CardHeader>
        <CardContent className="space-y-2">
          <p className="text-sm text-gray-600">
            Provide your name or initials. All code submissions are tagged with this value for auditing.
          </p>
          <Input
            placeholder="e.g. JD or Ops Team"
            value={operatorName}
            onChange={(event) => setOperatorName(event.target.value)}
          />
        </CardContent>
      </Card>

      {error && (
        <div className="rounded-md border border-red-200 bg-red-50 p-4 text-sm text-red-700">
          Failed to load requests. {error instanceof Error ? error.message : 'Unexpected error'}
        </div>
      )}

      <Tabs defaultValue="pending" className="w-full">
        <TabsList>
          <TabsTrigger value="pending">
            Pending ({sortedPending.length})
          </TabsTrigger>
          <TabsTrigger value="succeeded">
            Success ({sortedSucceeded.length})
          </TabsTrigger>
          <TabsTrigger value="errored">
            Errored ({sortedErrored.length})
          </TabsTrigger>
        </TabsList>
        <TabsContent value="pending" className="mt-6 space-y-4">
          {isLoading && !data ? (
            <Card>
              <CardContent className="py-10 text-center text-gray-600">Loading pending requests…</CardContent>
            </Card>
          ) : sortedPending.length === 0 ? (
            <Card>
              <CardContent className="py-10 text-center text-gray-600">
                No pending verification requests right now.
              </CardContent>
            </Card>
          ) : (
            sortedPending.map((request) => (
              <Card key={request.id} className="overflow-hidden">
                <CardHeader className="flex flex-row items-start justify-between gap-4">
                  <div>
                    <CardTitle className="text-lg">
                      Request #{request.id}{' '}
                      <Badge variant="secondary" className="ml-2">
                        {request.request_type}
                      </Badge>
                    </CardTitle>
                    <div className="text-sm text-gray-600 space-y-1 mt-2">
                      <div>
                        <span className="font-semibold text-gray-800">Outreach seat:</span>{' '}
                        <span className="text-gray-900">{request.outreach_email}</span>{' '}
                        <Link
                          href={request.outreach_linkedin_url}
                          target="_blank"
                          className="text-indigo-600 hover:underline"
                        >
                          View profile
                        </Link>
                      </div>
                      <div>
                        <span className="font-semibold text-gray-800">Target:</span>{' '}
                        {request.target_name ? (
                          <>
                            <span className="text-gray-900">{request.target_name}</span>{' '}
                            {request.target_url && (
                              <Link href={request.target_url} target="_blank" className="text-indigo-600 hover:underline">
                                LinkedIn
                              </Link>
                            )}
                          </>
                        ) : (
                          <span className="text-gray-600">Unknown</span>
                        )}
                      </div>
                      <div>
                        <span className="font-semibold text-gray-800">Expires:</span>{' '}
                        {format(new Date(request.expires_at), 'LLL d, yyyy HH:mm')}
                      </div>
                      <div>
                        <span className="font-semibold text-gray-800">Remaining:</span>{' '}
                        {formatRemaining(request.remaining_seconds)}
                      </div>
                    </div>
                  </div>
                  <Badge variant={request.remaining_seconds <= 0 ? 'destructive' : 'outline'}>
                    {request.remaining_seconds <= 0 ? 'Expired' : 'Waiting'}
                  </Badge>
                </CardHeader>
                <CardContent className="space-y-4">
                  {request.pending_reason && (
                    <div className="rounded-md bg-gray-50 border border-gray-200 p-3 text-sm text-gray-700">
                      <span className="font-semibold text-gray-900">Reason:</span> {request.pending_reason}
                    </div>
                  )}
                  {/* Show if code was already submitted for this request */}
                  {(request.status === 'submitted' || request.attempts.length > 0) && (
                    <div className="rounded-md bg-amber-50 border border-amber-200 p-3 text-sm text-amber-800">
                      <span className="font-semibold">⏳ Code already submitted.</span>{' '}
                      Awaiting verification result. Status will update automatically.
                    </div>
                  )}
                  {/* Only show form if no code submitted yet and request is still pending */}
                  {request.status === 'pending' && request.attempts.length === 0 ? (
                    <div className="flex flex-col gap-3 md:flex-row md:items-end">
                      <div className="flex-1 space-y-2">
                        <label className="text-sm font-medium text-gray-700" htmlFor={`code-${request.id}`}>
                          Verification code
                        </label>
                        <Input
                          id={`code-${request.id}`}
                          placeholder="Enter code"
                          value={inputs[request.id] ?? ''}
                          onChange={(event) =>
                            setInputs((prev) => ({
                              ...prev,
                              [request.id]: event.target.value,
                            }))
                          }
                          disabled={submittingId === request.id}
                        />
                      </div>
                      <Button
                        disabled={
                          submittingId === request.id ||
                          !operatorName.trim() ||
                          (inputs[request.id] ?? '').trim().length === 0
                        }
                        onClick={() => handleSubmit(request.id)}
                      >
                        {submittingId === request.id ? 'Submitting…' : 'Submit code'}
                      </Button>
                    </div>
                  ) : request.status !== 'submitted' && request.attempts.length === 0 ? (
                    <div className="text-sm text-gray-500">
                      Request is no longer accepting code submissions (status: {request.status}).
                    </div>
                  ) : null}
                </CardContent>
              </Card>
            ))
          )}
        </TabsContent>
        <TabsContent value="succeeded" className="mt-6 space-y-4">
          {sortedSucceeded.length === 0 ? (
            <Card>
              <CardContent className="py-10 text-center text-gray-600">
                No successful verification requests yet.
              </CardContent>
            </Card>
          ) : (
            sortedSucceeded.map((request) => (
              <Card key={request.id} className="border-green-200 bg-green-50/30">
                <CardHeader>
                  <CardTitle className="text-lg flex items-center gap-2">
                    <span className="text-green-600">✓</span>
                    Request #{request.id}{' '}
                    <Badge variant="default" className="ml-2 bg-green-600">
                      Verified
                    </Badge>
                  </CardTitle>
                  <div className="text-sm text-gray-600 mt-2 space-y-1">
                    <div>
                      <span className="font-semibold text-gray-800">Outreach:</span> {request.outreach_email}
                    </div>
                    <div>
                      <span className="font-semibold text-gray-800">Target:</span>{' '}
                      {request.target_name || 'Unknown'}
                    </div>
                    <div>
                      <span className="font-semibold text-gray-800">Verified at:</span>{' '}
                      {request.resolved_at ? format(new Date(request.resolved_at), 'LLL d, yyyy HH:mm') : '—'}
                    </div>
                  </div>
                </CardHeader>
                <CardContent className="space-y-4">
                  {renderRequestMeta(request)}
                  <div>
                    <h4 className="text-sm font-semibold text-gray-800 mb-2">Attempts</h4>
                    {renderAttempts(request)}
                  </div>
                </CardContent>
              </Card>
            ))
          )}
        </TabsContent>
        <TabsContent value="errored" className="mt-6 space-y-4">
          {sortedErrored.length === 0 ? (
            <Card>
              <CardContent className="py-10 text-center text-gray-600">
                No errored or expired verification requests.
              </CardContent>
            </Card>
          ) : (
            sortedErrored.map((request) => (
              <Card key={request.id}>
                <CardHeader>
                  <CardTitle className="text-lg">
                    Request #{request.id}{' '}
                    <Badge variant="destructive" className="ml-2 capitalize">
                      {request.status.replaceAll('_', ' ')}
                    </Badge>
                  </CardTitle>
                  <div className="text-sm text-gray-600 mt-2 space-y-1">
                    <div>
                      <span className="font-semibold text-gray-800">Outreach:</span> {request.outreach_email}
                    </div>
                    <div>
                      <span className="font-semibold text-gray-800">Target:</span>{' '}
                      {request.target_name || 'Unknown'}
                    </div>
                    <div>
                      <span className="font-semibold text-gray-800">Completed:</span>{' '}
                      {request.resolved_at ? format(new Date(request.resolved_at), 'LLL d, yyyy HH:mm') : '—'}
                    </div>
                  </div>
                </CardHeader>
                <CardContent className="space-y-4">
                  {renderRequestMeta(request)}
                  <div>
                    <h4 className="text-sm font-semibold text-gray-800 mb-2">Attempts</h4>
                    {renderAttempts(request)}
                  </div>
                  {request.metadata && (
                    <div>
                      <h4 className="text-sm font-semibold text-gray-800 mb-2">Metadata</h4>
                      <pre className="bg-gray-50 border border-gray-200 rounded-md p-3 text-xs text-gray-700 overflow-x-auto">
                        {JSON.stringify(request.metadata, null, 2)}
                      </pre>
                    </div>
                  )}
                </CardContent>
              </Card>
            ))
          )}
        </TabsContent>
      </Tabs>
    </div>
  )
}


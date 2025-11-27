'use client'

import React, { createContext, useContext, useState } from 'react'
import { WizardState, TargetProfile } from '@/types'

interface WizardContextType {
  state: WizardState
  update_state: (partial: Partial<WizardState>) => void
  reset_state: () => void
  current_step: number
  set_current_step: (step: number) => void
  go_to_next_step: () => void
  go_to_previous_step: () => void
}

const initial_state: WizardState = {
  selectedClientId: null,
  clientEmail: null,
  clientAccessToken: null,
  outreachProfileId: null,
  campaignTemplateId: null,
  requiredVariables: [],
  targetProfiles: [],
  importId: null,
  importMethod: null,
}

const WizardContext = createContext<WizardContextType | undefined>(undefined)

export const useWizard = () => {
  const context = useContext(WizardContext)
  if (!context) {
    throw new Error('useWizard must be used within a WizardProvider')
  }
  return context
}

interface WizardProviderProps {
  children: React.ReactNode
}

const STORAGE_KEY = 'campaign_wizard_state'
const STEP_KEY = 'campaign_wizard_step'

export const WizardProvider: React.FC<WizardProviderProps> = ({ children }) => {
  const [state, set_state] = useState<WizardState>(() => {
    if (typeof window !== 'undefined') {
      const stored_state = localStorage.getItem(STORAGE_KEY)
      if (stored_state) {
        try {
          const parsed = JSON.parse(stored_state) as Partial<WizardState>
          return { ...initial_state, ...parsed }
        } catch (error) {
          console.error('Failed to parse stored wizard state:', error)
        }
      }
    }
    return initial_state
  })
  const [current_step, set_current_step] = useState<number>(() => {
    if (typeof window !== 'undefined') {
      const stored_step = localStorage.getItem(STEP_KEY)
      if (stored_step) {
        const parsed_step = parseInt(stored_step, 10)
        if (!Number.isNaN(parsed_step)) {
          return parsed_step
        }
      }
    }
    return 0
  })

  const update_state = (partial: Partial<WizardState>) => {
    set_state((prev) => {
      const new_state = { ...prev, ...partial }
      if (typeof window !== 'undefined') {
        localStorage.setItem(STORAGE_KEY, JSON.stringify(new_state))
      }
      return new_state
    })
  }

  const reset_state = () => {
    set_state(initial_state)
    set_current_step(0)
    if (typeof window !== 'undefined') {
      localStorage.removeItem(STORAGE_KEY)
      localStorage.removeItem(STEP_KEY)
    }
  }

  const update_current_step = (step: number) => {
    set_current_step(step)
    if (typeof window !== 'undefined') {
      localStorage.setItem(STEP_KEY, step.toString())
    }
  }

  const go_to_next_step = () => {
    update_current_step(current_step + 1)
  }

  const go_to_previous_step = () => {
    if (current_step > 0) {
      update_current_step(current_step - 1)
    }
  }

  return (
    <WizardContext.Provider
      value={{
        state,
        update_state,
        reset_state,
        current_step,
        set_current_step: update_current_step,
        go_to_next_step,
        go_to_previous_step,
      }}
    >
      {children}
    </WizardContext.Provider>
  )
}




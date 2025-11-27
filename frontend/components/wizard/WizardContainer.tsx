'use client'

import React from 'react'
import { Card } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { useWizard } from '@/lib/context/WizardContext'
import { Progress } from '@/components/ui/progress'

type WizardStepComponent = React.ComponentType<{ on_next: () => void; on_back: () => void }>

interface WizardStep {
  title: string
  description: string
  component: WizardStepComponent
}

interface WizardContainerProps {
  steps: WizardStep[]
  on_complete?: () => void
}

export const WizardContainer: React.FC<WizardContainerProps> = ({
  steps,
  on_complete,
}) => {
  const { current_step, go_to_next_step, go_to_previous_step, set_current_step } = useWizard()

  const CurrentStepComponent = steps[current_step]?.component
  const progress = ((current_step + 1) / steps.length) * 100

  const handle_next = () => {
    if (current_step < steps.length - 1) {
      go_to_next_step()
    } else if (on_complete) {
      on_complete()
    }
  }

  const handle_back = () => {
    go_to_previous_step()
  }

  return (
    <div className="space-y-6">
      <div>
        <div className="flex items-center justify-between mb-4">
          <div>
            <h2 className="text-2xl font-bold text-gray-900">
              {steps[current_step]?.title}
            </h2>
            <p className="text-sm text-gray-600">
              Step {current_step + 1} of {steps.length}
            </p>
          </div>
        </div>
        <Progress value={progress} className="h-2" />
      </div>

      <div className="flex gap-2 overflow-x-auto pb-2">
        {steps.map((step, index) => (
          <button
            key={index}
            onClick={() => set_current_step(index)}
            className={`
              flex-shrink-0 px-4 py-2 rounded-lg text-sm font-medium transition-colors
              ${
                index === current_step
                  ? 'bg-blue-600 text-white'
                  : index < current_step
                  ? 'bg-green-100 text-green-800 hover:bg-green-200'
                  : 'bg-gray-100 text-gray-600 hover:bg-gray-200'
              }
            `}
          >
            {index + 1}. {step.title}
          </button>
        ))}
      </div>

      <Card className="p-6">
        <div className="mb-6">
          <p className="text-gray-600">{steps[current_step]?.description}</p>
        </div>

        {CurrentStepComponent && (
          <CurrentStepComponent
            on_next={handle_next}
            on_back={handle_back}
          />
        )}
      </Card>

      <div className="flex justify-between">
        <Button
          variant="outline"
          onClick={handle_back}
          disabled={current_step === 0}
        >
          Back
        </Button>
        <Button onClick={handle_next}>
          {current_step === steps.length - 1 ? 'Complete' : 'Next'}
        </Button>
      </div>
    </div>
  )
}





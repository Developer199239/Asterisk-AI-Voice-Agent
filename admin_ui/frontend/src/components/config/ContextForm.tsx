import React from 'react';
import { FormInput, FormSelect, FormLabel } from '../ui/FormComponents';

interface ContextFormProps {
    config: any;
    providers: any;
    onChange: (newConfig: any) => void;
    isNew?: boolean;
}

const ContextForm = ({ config, providers, onChange, isNew }: ContextFormProps) => {
    const updateConfig = (field: string, value: any) => {
        onChange({ ...config, [field]: value });
    };

    const availableTools = [
        'transfer',
        'cancel_transfer',
        'hangup_call',
        'leave_voicemail',
        'send_email_summary',
        'request_transcript'
    ];

    const availableProfiles = [
        'default',
        'telephony_responsive',
        'telephony_ulaw_8k',
        'openai_realtime_24k',
        'wideband_pcm_16k'
    ];

    const handleToolToggle = (tool: string) => {
        const currentTools = config.tools || [];
        const newTools = currentTools.includes(tool)
            ? currentTools.filter((t: string) => t !== tool)
            : [...currentTools, tool];
        updateConfig('tools', newTools);
    };

    const providerOptions = Object.entries(providers || {}).map(([name, p]: [string, any]) => ({
        value: name,
        label: `${name}${p.enabled === false ? ' (Disabled)' : ''}`
    }));

    return (
        <div className="space-y-6">
            <FormInput
                label="Context Name"
                value={config.name || ''}
                onChange={(e) => updateConfig('name', e.target.value)}
                disabled={!isNew}
                placeholder="e.g., demo_support"
            />

            <FormInput
                label="Greeting"
                value={config.greeting || ''}
                onChange={(e) => updateConfig('greeting', e.target.value)}
                placeholder="Hi {caller_name}, how can I help you?"
                tooltip="Use {caller_name} as a placeholder for the caller's name"
            />

            <div className="space-y-2">
                <FormLabel tooltip="The main instruction prompt for the AI agent">System Prompt</FormLabel>
                <textarea
                    className="w-full p-3 rounded-md border border-input bg-transparent text-sm min-h-[200px] focus:outline-none focus:ring-1 focus:ring-ring"
                    value={config.prompt || ''}
                    onChange={(e) => updateConfig('prompt', e.target.value)}
                    placeholder="You are a helpful voice assistant..."
                />
            </div>

            <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
                <FormSelect
                    label="Audio Profile"
                    options={availableProfiles.map(p => ({ value: p, label: p }))}
                    value={config.profile || 'telephony_ulaw_8k'}
                    onChange={(e) => updateConfig('profile', e.target.value)}
                />

                <FormSelect
                    label="Provider Override (Optional)"
                    options={[{ value: '', label: 'Default (None)' }, ...providerOptions]}
                    value={config.provider || ''}
                    onChange={(e) => updateConfig('provider', e.target.value)}
                />
            </div>

            <div className="space-y-3">
                <FormLabel>Available Tools</FormLabel>
                <div className="grid grid-cols-2 gap-3">
                    {availableTools.map(tool => (
                        <label key={tool} className="flex items-center space-x-3 p-3 rounded-md border border-border bg-card/50 hover:bg-accent cursor-pointer transition-colors">
                            <input
                                type="checkbox"
                                className="rounded border-input text-primary focus:ring-primary"
                                checked={(config.tools || []).includes(tool)}
                                onChange={() => handleToolToggle(tool)}
                            />
                            <span className="text-sm font-medium">{tool}</span>
                        </label>
                    ))}
                </div>
            </div>
        </div>
    );
};

export default ContextForm;

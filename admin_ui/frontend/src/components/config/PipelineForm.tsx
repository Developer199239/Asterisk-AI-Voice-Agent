import React, { useState, useEffect } from 'react';
import { FormInput, FormLabel } from '../ui/FormComponents';
import { ensureModularKey, isFullAgentProvider, isRegisteredProvider } from '../../utils/providerNaming';

interface PipelineFormProps {
    config: any;
    providers: any;
    onChange: (newConfig: any) => void;
    isNew?: boolean;
}

const PipelineForm: React.FC<PipelineFormProps> = ({ config, providers, onChange, isNew }) => {
    const [localConfig, setLocalConfig] = useState<any>({ ...config });

    useEffect(() => {
        setLocalConfig({ ...config });
    }, [config]);

    const updateConfig = (updates: any) => {
        const newConfig = { ...localConfig, ...updates };
        setLocalConfig(newConfig);
        onChange(newConfig);
    };

    // Helper to filter providers by capability
    // STRICT: Only use capabilities array. NO name matching.
    // Only show registered providers that have engine adapter support.
    const getProvidersByCapability = (cap: 'stt' | 'llm' | 'tts') => {
        return Object.entries(providers || {})
            .filter(([_, p]: [string, any]) => {
                // Exclude Full Agents from modular slots
                if (isFullAgentProvider(p)) return false;

                // Exclude unregistered providers (no engine adapter)
                if (!isRegisteredProvider(p)) return false;

                // Check capability existence
                return (p.capabilities || []).includes(cap);
            })
            .map(([name, p]: [string, any]) => ({
                value: name,
                label: name,
                disabled: p.enabled === false
            }));
    };

    const sttProviders = getProvidersByCapability('stt');
    const llmProviders = getProvidersByCapability('llm');
    const ttsProviders = getProvidersByCapability('tts');

    const handleProviderChange = (cap: 'stt' | 'llm' | 'tts', value: string) => {
        if (!value) {
            updateConfig({ [cap]: '' });
            return;
        }
        const normalized = ensureModularKey(value, cap);
        updateConfig({ [cap]: normalized });
    };

    return (
        <div className="space-y-6">
            <div className="space-y-4 border-b border-border pb-6">
                <h4 className="font-semibold">Pipeline Identity</h4>
                <FormInput
                    label="Pipeline Name"
                    value={localConfig.name || ''}
                    onChange={(e) => updateConfig({ name: e.target.value })}
                    placeholder="e.g., english_support"
                    disabled={!isNew}
                    tooltip="Unique identifier for this pipeline."
                />
            </div>

            <div className="space-y-4">
                <h4 className="font-semibold">Components</h4>

                <div className="space-y-2">
                    <FormLabel>Speech-to-Text (STT)</FormLabel>
                    <select
                        className="flex h-10 w-full rounded-md border border-input bg-background px-3 py-2 text-sm ring-offset-background file:border-0 file:bg-transparent file:text-sm file:font-medium placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-50"
                        value={localConfig.stt || ''}
                        onChange={(e) => handleProviderChange('stt', e.target.value)}
                    >
                        <option value="">Select STT Provider...</option>
                        {sttProviders.map(p => (
                            <option key={p.value} value={p.value} disabled={p.disabled}>
                                {p.label} {p.disabled ? '(Disabled)' : ''}
                            </option>
                        ))}
                    </select>
                    {sttProviders.length === 0 && (
                        <p className="text-xs text-destructive">No STT providers available. Create a modular STT provider first.</p>
                    )}
                </div>

                <div className="space-y-2">
                    <FormLabel>Large Language Model (LLM)</FormLabel>
                    <select
                        className="flex h-10 w-full rounded-md border border-input bg-background px-3 py-2 text-sm ring-offset-background file:border-0 file:bg-transparent file:text-sm file:font-medium placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-50"
                        value={localConfig.llm || ''}
                        onChange={(e) => handleProviderChange('llm', e.target.value)}
                    >
                        <option value="">Select LLM Provider...</option>
                        {llmProviders.map(p => (
                            <option key={p.value} value={p.value} disabled={p.disabled}>
                                {p.label} {p.disabled ? '(Disabled)' : ''}
                            </option>
                        ))}
                    </select>
                    {llmProviders.length === 0 && (
                        <p className="text-xs text-destructive">No LLM providers available. Create a modular LLM provider first.</p>
                    )}
                </div>

                <div className="space-y-2">
                    <FormLabel>Text-to-Speech (TTS)</FormLabel>
                    <select
                        className="flex h-10 w-full rounded-md border border-input bg-background px-3 py-2 text-sm ring-offset-background file:border-0 file:bg-transparent file:text-sm file:font-medium placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-50"
                        value={localConfig.tts || ''}
                        onChange={(e) => handleProviderChange('tts', e.target.value)}
                    >
                        <option value="">Select TTS Provider...</option>
                        {ttsProviders.map(p => (
                            <option key={p.value} value={p.value} disabled={p.disabled}>
                                {p.label} {p.disabled ? '(Disabled)' : ''}
                            </option>
                        ))}
                    </select>
                    {ttsProviders.length === 0 && (
                        <p className="text-xs text-destructive">No TTS providers available. Create a modular TTS provider first.</p>
                    )}
                </div>
            </div>
        </div>
    );
};

export default PipelineForm;

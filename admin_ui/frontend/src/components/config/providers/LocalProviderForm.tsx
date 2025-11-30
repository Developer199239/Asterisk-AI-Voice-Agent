import React from 'react';

interface LocalProviderFormProps {
    config: any;
    onChange: (newConfig: any) => void;
}

const LocalProviderForm: React.FC<LocalProviderFormProps> = ({ config, onChange }) => {
    const handleChange = (field: string, value: any) => {
        onChange({ ...config, [field]: value });
    };

    const name = (config?.name || '').toLowerCase();
    const caps = config?.capabilities || [];
    const isFullAgent = config?.type === 'full' || (caps.includes('stt') && caps.includes('llm') && caps.includes('tts'));
    
    // For modular providers, detect role by name or capability
    const isSTT = isFullAgent || name.includes('stt') || caps.includes('stt');
    const isTTS = isFullAgent || name.includes('tts') || caps.includes('tts');
    const isLLM = isFullAgent || name.includes('llm') || caps.includes('llm') || (!name.includes('stt') && !name.includes('tts'));

    return (
        <div className="space-y-6">
            {/* Full Agent Notice */}
            {isFullAgent && (
                <div className="bg-green-50/50 dark:bg-green-900/10 p-3 rounded-md border border-green-200 dark:border-green-900/30 text-sm text-green-800 dark:text-green-300">
                    <strong>Full Agent Mode:</strong> This provider handles STT, LLM, and TTS together via Local AI Server.
                </div>
            )}

            {/* Greeting (for full agents) */}
            {isFullAgent && (
                <div>
                    <h4 className="font-semibold mb-3">Greeting</h4>
                    <div className="space-y-2">
                        <input
                            type="text"
                            className="w-full p-2 rounded border border-input bg-background"
                            value={config.greeting || ''}
                            onChange={(e) => handleChange('greeting', e.target.value)}
                            placeholder="Hello! I'm your local AI assistant."
                        />
                        <p className="text-xs text-muted-foreground">
                            Initial greeting message spoken when a call starts.
                        </p>
                    </div>
                </div>
            )}

            {/* Connection Settings */}
            <div>
                <h4 className="font-semibold mb-3">Connection Settings</h4>
                <div className="space-y-2">
                    <label className="text-sm font-medium">
                        {isFullAgent ? 'Base URL / WebSocket URL' : 'WebSocket URL'}
                        <span className="text-xs text-muted-foreground ml-2">({isFullAgent ? 'base_url' : 'ws_url'})</span>
                    </label>
                    <input
                        type="text"
                        className="w-full p-2 rounded border border-input bg-background"
                        value={isFullAgent 
                            ? (config.base_url || '${LOCAL_WS_URL:-ws://local_ai_server:8765}')
                            : (config.ws_url || '${LOCAL_WS_URL:-ws://local_ai_server:8765}')}
                        onChange={(e) => handleChange(isFullAgent ? 'base_url' : 'ws_url', e.target.value)}
                        placeholder="${LOCAL_WS_URL:-ws://local_ai_server:8765}"
                    />
                    <p className="text-xs text-muted-foreground">
                        WebSocket URL for local AI server. Change port if running on custom configuration.
                    </p>
                </div>
            </div>

            {/* Connection Parameters */}
            <div>
                <h4 className="font-semibold mb-3">Connection Parameters</h4>
                <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                    <div className="space-y-2">
                        <label className="text-sm font-medium">Connect Timeout (s)</label>
                        <input
                            type="number"
                            step="0.1"
                            className="w-full p-2 rounded border border-input bg-background"
                            value={config.connect_timeout_sec || 5.0}
                            onChange={(e) => handleChange('connect_timeout_sec', parseFloat(e.target.value))}
                        />
                    </div>
                    <div className="space-y-2">
                        <label className="text-sm font-medium">Response Timeout (s)</label>
                        <input
                            type="number"
                            step="0.1"
                            className="w-full p-2 rounded border border-input bg-background"
                            value={config.response_timeout_sec || 5.0}
                            onChange={(e) => handleChange('response_timeout_sec', parseFloat(e.target.value))}
                        />
                    </div>
                    <div className="space-y-2">
                        <label className="text-sm font-medium">Chunk Size (ms)</label>
                        <input
                            type="number"
                            className="w-full p-2 rounded border border-input bg-background"
                            value={config.chunk_ms || 200}
                            onChange={(e) => handleChange('chunk_ms', parseInt(e.target.value))}
                        />
                    </div>
                </div>
            </div>

            {/* Role-specific settings */}
            <div className="space-y-4">
                {isLLM && (
                    <div className="space-y-2">
                        <h4 className="font-semibold text-sm border-b pb-2">LLM Defaults</h4>
                        <label className="text-sm font-medium">Max Tokens</label>
                        <input
                            type="number"
                            className="w-full p-2 rounded border border-input bg-background"
                            value={config.max_tokens || 150}
                            onChange={(e) => handleChange('max_tokens', parseInt(e.target.value))}
                        />
                        <p className="text-xs text-muted-foreground">
                            Uses local model configured on the local AI server (.env).
                        </p>
                    </div>
                )}

                {isSTT && (
                    <div className="space-y-2">
                        <h4 className="font-semibold text-sm border-b pb-2">STT</h4>
                        <label className="text-sm font-medium">STT Model Path</label>
                        <input
                            type="text"
                            className="w-full p-2 rounded border border-input bg-background"
                            value={config.stt_model || 'models/stt/vosk-model-en-us-0.22'}
                            onChange={(e) => handleChange('stt_model', e.target.value)}
                        />
                    </div>
                )}

                {isTTS && (
                    <div className="space-y-2">
                        <h4 className="font-semibold text-sm border-b pb-2">TTS</h4>
                        <label className="text-sm font-medium">TTS Voice Path</label>
                        <input
                            type="text"
                            className="w-full p-2 rounded border border-input bg-background"
                            value={config.tts_voice || 'models/tts/en_US-lessac-medium.onnx'}
                            onChange={(e) => handleChange('tts_voice', e.target.value)}
                        />
                    </div>
                )}
            </div>

            <div className="flex items-center space-x-2">
                <input
                    type="checkbox"
                    id="enabled"
                    className="rounded border-input"
                    checked={config.enabled ?? true}
                    onChange={(e) => handleChange('enabled', e.target.checked)}
                />
                <label htmlFor="enabled" className="text-sm font-medium">Enabled</label>
            </div>
        </div>
    );
};

export default LocalProviderForm;

import React from 'react';

interface VADConfigProps {
    config: any;
    onChange: (newConfig: any) => void;
}

const VADConfig: React.FC<VADConfigProps> = ({ config, onChange }) => {
    const handleChange = (field: string, value: any) => {
        onChange({ ...config, [field]: value });
    };

    return (
        <div className="space-y-6">
            <div className="space-y-4">
                <h3 className="text-lg font-semibold">Voice Activity Detection</h3>
                <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                    <div className="flex items-center space-x-2">
                        <input
                            type="checkbox"
                            id="enhanced_enabled"
                            className="rounded border-input"
                            checked={config.enhanced_enabled ?? true}
                            onChange={(e) => handleChange('enhanced_enabled', e.target.checked)}
                        />
                        <label htmlFor="enhanced_enabled" className="text-sm font-medium">Enhanced VAD</label>
                    </div>

                    <div className="flex items-center space-x-2">
                        <input
                            type="checkbox"
                            id="use_provider_vad"
                            className="rounded border-input"
                            checked={config.use_provider_vad ?? false}
                            onChange={(e) => handleChange('use_provider_vad', e.target.checked)}
                        />
                        <label htmlFor="use_provider_vad" className="text-sm font-medium">Use Provider VAD</label>
                    </div>

                    <div className="space-y-2">
                        <label className="text-sm font-medium">Min Utterance Duration (ms)</label>
                        <input
                            type="number"
                            className="w-full p-2 rounded border border-input bg-background"
                            value={config.min_utterance_duration_ms || 600}
                            onChange={(e) => handleChange('min_utterance_duration_ms', parseInt(e.target.value))}
                        />
                    </div>
                    <div className="space-y-2">
                        <label className="text-sm font-medium">Max Utterance Duration (ms)</label>
                        <input
                            type="number"
                            className="w-full p-2 rounded border border-input bg-background"
                            value={config.max_utterance_duration_ms || 10000}
                            onChange={(e) => handleChange('max_utterance_duration_ms', parseInt(e.target.value))}
                        />
                    </div>
                    <div className="space-y-2">
                        <label className="text-sm font-medium">Utterance Padding (ms)</label>
                        <input
                            type="number"
                            className="w-full p-2 rounded border border-input bg-background"
                            value={config.utterance_padding_ms || 200}
                            onChange={(e) => handleChange('utterance_padding_ms', parseInt(e.target.value))}
                        />
                    </div>
                </div>
            </div>

            <div className="space-y-4">
                <h3 className="text-lg font-semibold">Fallback VAD (WebRTC)</h3>
                <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                    <div className="flex items-center space-x-2">
                        <input
                            type="checkbox"
                            id="fallback_enabled"
                            className="rounded border-input"
                            checked={config.fallback_enabled ?? true}
                            onChange={(e) => handleChange('fallback_enabled', e.target.checked)}
                        />
                        <label htmlFor="fallback_enabled" className="text-sm font-medium">Enable Fallback</label>
                    </div>
                    <div className="space-y-2">
                        <label className="text-sm font-medium">Aggressiveness (0-3)</label>
                        <input
                            type="number"
                            min="0"
                            max="3"
                            className="w-full p-2 rounded border border-input bg-background"
                            value={config.webrtc_aggressiveness || 1}
                            onChange={(e) => handleChange('webrtc_aggressiveness', parseInt(e.target.value))}
                        />
                    </div>
                    <div className="space-y-2">
                        <label className="text-sm font-medium">Start Frames</label>
                        <input
                            type="number"
                            className="w-full p-2 rounded border border-input bg-background"
                            value={config.webrtc_start_frames || 3}
                            onChange={(e) => handleChange('webrtc_start_frames', parseInt(e.target.value))}
                        />
                    </div>
                    <div className="space-y-2">
                        <label className="text-sm font-medium">End Silence Frames</label>
                        <input
                            type="number"
                            className="w-full p-2 rounded border border-input bg-background"
                            value={config.webrtc_end_silence_frames || 50}
                            onChange={(e) => handleChange('webrtc_end_silence_frames', parseInt(e.target.value))}
                        />
                    </div>
                </div>
            </div>
        </div>
    );
};

export default VADConfig;

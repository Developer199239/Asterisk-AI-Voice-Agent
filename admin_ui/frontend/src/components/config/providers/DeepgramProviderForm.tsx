import React from 'react';

interface DeepgramProviderFormProps {
    config: any;
    onChange: (newConfig: any) => void;
}

const DeepgramProviderForm: React.FC<DeepgramProviderFormProps> = ({ config, onChange }) => {
    const handleChange = (field: string, value: any) => {
        onChange({ ...config, [field]: value });
    };

    return (
        <div className="space-y-6">
            {/* Base URL Section */}
            <div>
                <h4 className="font-semibold mb-3">API Endpoints</h4>
                <div className="grid grid-cols-1 gap-4">
                    <div className="space-y-2">
                        <label className="text-sm font-medium">
                            Voice Agent WebSocket URL
                            <span className="text-xs text-muted-foreground ml-2">(base_url)</span>
                        </label>
                        <input
                            type="text"
                            className="w-full p-2 rounded border border-input bg-background"
                            value={config.base_url || 'wss://agent.deepgram.com/v1/agent/converse'}
                            onChange={(e) => handleChange('base_url', e.target.value)}
                            placeholder="wss://agent.deepgram.com/v1/agent/converse"
                        />
                        <p className="text-xs text-muted-foreground">
                            Deepgram Voice Agent WebSocket endpoint for full agent provider. Change for EU region (wss://agent.eu.deepgram.com/v1/agent/converse).
                        </p>
                    </div>
                </div>
            </div>

            {/* Models Section */}
            <div>
                <h4 className="font-semibold mb-3">Models & Voice</h4>
                <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                    <div className="space-y-2">
                        <label className="text-sm font-medium">STT Model</label>
                        <select
                            className="w-full p-2 rounded border border-input bg-background"
                            value={config.stt_model || 'nova-2-phonecall'}
                            onChange={(e) => handleChange('stt_model', e.target.value)}
                        >
                            <optgroup label="Nova-3 (Latest)">
                                <option value="nova-3">Nova-3 General</option>
                                <option value="nova-3-medical">Nova-3 Medical</option>
                            </optgroup>
                            <optgroup label="Nova-2 (Recommended)">
                                <option value="nova-2">Nova-2 General</option>
                                <option value="nova-2-phonecall">Nova-2 Phone Call</option>
                                <option value="nova-2-meeting">Nova-2 Meeting</option>
                                <option value="nova-2-voicemail">Nova-2 Voicemail</option>
                                <option value="nova-2-finance">Nova-2 Finance</option>
                                <option value="nova-2-conversationalai">Nova-2 Conversational AI</option>
                                <option value="nova-2-video">Nova-2 Video</option>
                                <option value="nova-2-medical">Nova-2 Medical</option>
                                <option value="nova-2-drivethru">Nova-2 Drive-thru</option>
                                <option value="nova-2-automotive">Nova-2 Automotive</option>
                                <option value="nova-2-atc">Nova-2 Air Traffic Control</option>
                            </optgroup>
                            <optgroup label="Nova (Legacy)">
                                <option value="nova">Nova General</option>
                                <option value="nova-phonecall">Nova Phone Call</option>
                                <option value="nova-drivethru">Nova Drive-thru</option>
                                <option value="nova-medical">Nova Medical</option>
                                <option value="nova-voicemail">Nova Voicemail</option>
                            </optgroup>
                            <optgroup label="Other Models">
                                <option value="enhanced">Enhanced</option>
                                <option value="base">Base</option>
                                <option value="whisper-cloud">Whisper Cloud</option>
                            </optgroup>
                        </select>
                        <p className="text-xs text-muted-foreground">
                            Deepgram Speech-to-Text models.
                            <a href="https://developers.deepgram.com/docs/models-overview" target="_blank" rel="noopener noreferrer" className="ml-1 text-blue-500 hover:underline">STT Models ↗</a>
                        </p>
                    </div>

                    <div className="space-y-2">
                        <label className="text-sm font-medium">
                            Voice Model
                            <span className="text-xs text-muted-foreground ml-2">(tts_model)</span>
                        </label>
                        <select
                            className="w-full p-2 rounded border border-input bg-background"
                            value={config.tts_model || 'aura-2-thalia-en'}
                            onChange={(e) => handleChange('tts_model', e.target.value)}
                        >
                            <optgroup label="Aura-2 Female (Latest)">
                                <option value="aura-2-thalia-en">Thalia</option>
                                <option value="aura-2-asteria-en">Asteria</option>
                                <option value="aura-2-luna-en">Luna</option>
                                <option value="aura-2-athena-en">Athena</option>
                                <option value="aura-2-hera-en">Hera</option>
                                <option value="aura-2-andromeda-en">Andromeda</option>
                                <option value="aura-2-aurora-en">Aurora</option>
                                <option value="aura-2-callista-en">Callista</option>
                                <option value="aura-2-cora-en">Cora</option>
                                <option value="aura-2-cordelia-en">Cordelia</option>
                                <option value="aura-2-delia-en">Delia</option>
                                <option value="aura-2-electra-en">Electra</option>
                                <option value="aura-2-harmonia-en">Harmonia</option>
                                <option value="aura-2-helena-en">Helena</option>
                                <option value="aura-2-iris-en">Iris</option>
                                <option value="aura-2-juno-en">Juno</option>
                                <option value="aura-2-minerva-en">Minerva</option>
                                <option value="aura-2-ophelia-en">Ophelia</option>
                                <option value="aura-2-pandora-en">Pandora</option>
                                <option value="aura-2-phoebe-en">Phoebe</option>
                                <option value="aura-2-selene-en">Selene</option>
                                <option value="aura-2-theia-en">Theia</option>
                                <option value="aura-2-vesta-en">Vesta</option>
                                <option value="aura-2-amalthea-en">Amalthea</option>
                            </optgroup>
                            <optgroup label="Aura-2 Male (Latest)">
                                <option value="aura-2-orion-en">Orion</option>
                                <option value="aura-2-arcas-en">Arcas</option>
                                <option value="aura-2-orpheus-en">Orpheus</option>
                                <option value="aura-2-zeus-en">Zeus</option>
                                <option value="aura-2-apollo-en">Apollo</option>
                                <option value="aura-2-aries-en">Aries</option>
                                <option value="aura-2-atlas-en">Atlas</option>
                                <option value="aura-2-draco-en">Draco</option>
                                <option value="aura-2-hermes-en">Hermes</option>
                                <option value="aura-2-hyperion-en">Hyperion</option>
                                <option value="aura-2-janus-en">Janus</option>
                                <option value="aura-2-jupiter-en">Jupiter</option>
                                <option value="aura-2-mars-en">Mars</option>
                                <option value="aura-2-neptune-en">Neptune</option>
                                <option value="aura-2-odysseus-en">Odysseus</option>
                                <option value="aura-2-pluto-en">Pluto</option>
                                <option value="aura-2-saturn-en">Saturn</option>
                            </optgroup>
                            <optgroup label="Aura Legacy Female">
                                <option value="aura-asteria-en">Asteria</option>
                                <option value="aura-luna-en">Luna</option>
                                <option value="aura-stella-en">Stella</option>
                                <option value="aura-athena-en">Athena</option>
                                <option value="aura-hera-en">Hera</option>
                            </optgroup>
                            <optgroup label="Aura Legacy Male">
                                <option value="aura-orion-en">Orion</option>
                                <option value="aura-arcas-en">Arcas</option>
                                <option value="aura-perseus-en">Perseus</option>
                                <option value="aura-angus-en">Angus</option>
                                <option value="aura-orpheus-en">Orpheus</option>
                                <option value="aura-helios-en">Helios</option>
                                <option value="aura-zeus-en">Zeus</option>
                            </optgroup>
                        </select>
                        <p className="text-xs text-muted-foreground">
                            Deepgram Aura TTS voices. Aura-2 recommended for enterprise use.
                            <a href="https://developers.deepgram.com/docs/tts-models" target="_blank" rel="noopener noreferrer" className="ml-1 text-blue-500 hover:underline">TTS Voices ↗</a>
                        </p>
                    </div>

                    <div className="space-y-2">
                        <label className="text-sm font-medium">Input Encoding</label>
                        <select
                            className="w-full p-2 rounded border border-input bg-background"
                            value={config.input_encoding || 'linear16'}
                            onChange={(e) => handleChange('input_encoding', e.target.value)}
                        >
                            <option value="linear16">Linear16 (PCM)</option>
                            <option value="mulaw">μ-law</option>
                            <option value="alaw">A-law</option>
                        </select>
                    </div>

                    <div className="space-y-2">
                        <label className="text-sm font-medium">Input Sample Rate (Hz)</label>
                        <input
                            type="number"
                            className="w-full p-2 rounded border border-input bg-background"
                            value={config.input_sample_rate_hz || 8000}
                            onChange={(e) => handleChange('input_sample_rate_hz', parseInt(e.target.value))}
                        />
                    </div>

                    <div className="space-y-2">
                        <label className="text-sm font-medium">Output Encoding</label>
                        <select
                            className="w-full p-2 rounded border border-input bg-background"
                            value={config.output_encoding || 'mulaw'}
                            onChange={(e) => handleChange('output_encoding', e.target.value)}
                        >
                            <option value="mulaw">μ-law</option>
                            <option value="linear16">Linear16</option>
                            <option value="alaw">A-law</option>
                        </select>
                    </div>

                    <div className="space-y-2">
                        <label className="text-sm font-medium">Output Sample Rate (Hz)</label>
                        <input
                            type="number"
                            className="w-full p-2 rounded border border-input bg-background"
                            value={config.output_sample_rate_hz || 8000}
                            onChange={(e) => handleChange('output_sample_rate_hz', parseInt(e.target.value))}
                        />
                    </div>

                    <div className="space-y-2">
                        <label className="text-sm font-medium">Target Encoding</label>
                        <select
                            className="w-full p-2 rounded border border-input bg-background"
                            value={config.target_encoding || 'mulaw'}
                            onChange={(e) => handleChange('target_encoding', e.target.value)}
                        >
                            <option value="mulaw">μ-law</option>
                            <option value="linear16">Linear16</option>
                            <option value="alaw">A-law</option>
                        </select>
                    </div>

                    <div className="space-y-2">
                        <label className="text-sm font-medium">Target Sample Rate (Hz)</label>
                        <input
                            type="number"
                            className="w-full p-2 rounded border border-input bg-background"
                            value={config.target_sample_rate_hz || 8000}
                            onChange={(e) => handleChange('target_sample_rate_hz', parseInt(e.target.value))}
                        />
                    </div>

                    <div className="space-y-2">
                        <label className="text-sm font-medium">Provider Input Encoding</label>
                        <select
                            className="w-full p-2 rounded border border-input bg-background"
                            value={config.provider_input_encoding || 'linear16'}
                            onChange={(e) => handleChange('provider_input_encoding', e.target.value)}
                        >
                            <option value="linear16">Linear16 (PCM)</option>
                            <option value="mulaw">μ-law</option>
                        </select>
                    </div>

                    <div className="space-y-2">
                        <label className="text-sm font-medium">Provider Input Sample Rate (Hz)</label>
                        <input
                            type="number"
                            className="w-full p-2 rounded border border-input bg-background"
                            value={config.provider_input_sample_rate_hz || 16000}
                            onChange={(e) => handleChange('provider_input_sample_rate_hz', parseInt(e.target.value))}
                        />
                    </div>
                </div>

                <div className="space-y-2">
                    <label className="text-sm font-medium">System Instructions</label>
                    <textarea
                        className="w-full p-2 rounded border border-input bg-background min-h-[100px] font-mono text-sm"
                        value={config.instructions || ''}
                        onChange={(e) => handleChange('instructions', e.target.value)}
                        placeholder="You are a helpful assistant..."
                    />
                </div>

                <div className="space-y-2">
                    <label className="text-sm font-medium">Greeting</label>
                    <input
                        type="text"
                        className="w-full p-2 rounded border border-input bg-background"
                        value={config.greeting || ''}
                        onChange={(e) => handleChange('greeting', e.target.value)}
                        placeholder="Hello, how can I help you?"
                    />
                </div>

                <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
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

                    <div className="flex items-center space-x-2">
                        <input
                            type="checkbox"
                            id="continuous_input"
                            className="rounded border-input"
                            checked={config.continuous_input ?? true}
                            onChange={(e) => handleChange('continuous_input', e.target.checked)}
                        />
                        <label htmlFor="continuous_input" className="text-sm font-medium">Continuous Input</label>
                    </div>

                    <div className="flex items-center space-x-2">
                        <input
                            type="checkbox"
                            id="vad_turn_detection"
                            className="rounded border-input"
                            checked={config.vad_turn_detection ?? true}
                            onChange={(e) => handleChange('vad_turn_detection', e.target.checked)}
                        />
                        <label htmlFor="vad_turn_detection" className="text-sm font-medium">VAD Turn Detection</label>
                    </div>
                </div>

                <div className="space-y-2">
                    <label className="text-sm font-medium">Farewell Hangup Delay (seconds)</label>
                    <input
                        type="number"
                        step="0.5"
                        className="w-full p-2 rounded border border-input bg-background"
                        value={config.farewell_hangup_delay_sec ?? ''}
                        onChange={(e) => handleChange('farewell_hangup_delay_sec', e.target.value ? parseFloat(e.target.value) : null)}
                        placeholder="Use global default (2.5s)"
                    />
                    <p className="text-xs text-muted-foreground">
                        Seconds to wait after farewell audio before hanging up. Leave empty to use global default.
                    </p>
                </div>
            </div>

            {/* Authentication Section */}
            <div>
                <h4 className="font-semibold mb-3">Authentication</h4>
                <div className="space-y-2">
                    <label className="text-sm font-medium">API Key (Environment Variable)</label>
                    <input
                        type="text"
                        className="w-full p-2 rounded border border-input bg-background"
                        value={config.api_key || '${DEEPGRAM_API_KEY}'}
                        onChange={(e) => handleChange('api_key', e.target.value)}
                        placeholder="${DEEPGRAM_API_KEY}"
                    />
                    <p className="text-xs text-muted-foreground">Use {'${VAR_NAME}'} to reference environment variables</p>
                </div>
            </div>
        </div>
    );
};

export default DeepgramProviderForm;

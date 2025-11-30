import React, { useState, useEffect } from 'react';
import axios from 'axios';
import yaml from 'js-yaml';
import { Save, Activity } from 'lucide-react';
import { ConfigSection } from '../../components/ui/ConfigSection';
import { ConfigCard } from '../../components/ui/ConfigCard';
import { FormInput, FormSwitch } from '../../components/ui/FormComponents';

const VADPage = () => {
    const [config, setConfig] = useState<any>({});
    const [loading, setLoading] = useState(true);
    const [saving, setSaving] = useState(false);

    useEffect(() => {
        fetchConfig();
    }, []);

    const fetchConfig = async () => {
        try {
            const res = await axios.get('/api/config/yaml');
            const parsed = yaml.load(res.data.content) as any;
            setConfig(parsed || {});
        } catch (err) {
            console.error('Failed to load config', err);
        } finally {
            setLoading(false);
        }
    };

    const handleSave = async () => {
        setSaving(true);
        try {
            await axios.post('/api/config/yaml', { content: yaml.dump(config) });
            alert('VAD configuration saved successfully');
        } catch (err) {
            console.error('Failed to save config', err);
            alert('Failed to save configuration');
        } finally {
            setSaving(false);
        }
    };

    const updateVADConfig = (field: string, value: any) => {
        setConfig({
            ...config,
            vad: {
                ...config.vad,
                [field]: value
            }
        });
    };

    if (loading) return <div className="p-8 text-center text-muted-foreground">Loading configuration...</div>;

    const vadConfig = config.vad || {};

    return (
        <div className="space-y-6">
            <div className="flex justify-between items-center">
                <div>
                    <h1 className="text-3xl font-bold tracking-tight">Voice Activity Detection</h1>
                    <p className="text-muted-foreground mt-1">
                        Configure how the system detects speech and silence.
                    </p>
                </div>
                <button
                    onClick={handleSave}
                    disabled={saving}
                    className="inline-flex items-center justify-center whitespace-nowrap rounded-md text-sm font-medium transition-colors focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring disabled:pointer-events-none disabled:opacity-50 bg-primary text-primary-foreground shadow hover:bg-primary/90 h-9 px-4 py-2"
                >
                    <Save className="w-4 h-4 mr-2" />
                    {saving ? 'Saving...' : 'Save Changes'}
                </button>
            </div>

            <ConfigSection title="Primary Detection" description="Main VAD settings for speech detection.">
                <ConfigCard>
                    <div className="space-y-6">
                        <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
                            <FormSwitch
                                label="Enhanced VAD"
                                description="Use advanced algorithms for better accuracy."
                                checked={vadConfig.enhanced_enabled ?? true}
                                onChange={(e) => updateVADConfig('enhanced_enabled', e.target.checked)}
                            />
                            <FormSwitch
                                label="Use Provider VAD"
                                description="Offload VAD to the STT provider if supported."
                                checked={vadConfig.use_provider_vad ?? false}
                                onChange={(e) => updateVADConfig('use_provider_vad', e.target.checked)}
                            />
                        </div>

                        <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
                            <FormInput
                                label="Min Utterance Duration (ms)"
                                type="number"
                                value={vadConfig.min_utterance_duration_ms || 600}
                                onChange={(e) => updateVADConfig('min_utterance_duration_ms', parseInt(e.target.value))}
                            />
                            <FormInput
                                label="Max Utterance Duration (ms)"
                                type="number"
                                value={vadConfig.max_utterance_duration_ms || 10000}
                                onChange={(e) => updateVADConfig('max_utterance_duration_ms', parseInt(e.target.value))}
                            />
                            <FormInput
                                label="Utterance Padding (ms)"
                                type="number"
                                value={vadConfig.utterance_padding_ms || 200}
                                onChange={(e) => updateVADConfig('utterance_padding_ms', parseInt(e.target.value))}
                            />
                        </div>
                        <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
                            <FormInput
                                label="Fallback Buffer Size"
                                type="number"
                                value={vadConfig.fallback_buffer_size || 128000}
                                onChange={(e) => updateVADConfig('fallback_buffer_size', parseInt(e.target.value))}
                            />
                            <FormInput
                                label="Fallback Interval (ms)"
                                type="number"
                                value={vadConfig.fallback_interval_ms || 4000}
                                onChange={(e) => updateVADConfig('fallback_interval_ms', parseInt(e.target.value))}
                            />
                        </div>
                    </div>
                </ConfigCard>
            </ConfigSection>

            <ConfigSection title="Fallback VAD (WebRTC)" description="Backup detection mechanism using WebRTC standards.">
                <ConfigCard>
                    <div className="space-y-6">
                        <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
                            <FormSwitch
                                label="Enable Fallback VAD"
                                description="Use WebRTC VAD when primary detection is uncertain."
                                checked={vadConfig.fallback_enabled ?? true}
                                onChange={(e) => updateVADConfig('fallback_enabled', e.target.checked)}
                            />
                        </div>

                        <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
                            <FormInput
                                label="Fallback Buffer Size (bytes)"
                                type="number"
                                value={vadConfig.fallback_buffer_size || 128000}
                                onChange={(e) => updateVADConfig('fallback_buffer_size', parseInt(e.target.value))}
                            />
                            <FormInput
                                label="Fallback Interval (ms)"
                                type="number"
                                value={vadConfig.fallback_interval_ms || 4000}
                                onChange={(e) => updateVADConfig('fallback_interval_ms', parseInt(e.target.value))}
                            />
                        </div>

                        <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
                            <FormInput
                                label="Aggressiveness (0-3)"
                                type="number"
                                min="0"
                                max="3"
                                value={vadConfig.webrtc_aggressiveness || 1}
                                onChange={(e) => updateVADConfig('webrtc_aggressiveness', parseInt(e.target.value))}
                                tooltip="Higher values mean more aggressive silence detection."
                            />
                            <FormInput
                                label="Start Frames"
                                type="number"
                                value={vadConfig.webrtc_start_frames || 3}
                                onChange={(e) => updateVADConfig('webrtc_start_frames', parseInt(e.target.value))}
                            />
                            <FormInput
                                label="End Silence Frames"
                                type="number"
                                value={vadConfig.webrtc_end_silence_frames || 50}
                                onChange={(e) => updateVADConfig('webrtc_end_silence_frames', parseInt(e.target.value))}
                            />
                        </div>
                    </div>
                </ConfigCard>
            </ConfigSection>
        </div>
    );
};

export default VADPage;

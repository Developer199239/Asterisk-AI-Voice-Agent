import { useState, useEffect } from 'react';
import axios from 'axios';
import yaml from 'js-yaml';
import { Save, Zap, AlertCircle } from 'lucide-react';
import { ConfigSection } from '../../components/ui/ConfigSection';
import { ConfigCard } from '../../components/ui/ConfigCard';
import { FormInput, FormSwitch } from '../../components/ui/FormComponents';

const BargeInPage = () => {
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
            alert('Barge-in configuration saved successfully');
        } catch (err) {
            console.error('Failed to save config', err);
            alert('Failed to save configuration');
        } finally {
            setSaving(false);
        }
    };

    const updateBargeInConfig = (field: string, value: any) => {
        setConfig({
            ...config,
            barge_in: {
                ...config.barge_in,
                [field]: value
            }
        });
    };

    if (loading) return <div className="p-8 text-center text-muted-foreground">Loading configuration...</div>;

    const bargeInConfig = config.barge_in || {};

    return (
        <div className="space-y-6">
            {/* Restart Warning Banner */}
            <div className="bg-amber-50 dark:bg-amber-900/20 border border-amber-200 dark:border-amber-800 rounded-lg p-4">
                <div className="flex items-start">
                    <AlertCircle className="w-5 h-5 text-amber-600 dark:text-amber-400 mt-0.5 mr-3 flex-shrink-0" />
                    <div>
                        <h3 className="text-sm font-medium text-amber-800 dark:text-amber-300">
                            Configuration Reload Required
                        </h3>
                        <p className="mt-1 text-sm text-amber-700 dark:text-amber-400">
                            Changes to barge-in settings require restarting the AI Engine container to take effect.
                        </p>
                    </div>
                </div>
            </div>

            <div className="flex justify-between items-center">
                <div>
                    <h1 className="text-3xl font-bold tracking-tight">Barge-in Settings</h1>
                    <p className="text-muted-foreground mt-1">
                        Configure how callers can interrupt the AI agent during responses.
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

            <ConfigSection 
                title="Barge-in Control" 
                description="Allow callers to interrupt the AI while it's speaking."
            >
                <ConfigCard>
                    <div className="space-y-6">
                        <FormSwitch
                            label="Enable Barge-in"
                            description="Allow users to interrupt the AI agent during TTS playback."
                            checked={bargeInConfig.enabled ?? true}
                            onChange={(e) => updateBargeInConfig('enabled', e.target.checked)}
                        />

                        <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
                            <FormInput
                                label="Energy Threshold"
                                type="number"
                                value={bargeInConfig.energy_threshold || 700}
                                onChange={(e) => updateBargeInConfig('energy_threshold', parseInt(e.target.value))}
                                tooltip="RMS energy level to trigger barge-in (higher = less sensitive)"
                            />
                            <FormInput
                                label="Minimum Duration (ms)"
                                type="number"
                                value={bargeInConfig.min_ms || 150}
                                onChange={(e) => updateBargeInConfig('min_ms', parseInt(e.target.value))}
                                tooltip="Minimum speech duration to trigger barge-in"
                            />
                        </div>
                    </div>
                </ConfigCard>
            </ConfigSection>

            <ConfigSection 
                title="Protection Windows" 
                description="Prevent false barge-ins during critical moments."
            >
                <ConfigCard>
                    <div className="space-y-6">
                        <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
                            <FormInput
                                label="Initial Protection (ms)"
                                type="number"
                                value={bargeInConfig.initial_protection_ms || 100}
                                onChange={(e) => updateBargeInConfig('initial_protection_ms', parseInt(e.target.value))}
                                tooltip="Protection window at the start of each response"
                            />
                            <FormInput
                                label="Post-TTS Protection (ms)"
                                type="number"
                                value={bargeInConfig.post_tts_end_protection_ms || 800}
                                onChange={(e) => updateBargeInConfig('post_tts_end_protection_ms', parseInt(e.target.value))}
                                tooltip="Guard window after TTS ends to prevent echo"
                            />
                            <FormInput
                                label="Finalize Timeout (ms)"
                                type="number"
                                value={bargeInConfig.finalize_timeout_ms || 300}
                                onChange={(e) => updateBargeInConfig('finalize_timeout_ms', parseInt(e.target.value))}
                                tooltip="Wait time before finalizing barge-in detection"
                            />
                        </div>

                        <div className="bg-blue-50 dark:bg-blue-900/20 border border-blue-200 dark:border-blue-800 rounded-lg p-4">
                            <div className="flex items-start">
                                <Zap className="w-5 h-5 text-blue-600 dark:text-blue-400 mt-0.5 mr-3 flex-shrink-0" />
                                <div className="text-sm text-blue-700 dark:text-blue-300">
                                    <p className="font-medium mb-1">Tuning Tips</p>
                                    <ul className="list-disc list-inside space-y-1">
                                        <li><strong>Energy Threshold:</strong> Increase if barge-in is too sensitive (500-1000 typical)</li>
                                        <li><strong>Post-TTS Protection:</strong> Increase if agent hears its own voice tail (600-1000ms)</li>
                                        <li><strong>Initial Protection:</strong> Prevents barge-in during first milliseconds of response</li>
                                    </ul>
                                </div>
                            </div>
                        </div>
                    </div>
                </ConfigCard>
            </ConfigSection>

            <ConfigSection 
                title="Current Configuration" 
                description="Summary of your barge-in settings."
            >
                <ConfigCard>
                    <div className="grid grid-cols-1 md:grid-cols-2 gap-4 text-sm">
                        <div>
                            <span className="text-muted-foreground">Status:</span>
                            <span className={`ml-2 font-medium ${bargeInConfig.enabled ? 'text-green-600 dark:text-green-400' : 'text-red-600 dark:text-red-400'}`}>
                                {bargeInConfig.enabled ? 'Enabled' : 'Disabled'}
                            </span>
                        </div>
                        <div>
                            <span className="text-muted-foreground">Energy Threshold:</span>
                            <span className="ml-2 font-medium">{bargeInConfig.energy_threshold || 700} RMS</span>
                        </div>
                        <div>
                            <span className="text-muted-foreground">Minimum Duration:</span>
                            <span className="ml-2 font-medium">{bargeInConfig.min_ms || 150}ms</span>
                        </div>
                        <div>
                            <span className="text-muted-foreground">Post-TTS Protection:</span>
                            <span className="ml-2 font-medium">{bargeInConfig.post_tts_end_protection_ms || 800}ms</span>
                        </div>
                    </div>
                </ConfigCard>
            </ConfigSection>
        </div>
    );
};

export default BargeInPage;

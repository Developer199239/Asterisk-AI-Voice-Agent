import React, { useState, useEffect } from 'react';
import axios from 'axios';
import yaml from 'js-yaml';
import { Save, Wrench } from 'lucide-react';
import { ConfigSection } from '../components/ui/ConfigSection';
import { ConfigCard } from '../components/ui/ConfigCard';
import ToolForm from '../components/config/ToolForm';

const ToolsPage = () => {
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
            alert('Tools configuration saved successfully');
        } catch (err) {
            console.error('Failed to save config', err);
            alert('Failed to save configuration');
        } finally {
            setSaving(false);
        }
    };

    const updateToolsConfig = (newToolsConfig: any) => {
        setConfig({ ...config, tools: newToolsConfig });
    };

    if (loading) return <div className="p-8 text-center text-muted-foreground">Loading configuration...</div>;

    return (
        <div className="space-y-6">
            <div className="flex justify-between items-center">
                <div>
                    <h1 className="text-3xl font-bold tracking-tight">Tools & Capabilities</h1>
                    <p className="text-muted-foreground mt-1">
                        Configure the tools and capabilities available to the AI agent.
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

            <ConfigSection title="Global Tool Settings" description="Configure tools available across all contexts.">
                <ConfigCard>
                    <ToolForm
                        config={config.tools || {}}
                        onChange={updateToolsConfig}
                    />
                </ConfigCard>
            </ConfigSection>
        </div>
    );
};

export default ToolsPage;

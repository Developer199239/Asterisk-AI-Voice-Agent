import React from 'react';

interface ToolsConfigProps {
    config: any;
    onChange: (newConfig: any) => void;
}

const ToolsConfig: React.FC<ToolsConfigProps> = ({ config, onChange }) => {
    const handleChange = (field: string, value: any) => {
        onChange({ ...config, [field]: value });
    };

    const handleNestedChange = (parent: string, field: string, value: any) => {
        onChange({
            ...config,
            [parent]: {
                ...config[parent],
                [field]: value
            }
        });
    };

    return (
        <div className="space-y-6">
            <div className="flex items-center space-x-2">
                <input
                    type="checkbox"
                    id="tools_enabled"
                    className="rounded border-input"
                    checked={config.enabled ?? true}
                    onChange={(e) => handleChange('enabled', e.target.checked)}
                />
                <label htmlFor="tools_enabled" className="text-sm font-medium">Enable Tools</label>
            </div>

            <div className="space-y-4">
                <h3 className="text-lg font-semibold">AI Identity</h3>
                <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                    <div className="space-y-2">
                        <label className="text-sm font-medium">Name</label>
                        <input
                            type="text"
                            className="w-full p-2 rounded border border-input bg-background"
                            value={config.ai_identity?.name || 'AI Agent'}
                            onChange={(e) => handleNestedChange('ai_identity', 'name', e.target.value)}
                        />
                    </div>
                    <div className="space-y-2">
                        <label className="text-sm font-medium">Number</label>
                        <input
                            type="text"
                            className="w-full p-2 rounded border border-input bg-background"
                            value={config.ai_identity?.number || '6789'}
                            onChange={(e) => handleNestedChange('ai_identity', 'number', e.target.value)}
                        />
                    </div>
                </div>
            </div>

            <div className="space-y-4">
                <h3 className="text-lg font-semibold">Transfer Tool</h3>
                <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                    <div className="flex items-center space-x-2">
                        <input
                            type="checkbox"
                            id="transfer_enabled"
                            className="rounded border-input"
                            checked={config.transfer?.enabled ?? true}
                            onChange={(e) => handleNestedChange('transfer', 'enabled', e.target.checked)}
                        />
                        <label htmlFor="transfer_enabled" className="text-sm font-medium">Enable Transfer</label>
                    </div>
                </div>
                {/* Destinations editing could be complex, maybe just JSON for now or a list editor later */}
                <div className="space-y-2">
                    <label className="text-sm font-medium">Destinations (JSON)</label>
                    <textarea
                        className="w-full p-2 rounded border border-input bg-background font-mono text-sm h-32"
                        value={JSON.stringify(config.transfer?.destinations || {}, null, 2)}
                        onChange={(e) => {
                            try {
                                handleNestedChange('transfer', 'destinations', JSON.parse(e.target.value));
                            } catch (err) {
                                // Allow invalid JSON while typing
                            }
                        }}
                    />
                </div>
            </div>

            <div className="space-y-4">
                <h3 className="text-lg font-semibold">Hangup Tool</h3>
                <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                    <div className="flex items-center space-x-2">
                        <input
                            type="checkbox"
                            id="hangup_enabled"
                            className="rounded border-input"
                            checked={config.hangup_call?.enabled ?? true}
                            onChange={(e) => handleNestedChange('hangup_call', 'enabled', e.target.checked)}
                        />
                        <label htmlFor="hangup_enabled" className="text-sm font-medium">Enable Hangup</label>
                    </div>
                    <div className="space-y-2">
                        <label className="text-sm font-medium">Farewell Message</label>
                        <input
                            type="text"
                            className="w-full p-2 rounded border border-input bg-background"
                            value={config.hangup_call?.farewell_message || ''}
                            onChange={(e) => handleNestedChange('hangup_call', 'farewell_message', e.target.value)}
                        />
                    </div>
                </div>
            </div>
        </div>
    );
};

export default ToolsConfig;

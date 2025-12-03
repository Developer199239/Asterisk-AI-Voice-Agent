import React from 'react';

interface AudioSocketConfigProps {
    config: any;
    onChange: (newConfig: any) => void;
}

const AudioSocketConfig: React.FC<AudioSocketConfigProps> = ({ config, onChange }) => {
    const handleChange = (field: string, value: any) => {
        onChange({ ...config, [field]: value });
    };

    return (
        <div className="space-y-6">
            <div>
                <h3 className="text-lg font-semibold mb-2">AudioSocket Configuration</h3>
                <p className="text-sm text-muted-foreground mb-4">
                    Configure AudioSocket transport for legacy TCP-based audio streaming
                </p>
            </div>

            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                <div className="space-y-2">
                    <label className="text-sm font-medium">Format</label>
                    <select
                        className="w-full p-2 rounded border border-input bg-background"
                        value={config.format || 'slin'}
                        onChange={(e) => handleChange('format', e.target.value)}
                    >
                        <option value="slin">SLIN (8kHz PCM)</option>
                        <option value="ulaw">μ-law (8kHz)</option>
                    </select>
                    <p className="text-xs text-muted-foreground">Audio format for AudioSocket stream</p>
                </div>

                <div className="space-y-2">
                    <label className="text-sm font-medium">Host</label>
                    <input
                        type="text"
                        className="w-full p-2 rounded border border-input bg-background"
                        value={config.host || '127.0.0.1'}
                        onChange={(e) => handleChange('host', e.target.value)}
                        placeholder="127.0.0.1"
                    />
                    <p className="text-xs text-muted-foreground">AudioSocket server host address</p>
                </div>

                <div className="space-y-2">
                    <label className="text-sm font-medium">Port</label>
                    <input
                        type="number"
                        className="w-full p-2 rounded border border-input bg-background"
                        value={config.port || 8090}
                        onChange={(e) => handleChange('port', parseInt(e.target.value))}
                        placeholder="8090"
                    />
                    <p className="text-xs text-muted-foreground">AudioSocket server port</p>
                </div>
            </div>

            <div className="mt-4 p-4 bg-muted/50 rounded-lg">
                <p className="text-sm text-muted-foreground">
                    <strong>Note:</strong> AudioSocket is a legacy transport method. For new deployments,
                    consider using External Media (RTP) for better performance and lower latency.
                </p>
            </div>
        </div>
    );
};

export default AudioSocketConfig;

import { useState } from 'react';
import { Plus, Trash2, Settings, Webhook, Search } from 'lucide-react';
import { FormInput, FormSwitch, FormSelect, FormLabel } from '../ui/FormComponents';
import { Modal } from '../ui/Modal';

interface HTTPToolFormProps {
    config: any;
    onChange: (newConfig: any) => void;
    phase: 'pre_call' | 'post_call';
}

interface HTTPToolConfig {
    kind: string;
    phase: string;
    enabled: boolean;
    is_global: boolean;
    timeout_ms: number;
    url: string;
    method: string;
    headers: Record<string, string>;
    query_params?: Record<string, string>;
    body_template?: string;
    payload_template?: string;
    output_variables?: Record<string, string>;
    hold_audio_file?: string;
    hold_audio_threshold_ms?: number;
    generate_summary?: boolean;
    summary_max_words?: number;
}

const DEFAULT_WEBHOOK_PAYLOAD = `{
  "schema_version": 1,
  "event_type": "call_completed",
  "call_id": "{call_id}",
  "caller_number": "{caller_number}",
  "caller_name": "{caller_name}",
  "call_duration": {call_duration},
  "call_outcome": "{call_outcome}",
  "transcript": {transcript_json},
  "context": "{context_name}",
  "provider": "{provider}",
  "timestamp": "{call_end_time}"
}`;

const HTTPToolForm = ({ config, onChange, phase }: HTTPToolFormProps) => {
    const [editingTool, setEditingTool] = useState<string | null>(null);
    const [toolForm, setToolForm] = useState<any>({});
    const [headerKey, setHeaderKey] = useState('');
    const [headerValue, setHeaderValue] = useState('');
    const [outputVarKey, setOutputVarKey] = useState('');
    const [outputVarPath, setOutputVarPath] = useState('');

    const getHTTPTools = () => {
        const tools: Record<string, HTTPToolConfig> = {};
        Object.entries(config || {}).forEach(([key, value]: [string, any]) => {
            if (value && typeof value === 'object' && value.kind && value.phase === phase) {
                tools[key] = value as HTTPToolConfig;
            }
        });
        return tools;
    };

    const httpTools = getHTTPTools();

    const handleAddTool = () => {
        const kind = phase === 'pre_call' ? 'generic_http_lookup' : 'generic_webhook';
        setEditingTool('new_tool');
        setToolForm({
            key: '',
            kind,
            phase,
            enabled: true,
            is_global: phase === 'post_call',
            timeout_ms: phase === 'pre_call' ? 2000 : 5000,
            url: '',
            method: phase === 'pre_call' ? 'GET' : 'POST',
            headers: { 'Content-Type': 'application/json' },
            query_params: {},
            output_variables: {},
            payload_template: phase === 'post_call' ? DEFAULT_WEBHOOK_PAYLOAD : undefined,
        });
    };

    const handleEditTool = (key: string, data: HTTPToolConfig) => {
        setEditingTool(key);
        setToolForm({ key, ...data });
    };

    const handleSaveTool = () => {
        if (!toolForm.key) return;

        const { key, ...data } = toolForm;
        const updated = { ...config };

        if (editingTool !== 'new_tool' && editingTool !== key) {
            delete updated[editingTool!];
        }

        updated[key] = data;
        onChange(updated);
        setEditingTool(null);
    };

    const handleDeleteTool = (key: string) => {
        if (!confirm(`Delete ${key}?`)) return;
        const updated = { ...config };
        delete updated[key];
        onChange(updated);
    };

    const addHeader = () => {
        if (!headerKey) return;
        setToolForm({
            ...toolForm,
            headers: { ...toolForm.headers, [headerKey]: headerValue }
        });
        setHeaderKey('');
        setHeaderValue('');
    };

    const removeHeader = (key: string) => {
        const headers = { ...toolForm.headers };
        delete headers[key];
        setToolForm({ ...toolForm, headers });
    };

    const addOutputVariable = () => {
        if (!outputVarKey) return;
        setToolForm({
            ...toolForm,
            output_variables: { ...toolForm.output_variables, [outputVarKey]: outputVarPath }
        });
        setOutputVarKey('');
        setOutputVarPath('');
    };

    const removeOutputVariable = (key: string) => {
        const vars = { ...toolForm.output_variables };
        delete vars[key];
        setToolForm({ ...toolForm, output_variables: vars });
    };

    const phaseIcon = phase === 'pre_call' ? <Search className="w-4 h-4" /> : <Webhook className="w-4 h-4" />;
    const phaseTitle = phase === 'pre_call' ? 'Pre-Call HTTP Lookups' : 'Post-Call Webhooks';
    const phaseDesc = phase === 'pre_call' 
        ? 'Fetch data from external APIs (CRM, database) before the AI speaks. Output variables are injected into the system prompt.'
        : 'Send call data to external systems (n8n, Make, CRM) after the call ends. Fire-and-forget.';

    return (
        <div className="space-y-4">
            <div className="flex justify-between items-center">
                <div>
                    <h4 className="text-md font-medium flex items-center gap-2">
                        {phaseIcon} {phaseTitle}
                    </h4>
                    <p className="text-xs text-muted-foreground mt-1">{phaseDesc}</p>
                </div>
                <button
                    onClick={handleAddTool}
                    className="text-xs flex items-center bg-primary text-primary-foreground px-3 py-1.5 rounded hover:bg-primary/90 transition-colors"
                >
                    <Plus className="w-3 h-3 mr-1" /> Add {phase === 'pre_call' ? 'Lookup' : 'Webhook'}
                </button>
            </div>

            {Object.keys(httpTools).length === 0 ? (
                <div className="text-sm text-muted-foreground p-4 border border-dashed border-border rounded-lg text-center">
                    No {phase === 'pre_call' ? 'pre-call lookups' : 'post-call webhooks'} configured.
                </div>
            ) : (
                <div className="space-y-2">
                    {Object.entries(httpTools).map(([key, tool]) => (
                        <div key={key} className="flex items-center justify-between p-3 bg-accent/30 rounded border border-border/50">
                            <div className="flex items-center gap-3">
                                <div className={`w-2 h-2 rounded-full ${tool.enabled ? 'bg-green-500' : 'bg-gray-400'}`} />
                                <div>
                                    <div className="font-medium text-sm flex items-center gap-2">
                                        {key}
                                        {tool.is_global && (
                                            <span className="text-xs bg-blue-500/20 text-blue-600 px-1.5 py-0.5 rounded">Global</span>
                                        )}
                                    </div>
                                    <div className="text-xs text-muted-foreground">
                                        {tool.method} • {tool.url ? (tool.url.length > 50 ? tool.url.substring(0, 50) + '...' : tool.url) : 'No URL'}
                                    </div>
                                </div>
                            </div>
                            <div className="flex items-center gap-1">
                                <button 
                                    onClick={() => handleEditTool(key, tool)} 
                                    className="p-1.5 hover:bg-background rounded text-muted-foreground hover:text-foreground"
                                >
                                    <Settings className="w-4 h-4" />
                                </button>
                                <button 
                                    onClick={() => handleDeleteTool(key)} 
                                    className="p-1.5 hover:bg-destructive/10 rounded text-destructive"
                                >
                                    <Trash2 className="w-4 h-4" />
                                </button>
                            </div>
                        </div>
                    ))}
                </div>
            )}

            <Modal
                isOpen={!!editingTool}
                onClose={() => setEditingTool(null)}
                title={editingTool === 'new_tool' ? `Add ${phase === 'pre_call' ? 'HTTP Lookup' : 'Webhook'}` : `Edit ${toolForm.key}`}
                footer={
                    <>
                        <button onClick={() => setEditingTool(null)} className="px-4 py-2 border rounded hover:bg-accent">Cancel</button>
                        <button onClick={handleSaveTool} className="px-4 py-2 bg-primary text-primary-foreground rounded hover:bg-primary/90">Save</button>
                    </>
                }
            >
                <div className="space-y-4 max-h-[60vh] overflow-y-auto pr-2">
                    <FormInput
                        label="Tool Name"
                        value={toolForm.key || ''}
                        onChange={(e) => setToolForm({ ...toolForm, key: e.target.value.replace(/\s/g, '_').toLowerCase() })}
                        placeholder="e.g., crm_lookup or call_webhook"
                        disabled={editingTool !== 'new_tool'}
                    />

                    <div className="grid grid-cols-2 gap-4">
                        <FormSwitch
                            label="Enabled"
                            checked={toolForm.enabled ?? true}
                            onChange={(e) => setToolForm({ ...toolForm, enabled: e.target.checked })}
                        />
                        <FormSwitch
                            label="Global (all contexts)"
                            checked={toolForm.is_global ?? false}
                            onChange={(e) => setToolForm({ ...toolForm, is_global: e.target.checked })}
                        />
                    </div>

                    <FormInput
                        label="URL"
                        value={toolForm.url || ''}
                        onChange={(e) => setToolForm({ ...toolForm, url: e.target.value })}
                        placeholder="https://api.example.com/webhook"
                        tooltip="Use {caller_number}, {call_id}, etc. for variable substitution. Use ${ENV_VAR} for secrets."
                    />

                    <div className="grid grid-cols-2 gap-4">
                        <FormSelect
                            label="Method"
                            options={[
                                { value: 'GET', label: 'GET' },
                                { value: 'POST', label: 'POST' },
                                { value: 'PUT', label: 'PUT' },
                                { value: 'PATCH', label: 'PATCH' },
                            ]}
                            value={toolForm.method || 'POST'}
                            onChange={(e) => setToolForm({ ...toolForm, method: e.target.value })}
                        />
                        <FormInput
                            label="Timeout (ms)"
                            type="number"
                            value={toolForm.timeout_ms || 5000}
                            onChange={(e) => setToolForm({ ...toolForm, timeout_ms: parseInt(e.target.value) })}
                        />
                    </div>

                    {/* Headers */}
                    <div className="space-y-2">
                        <FormLabel>Headers</FormLabel>
                        <div className="space-y-1">
                            {Object.entries(toolForm.headers || {}).map(([k, v]) => (
                                <div key={k} className="flex items-center gap-2 text-xs bg-accent/50 px-2 py-1 rounded">
                                    <span className="font-mono">{k}: {String(v).substring(0, 30)}{String(v).length > 30 ? '...' : ''}</span>
                                    <button onClick={() => removeHeader(k)} className="ml-auto text-destructive hover:text-destructive/80">
                                        <Trash2 className="w-3 h-3" />
                                    </button>
                                </div>
                            ))}
                        </div>
                        <div className="flex gap-2">
                            <input
                                className="flex-1 px-2 py-1 text-sm border rounded"
                                placeholder="Header name"
                                value={headerKey}
                                onChange={(e) => setHeaderKey(e.target.value)}
                            />
                            <input
                                className="flex-1 px-2 py-1 text-sm border rounded"
                                placeholder="Value (use ${VAR} for secrets)"
                                value={headerValue}
                                onChange={(e) => setHeaderValue(e.target.value)}
                            />
                            <button onClick={addHeader} className="px-2 py-1 bg-secondary rounded text-xs hover:bg-secondary/80">
                                <Plus className="w-3 h-3" />
                            </button>
                        </div>
                    </div>

                    {/* Pre-call specific: Output Variables */}
                    {phase === 'pre_call' && (
                        <>
                            <div className="space-y-2">
                                <FormLabel tooltip="Map JSON response paths to variables for prompt injection. Use dot notation like 'contact.name' or 'contacts[0].email'">
                                    Output Variables
                                </FormLabel>
                                <div className="space-y-1">
                                    {Object.entries(toolForm.output_variables || {}).map(([k, v]) => (
                                        <div key={k} className="flex items-center gap-2 text-xs bg-accent/50 px-2 py-1 rounded">
                                            <span className="font-mono">{k} ← {String(v)}</span>
                                            <button onClick={() => removeOutputVariable(k)} className="ml-auto text-destructive hover:text-destructive/80">
                                                <Trash2 className="w-3 h-3" />
                                            </button>
                                        </div>
                                    ))}
                                </div>
                                <div className="flex gap-2">
                                    <input
                                        className="flex-1 px-2 py-1 text-sm border rounded"
                                        placeholder="Variable name (e.g., customer_name)"
                                        value={outputVarKey}
                                        onChange={(e) => setOutputVarKey(e.target.value)}
                                    />
                                    <input
                                        className="flex-1 px-2 py-1 text-sm border rounded"
                                        placeholder="JSON path (e.g., contact.name)"
                                        value={outputVarPath}
                                        onChange={(e) => setOutputVarPath(e.target.value)}
                                    />
                                    <button onClick={addOutputVariable} className="px-2 py-1 bg-secondary rounded text-xs hover:bg-secondary/80">
                                        <Plus className="w-3 h-3" />
                                    </button>
                                </div>
                            </div>

                            <FormInput
                                label="Hold Audio File (optional)"
                                value={toolForm.hold_audio_file || ''}
                                onChange={(e) => setToolForm({ ...toolForm, hold_audio_file: e.target.value })}
                                placeholder="custom/please-wait"
                                tooltip="Asterisk sound file to play while waiting for lookup (if > threshold)"
                            />
                        </>
                    )}

                    {/* Post-call specific: Payload Template + Summary */}
                    {phase === 'post_call' && (
                        <>
                            <div className="border border-border rounded-lg p-3 bg-card/30">
                                <FormSwitch
                                    label="Generate AI Summary"
                                    description="Use OpenAI to generate a concise summary instead of sending full transcript. Requires OPENAI_API_KEY."
                                    checked={toolForm.generate_summary ?? false}
                                    onChange={(e) => setToolForm({ ...toolForm, generate_summary: e.target.checked })}
                                />
                                {toolForm.generate_summary && (
                                    <div className="mt-3">
                                        <FormInput
                                            label="Max Summary Words"
                                            type="number"
                                            value={toolForm.summary_max_words || 100}
                                            onChange={(e) => setToolForm({ ...toolForm, summary_max_words: parseInt(e.target.value) })}
                                            tooltip="Maximum words for the generated summary"
                                        />
                                    </div>
                                )}
                            </div>
                            <div className="space-y-2">
                                <FormLabel tooltip="JSON payload with variable substitution. Available: {call_id}, {caller_number}, {call_duration}, {transcript_json}, {summary}, etc.">
                                    Payload Template
                                </FormLabel>
                                <textarea
                                    className="w-full p-3 rounded-md border border-input bg-transparent text-sm font-mono min-h-[200px] focus:outline-none focus:ring-1 focus:ring-ring"
                                    value={toolForm.payload_template || ''}
                                    onChange={(e) => setToolForm({ ...toolForm, payload_template: e.target.value })}
                                    placeholder={DEFAULT_WEBHOOK_PAYLOAD}
                                />
                            </div>
                        </>
                    )}
                </div>
            </Modal>
        </div>
    );
};

export default HTTPToolForm;

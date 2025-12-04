import { useState, useEffect } from 'react';
import { Cpu, HardDrive, AlertCircle, CheckCircle2, XCircle, Activity, Layers, Box, RefreshCw, ExternalLink } from 'lucide-react';
import { ConfigCard } from './ui/ConfigCard';
import { useNavigate } from 'react-router-dom';
import axios from 'axios';

interface HealthInfo {
    local_ai_server: {
        status: string;
        details: any;
    };
    ai_engine: {
        status: string;
        details: any;
    };
}

interface ModelInfo {
    name: string;
    path: string;
    type: string;
    backend?: string;
    size_mb?: number;
}

interface AvailableModels {
    stt: Record<string, ModelInfo[]>;
    tts: Record<string, ModelInfo[]>;
    llm: ModelInfo[];
}

export const HealthWidget = () => {
    const navigate = useNavigate();
    const [health, setHealth] = useState<HealthInfo | null>(null);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState<string | null>(null);
    const [availableModels, setAvailableModels] = useState<AvailableModels | null>(null);
    const [switching, setSwitching] = useState<string | null>(null);
    const [restartRequired, setRestartRequired] = useState(false);
    const [restarting, setRestarting] = useState(false);

    useEffect(() => {
        const fetchHealth = async () => {
            try {
                const res = await axios.get('/api/system/health');
                setHealth(res.data);
                setError(null);
            } catch (err) {
                console.error('Failed to fetch health', err);
                setError('Failed to load health status');
            } finally {
                setLoading(false);
            }
        };
        fetchHealth();
        // Refresh every 5 seconds
        const interval = setInterval(fetchHealth, 5000);
        return () => clearInterval(interval);
    }, []);

    // Fetch available models
    useEffect(() => {
        const fetchModels = async () => {
            try {
                const res = await axios.get('/api/local-ai/models');
                setAvailableModels(res.data);
            } catch (err) {
                console.error('Failed to fetch available models', err);
            }
        };
        fetchModels();
    }, []);

    const handleSwitchModel = async (modelType: string, backend: string, modelPath?: string, voice?: string) => {
        setSwitching(modelType);
        try {
            const res = await axios.post('/api/local-ai/switch', {
                model_type: modelType,
                backend: backend,
                model_path: modelPath,
                voice: voice
            });
            if (res.data.requires_restart) {
                setRestartRequired(true);
            }
        } catch (err) {
            console.error('Failed to switch model', err);
            alert('Failed to switch model');
        } finally {
            setSwitching(null);
        }
    };

    const handleRestart = async () => {
        setRestarting(true);
        try {
            await axios.post('/api/system/containers/local_ai_server/restart');
            setRestartRequired(false);
            // Wait a bit for restart
            setTimeout(() => {
                setRestarting(false);
            }, 5000);
        } catch (err) {
            console.error('Failed to restart container', err);
            alert('Failed to restart. Go to Docker Services to restart manually.');
            setRestarting(false);
        }
    };

    if (loading) return <div className="animate-pulse h-48 bg-muted rounded-lg mb-6"></div>;

    if (error) {
        return (
            <div className="bg-destructive/10 border border-destructive/20 text-destructive p-4 rounded-md mb-6 flex items-center">
                <AlertCircle className="w-5 h-5 mr-2" />
                {error}
            </div>
        );
    }

    if (!health) return null;

    const renderStatus = (status: string) => {
        if (status === 'connected') return <span className="text-green-500 font-medium flex items-center gap-1"><CheckCircle2 className="w-4 h-4" /> Connected</span>;
        if (status === 'degraded') return <span className="text-yellow-500 font-medium flex items-center gap-1"><Activity className="w-4 h-4" /> Degraded</span>;
        return <span className="text-red-500 font-medium flex items-center gap-1"><XCircle className="w-4 h-4" /> Error</span>;
    };

    const getModelName = (path: string) => {
        if (!path) return 'Unknown';
        const parts = path.split('/');
        return parts[parts.length - 1];
    };

    return (
        <div className="grid grid-cols-1 md:grid-cols-2 gap-6 mb-8">
            {/* Local AI Server Card */}
            <ConfigCard className="p-6">
                <div className="flex justify-between items-start mb-6">
                    <div className="flex items-center gap-4">
                        <div className="p-3 bg-blue-500/10 rounded-xl">
                            <Cpu className="w-6 h-6 text-blue-500" />
                        </div>
                        <div>
                            <h3 className="font-semibold text-lg">Local AI Server</h3>
                            <div className="mt-1">{renderStatus(health.local_ai_server.status)}</div>
                        </div>
                    </div>
                </div>

                {health.local_ai_server.status === 'connected' && (
                    <div className="space-y-4">
                        {/* STT Section */}
                        <div className="space-y-2">
                            <div className="flex justify-between items-center text-sm">
                                <span className="text-muted-foreground font-medium">STT</span>
                                <span className={`px-2 py-1 rounded-md text-xs font-medium ${health.local_ai_server.details.models?.stt?.loaded ? "bg-green-500/10 text-green-500" : "bg-yellow-500/10 text-yellow-500"}`}>
                                    {health.local_ai_server.details.models?.stt?.loaded ? "Loaded" : "Not Loaded"}
                                </span>
                            </div>
                            <div className="flex gap-2">
                                <select
                                    className="flex-1 text-xs p-2 rounded border border-border bg-background"
                                    value={health.local_ai_server.details.models?.stt?.backend || health.local_ai_server.details.stt_backend || 'vosk'}
                                    onChange={(e) => {
                                        const backend = e.target.value;
                                        const models = availableModels?.stt[backend] || [];
                                        const firstModel = models[0];
                                        handleSwitchModel('stt', backend, firstModel?.path);
                                    }}
                                    disabled={switching === 'stt'}
                                >
                                    {availableModels?.stt && Object.entries(availableModels.stt).map(([backend, models]) => (
                                        models.length > 0 && (
                                            <option key={backend} value={backend}>
                                                {backend.charAt(0).toUpperCase() + backend.slice(1)} ({models.length})
                                            </option>
                                        )
                                    ))}
                                </select>
                            </div>
                            <div className="text-xs text-muted-foreground bg-muted/50 p-2 rounded border border-border/50 truncate">
                                {getModelName(health.local_ai_server.details.models?.stt?.path || 'Not configured')}
                            </div>
                        </div>

                        {/* LLM Section */}
                        <div className="space-y-2">
                            <div className="flex justify-between items-center text-sm">
                                <span className="text-muted-foreground font-medium">LLM</span>
                                <span className={`px-2 py-1 rounded-md text-xs font-medium ${health.local_ai_server.details.models?.llm?.loaded ? "bg-green-500/10 text-green-500" : "bg-yellow-500/10 text-yellow-500"}`}>
                                    {health.local_ai_server.details.models?.llm?.loaded ? "Loaded" : "Not Loaded"}
                                </span>
                            </div>
                            <select
                                className="w-full text-xs p-2 rounded border border-border bg-background"
                                value={health.local_ai_server.details.models?.llm?.path || ''}
                                onChange={(e) => handleSwitchModel('llm', '', e.target.value)}
                                disabled={switching === 'llm'}
                            >
                                {availableModels?.llm?.map((model) => (
                                    <option key={model.path} value={model.path}>
                                        {model.name} {model.size_mb ? `(${model.size_mb} MB)` : ''}
                                    </option>
                                ))}
                            </select>
                            <div className="text-xs text-muted-foreground bg-muted/50 p-2 rounded border border-border/50 truncate">
                                {getModelName(health.local_ai_server.details.models?.llm?.path || 'Not configured')}
                            </div>
                        </div>

                        {/* TTS Section */}
                        <div className="space-y-2">
                            <div className="flex justify-between items-center text-sm">
                                <span className="text-muted-foreground font-medium">TTS</span>
                                <span className={`px-2 py-1 rounded-md text-xs font-medium ${health.local_ai_server.details.models?.tts?.loaded ? "bg-green-500/10 text-green-500" : "bg-yellow-500/10 text-yellow-500"}`}>
                                    {health.local_ai_server.details.models?.tts?.loaded ? "Loaded" : "Not Loaded"}
                                </span>
                            </div>
                            <div className="flex gap-2">
                                <select
                                    className="flex-1 text-xs p-2 rounded border border-border bg-background"
                                    value={health.local_ai_server.details.models?.tts?.backend || health.local_ai_server.details.tts_backend || 'piper'}
                                    onChange={(e) => {
                                        const backend = e.target.value;
                                        const models = availableModels?.tts[backend] || [];
                                        const firstModel = models[0];
                                        if (backend === 'kokoro') {
                                            handleSwitchModel('tts', backend, firstModel?.path, 'af_heart');
                                        } else {
                                            handleSwitchModel('tts', backend, firstModel?.path);
                                        }
                                    }}
                                    disabled={switching === 'tts'}
                                >
                                    {availableModels?.tts && Object.entries(availableModels.tts).map(([backend, models]) => (
                                        models.length > 0 && (
                                            <option key={backend} value={backend}>
                                                {backend.charAt(0).toUpperCase() + backend.slice(1)} ({models.length})
                                            </option>
                                        )
                                    ))}
                                </select>
                            </div>
                            <div className="text-xs text-muted-foreground bg-muted/50 p-2 rounded border border-border/50 truncate">
                                {getModelName(health.local_ai_server.details.models?.tts?.path || 'Not configured')}
                            </div>
                        </div>

                        {/* Restart Banner */}
                        {restartRequired && (
                            <div className="bg-yellow-500/10 border border-yellow-500/30 rounded-lg p-3 space-y-2">
                                <div className="flex items-center gap-2 text-yellow-600 dark:text-yellow-400 text-sm font-medium">
                                    <AlertCircle className="w-4 h-4" />
                                    Restart required to apply changes
                                </div>
                                <div className="flex gap-2">
                                    <button
                                        onClick={handleRestart}
                                        disabled={restarting}
                                        className="flex-1 flex items-center justify-center gap-2 px-3 py-1.5 bg-yellow-500 text-white rounded text-xs font-medium hover:bg-yellow-600 disabled:opacity-50"
                                    >
                                        {restarting ? (
                                            <>
                                                <RefreshCw className="w-3 h-3 animate-spin" />
                                                Restarting...
                                            </>
                                        ) : (
                                            <>
                                                <RefreshCw className="w-3 h-3" />
                                                Restart Now
                                            </>
                                        )}
                                    </button>
                                    <button
                                        onClick={() => navigate('/docker')}
                                        className="flex items-center gap-1 px-3 py-1.5 bg-muted text-muted-foreground rounded text-xs font-medium hover:bg-muted/80"
                                    >
                                        <ExternalLink className="w-3 h-3" />
                                        Docker Services
                                    </button>
                                </div>
                            </div>
                        )}
                    </div>
                )}
            </ConfigCard>

            {/* AI Engine Card */}
            <ConfigCard className="p-6">
                <div className="flex justify-between items-start mb-6">
                    <div className="flex items-center gap-4">
                        <div className="p-3 bg-purple-500/10 rounded-xl">
                            <HardDrive className="w-6 h-6 text-purple-500" />
                        </div>
                        <div>
                            <h3 className="font-semibold text-lg">AI Engine</h3>
                            <div className="mt-1">{renderStatus(health.ai_engine.status)}</div>
                        </div>
                    </div>
                </div>

                {(health.ai_engine.status === 'connected' || health.ai_engine.status === 'degraded') && (
                    <div className="space-y-6">
                        {/* ARI Status */}
                        <div className="flex justify-between items-center p-3 bg-muted/30 rounded-lg border border-border/50">
                            <span className="text-sm font-medium text-muted-foreground">ARI Connection</span>
                            <span className={`flex items-center gap-1.5 text-sm font-medium ${health.ai_engine.details.ari_connected ? "text-green-500" : "text-red-500"}`}>
                                <span className={`w-2 h-2 rounded-full ${health.ai_engine.details.ari_connected ? "bg-green-500" : "bg-red-500"}`}></span>
                                {health.ai_engine.details.ari_connected ? "Connected" : "Disconnected"}
                            </span>
                        </div>

                        {/* Pipelines */}
                        <div>
                            <div className="flex items-center gap-2 mb-3">
                                <Layers className="w-4 h-4 text-muted-foreground" />
                                <h4 className="text-sm font-medium text-muted-foreground">Active Pipelines</h4>
                            </div>
                            <div className="grid grid-cols-2 gap-2">
                                {health.ai_engine.details.pipelines ? (
                                    Object.keys(health.ai_engine.details.pipelines).map((pipelineName) => (
                                        <div key={pipelineName} className="text-xs bg-muted/50 p-2 rounded border border-border/50 font-mono">
                                            {pipelineName}
                                        </div>
                                    ))
                                ) : (
                                    <div className="text-xs text-muted-foreground italic col-span-2">No pipelines configured</div>
                                )}
                            </div>
                        </div>

                        {/* Providers */}
                        <div>
                            <div className="flex items-center gap-2 mb-3">
                                <Box className="w-4 h-4 text-muted-foreground" />
                                <h4 className="text-sm font-medium text-muted-foreground">Providers</h4>
                            </div>
                            <div className="space-y-2">
                                {health.ai_engine.details.providers ? (
                                    Object.entries(health.ai_engine.details.providers).map(([name, info]: [string, any]) => (
                                        <div key={name} className="flex justify-between items-center text-sm p-2 rounded hover:bg-muted/50 transition-colors">
                                            <span className="capitalize">{name.replace('_', ' ')}</span>
                                            <span className={`text-xs px-2 py-0.5 rounded-full ${info.ready ? "bg-green-500/10 text-green-500" : "bg-red-500/10 text-red-500"}`}>
                                                {info.ready ? "Ready" : "Not Ready"}
                                            </span>
                                        </div>
                                    ))
                                ) : (
                                    <div className="text-xs text-muted-foreground italic">No providers loaded</div>
                                )}
                            </div>
                        </div>
                    </div>
                )}
            </ConfigCard>
        </div>
    );
};

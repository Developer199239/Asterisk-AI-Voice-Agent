import React, { useState, useEffect } from 'react';
import { Cpu, HardDrive, AlertCircle, CheckCircle2, XCircle, Activity, Layers, Box } from 'lucide-react';
import { ConfigCard } from './ui/ConfigCard';
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

export const HealthWidget = () => {
    const [health, setHealth] = useState<HealthInfo | null>(null);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState<string | null>(null);

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
                        <div className="space-y-3">
                            <div className="flex justify-between items-center text-sm">
                                <span className="text-muted-foreground font-medium">STT Model</span>
                                <span className={`px-2 py-1 rounded-md text-xs font-medium ${health.local_ai_server.details.models?.stt?.loaded ? "bg-green-500/10 text-green-500" : "bg-yellow-500/10 text-yellow-500"}`}>
                                    {health.local_ai_server.details.models?.stt?.loaded ? "Loaded" : "Not Loaded"}
                                </span>
                            </div>
                            {health.local_ai_server.details.models?.stt?.path && (
                                <div className="text-xs text-muted-foreground bg-muted/50 p-2 rounded border border-border/50 truncate">
                                    {getModelName(health.local_ai_server.details.models.stt.path)}
                                </div>
                            )}
                        </div>

                        <div className="space-y-3">
                            <div className="flex justify-between items-center text-sm">
                                <span className="text-muted-foreground font-medium">LLM Model</span>
                                <span className={`px-2 py-1 rounded-md text-xs font-medium ${health.local_ai_server.details.models?.llm?.loaded ? "bg-green-500/10 text-green-500" : "bg-yellow-500/10 text-yellow-500"}`}>
                                    {health.local_ai_server.details.models?.llm?.loaded ? "Loaded" : "Not Loaded"}
                                </span>
                            </div>
                            {health.local_ai_server.details.models?.llm?.path && (
                                <div className="text-xs text-muted-foreground bg-muted/50 p-2 rounded border border-border/50 truncate">
                                    {getModelName(health.local_ai_server.details.models.llm.path)}
                                </div>
                            )}
                        </div>

                        <div className="space-y-3">
                            <div className="flex justify-between items-center text-sm">
                                <span className="text-muted-foreground font-medium">TTS Model</span>
                                <span className={`px-2 py-1 rounded-md text-xs font-medium ${health.local_ai_server.details.models?.tts?.loaded ? "bg-green-500/10 text-green-500" : "bg-yellow-500/10 text-yellow-500"}`}>
                                    {health.local_ai_server.details.models?.tts?.loaded ? "Loaded" : "Not Loaded"}
                                </span>
                            </div>
                            {health.local_ai_server.details.models?.tts?.path && (
                                <div className="text-xs text-muted-foreground bg-muted/50 p-2 rounded border border-border/50 truncate">
                                    {getModelName(health.local_ai_server.details.models.tts.path)}
                                </div>
                            )}
                        </div>
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

import { useState, useEffect } from 'react';
import { HardDrive, Download, Trash2, RefreshCw, CheckCircle2, XCircle, Loader2, Globe, Mic, Volume2, Brain } from 'lucide-react';
import { ConfigSection } from '../../components/ui/ConfigSection';
import { ConfigCard } from '../../components/ui/ConfigCard';
import axios from 'axios';

interface ModelInfo {
    id: string;
    name: string;
    language?: string;
    region?: string;
    backend?: string;
    size_mb: number;
    size_display: string;
    model_path?: string;
    download_url?: string;
    installed?: boolean;
    quality?: string;
    gender?: string;
}

interface InstalledModel {
    name: string;
    path: string;
    size_mb: number;
    type: 'stt' | 'tts' | 'llm';
}

interface Toast {
    id: number;
    message: string;
    type: 'success' | 'error';
}

const ModelsPage = () => {
    const [catalog, setCatalog] = useState<{ stt: ModelInfo[]; tts: ModelInfo[]; llm: ModelInfo[] }>({ stt: [], tts: [], llm: [] });
    const [installedModels, setInstalledModels] = useState<InstalledModel[]>([]);
    const [languageNames, setLanguageNames] = useState<Record<string, string>>({});
    const [regionNames, setRegionNames] = useState<Record<string, string>>({});
    const [loading, setLoading] = useState(true);
    const [downloadingModel, setDownloadingModel] = useState<string | null>(null);
    const [deletingModel, setDeletingModel] = useState<string | null>(null);
    const [selectedTab, setSelectedTab] = useState<'installed' | 'stt' | 'tts' | 'llm'>('installed');
    const [selectedRegion, setSelectedRegion] = useState<string>('all');
    const [toasts, setToasts] = useState<Toast[]>([]);

    const showToast = (message: string, type: 'success' | 'error') => {
        const id = Date.now();
        setToasts(prev => [...prev, { id, message, type }]);
        setTimeout(() => {
            setToasts(prev => prev.filter(t => t.id !== id));
        }, 4000);
    };

    const fetchModels = async () => {
        setLoading(true);
        try {
            // Fetch catalog
            const catalogRes = await axios.get('/api/wizard/local/available-models');
            if (catalogRes.data) {
                setCatalog(catalogRes.data.catalog);
                setLanguageNames(catalogRes.data.language_names || {});
                setRegionNames(catalogRes.data.region_names || {});
            }

            // Fetch installed models
            const installedRes = await axios.get('/api/local-ai/models');
            if (installedRes.data?.models) {
                setInstalledModels(installedRes.data.models);
            }
        } catch (err) {
            console.error('Failed to fetch models', err);
        } finally {
            setLoading(false);
        }
    };

    useEffect(() => {
        fetchModels();
    }, []);

    const handleDownload = async (model: ModelInfo, type: 'stt' | 'tts' | 'llm') => {
        if (!model.download_url) {
            showToast('This model requires an API key and cannot be downloaded', 'error');
            return;
        }

        setDownloadingModel(model.id);
        try {
            await axios.post('/api/wizard/local/download-model', {
                model_id: model.id,
                type: type,
                download_url: model.download_url,
                model_path: model.model_path
            });
            showToast(`Started downloading ${model.name}`, 'success');
            // Poll for completion
            const pollDownload = async () => {
                try {
                    const res = await axios.get('/api/wizard/local/download-progress');
                    if (res.data.completed) {
                        showToast(`${model.name} downloaded successfully!`, 'success');
                        setDownloadingModel(null);
                        fetchModels();
                    } else if (res.data.error) {
                        showToast(`Download failed: ${res.data.error}`, 'error');
                        setDownloadingModel(null);
                    } else if (res.data.running) {
                        setTimeout(pollDownload, 2000);
                    } else {
                        setDownloadingModel(null);
                    }
                } catch (err) {
                    setTimeout(pollDownload, 3000);
                }
            };
            setTimeout(pollDownload, 1000);
        } catch (err: any) {
            showToast(`Failed to start download: ${err.message}`, 'error');
            setDownloadingModel(null);
        }
    };

    const handleDelete = async (model: InstalledModel) => {
        if (!confirm(`Are you sure you want to delete "${model.name}"? This cannot be undone.`)) {
            return;
        }

        setDeletingModel(model.name);
        try {
            await axios.delete('/api/local-ai/models', {
                data: { model_path: model.path, type: model.type }
            });
            showToast(`${model.name} deleted successfully`, 'success');
            fetchModels();
        } catch (err: any) {
            showToast(`Failed to delete model: ${err.message}`, 'error');
        } finally {
            setDeletingModel(null);
        }
    };

    const getTypeIcon = (type: string) => {
        switch (type) {
            case 'stt': return <Mic className="w-4 h-4" />;
            case 'tts': return <Volume2 className="w-4 h-4" />;
            case 'llm': return <Brain className="w-4 h-4" />;
            default: return <HardDrive className="w-4 h-4" />;
        }
    };

    const filterByRegion = (models: ModelInfo[]) => {
        if (selectedRegion === 'all') return models;
        return models.filter(m => m.region === selectedRegion);
    };

    const getUniqueRegions = () => {
        const regions = new Set<string>();
        [...catalog.stt, ...catalog.tts].forEach(m => {
            if (m.region) regions.add(m.region);
        });
        return Array.from(regions);
    };

    const isModelInstalled = (modelPath: string) => {
        return installedModels.some(m => m.path.includes(modelPath) || m.name === modelPath);
    };

    return (
        <div className="p-6 space-y-6">
            {/* Toast notifications */}
            <div className="fixed top-4 right-4 z-50 space-y-2">
                {toasts.map(toast => (
                    <div
                        key={toast.id}
                        className={`px-4 py-3 rounded-lg shadow-lg flex items-center gap-2 ${
                            toast.type === 'success' 
                                ? 'bg-green-600 text-white' 
                                : 'bg-red-600 text-white'
                        }`}
                    >
                        {toast.type === 'success' ? <CheckCircle2 className="w-4 h-4" /> : <XCircle className="w-4 h-4" />}
                        {toast.message}
                    </div>
                ))}
            </div>

            <ConfigSection
                title="Models"
                description="Download and manage STT, TTS, and LLM models for the Local AI Server"
                icon={<HardDrive className="w-5 h-5" />}
            >
                {/* Header with tabs and refresh */}
                <div className="flex justify-between items-center mb-6">
                    <div className="flex gap-2">
                        <button
                            onClick={() => setSelectedTab('installed')}
                            className={`px-4 py-2 rounded-md text-sm font-medium transition-colors ${
                                selectedTab === 'installed'
                                    ? 'bg-primary text-primary-foreground'
                                    : 'bg-muted hover:bg-muted/80'
                            }`}
                        >
                            Installed ({installedModels.length})
                        </button>
                        <button
                            onClick={() => setSelectedTab('stt')}
                            className={`px-4 py-2 rounded-md text-sm font-medium transition-colors flex items-center gap-2 ${
                                selectedTab === 'stt'
                                    ? 'bg-primary text-primary-foreground'
                                    : 'bg-muted hover:bg-muted/80'
                            }`}
                        >
                            <Mic className="w-4 h-4" /> STT ({catalog.stt.length})
                        </button>
                        <button
                            onClick={() => setSelectedTab('tts')}
                            className={`px-4 py-2 rounded-md text-sm font-medium transition-colors flex items-center gap-2 ${
                                selectedTab === 'tts'
                                    ? 'bg-primary text-primary-foreground'
                                    : 'bg-muted hover:bg-muted/80'
                            }`}
                        >
                            <Volume2 className="w-4 h-4" /> TTS ({catalog.tts.length})
                        </button>
                        <button
                            onClick={() => setSelectedTab('llm')}
                            className={`px-4 py-2 rounded-md text-sm font-medium transition-colors flex items-center gap-2 ${
                                selectedTab === 'llm'
                                    ? 'bg-primary text-primary-foreground'
                                    : 'bg-muted hover:bg-muted/80'
                            }`}
                        >
                            <Brain className="w-4 h-4" /> LLM ({catalog.llm.length})
                        </button>
                    </div>
                    <div className="flex gap-2 items-center">
                        {selectedTab !== 'installed' && selectedTab !== 'llm' && (
                            <select
                                value={selectedRegion}
                                onChange={e => setSelectedRegion(e.target.value)}
                                className="px-3 py-2 rounded-md border border-input bg-background text-sm"
                            >
                                <option value="all">All Regions</option>
                                {getUniqueRegions().map(region => (
                                    <option key={region} value={region}>
                                        {regionNames[region] || region}
                                    </option>
                                ))}
                            </select>
                        )}
                        <button
                            onClick={fetchModels}
                            disabled={loading}
                            className="p-2 rounded-md bg-muted hover:bg-muted/80 transition-colors"
                        >
                            <RefreshCw className={`w-4 h-4 ${loading ? 'animate-spin' : ''}`} />
                        </button>
                    </div>
                </div>

                {loading ? (
                    <div className="flex justify-center items-center py-12">
                        <Loader2 className="w-8 h-8 animate-spin text-muted-foreground" />
                    </div>
                ) : (
                    <>
                        {/* Installed Models Tab */}
                        {selectedTab === 'installed' && (
                            <div className="space-y-4">
                                {installedModels.length === 0 ? (
                                    <div className="text-center py-12 text-muted-foreground">
                                        <HardDrive className="w-12 h-12 mx-auto mb-4 opacity-50" />
                                        <p>No models installed yet.</p>
                                        <p className="text-sm mt-2">Browse the STT, TTS, and LLM tabs to download models.</p>
                                    </div>
                                ) : (
                                    <div className="grid gap-4">
                                        {installedModels.map(model => (
                                            <ConfigCard key={model.path}>
                                                <div className="flex justify-between items-center">
                                                    <div className="flex items-center gap-3">
                                                        <div className={`p-2 rounded-lg ${
                                                            model.type === 'stt' ? 'bg-blue-100 dark:bg-blue-900/30 text-blue-600' :
                                                            model.type === 'tts' ? 'bg-green-100 dark:bg-green-900/30 text-green-600' :
                                                            'bg-purple-100 dark:bg-purple-900/30 text-purple-600'
                                                        }`}>
                                                            {getTypeIcon(model.type)}
                                                        </div>
                                                        <div>
                                                            <p className="font-medium">{model.name}</p>
                                                            <p className="text-sm text-muted-foreground">
                                                                {model.type.toUpperCase()} • {model.size_mb} MB
                                                            </p>
                                                        </div>
                                                    </div>
                                                    <button
                                                        onClick={() => handleDelete(model)}
                                                        disabled={deletingModel === model.name}
                                                        className="p-2 rounded-md bg-red-100 dark:bg-red-900/30 text-red-600 hover:bg-red-200 dark:hover:bg-red-900/50 transition-colors"
                                                    >
                                                        {deletingModel === model.name ? (
                                                            <Loader2 className="w-4 h-4 animate-spin" />
                                                        ) : (
                                                            <Trash2 className="w-4 h-4" />
                                                        )}
                                                    </button>
                                                </div>
                                            </ConfigCard>
                                        ))}
                                    </div>
                                )}
                            </div>
                        )}

                        {/* STT Models Tab */}
                        {selectedTab === 'stt' && (
                            <div className="grid gap-4">
                                {filterByRegion(catalog.stt).map(model => (
                                    <ConfigCard key={model.id}>
                                        <div className="flex justify-between items-center">
                                            <div className="flex items-center gap-3">
                                                <div className="p-2 rounded-lg bg-blue-100 dark:bg-blue-900/30 text-blue-600">
                                                    <Mic className="w-4 h-4" />
                                                </div>
                                                <div>
                                                    <div className="flex items-center gap-2">
                                                        <p className="font-medium">{model.name}</p>
                                                        {isModelInstalled(model.model_path || '') && (
                                                            <span className="px-2 py-0.5 text-xs bg-green-100 dark:bg-green-900/30 text-green-600 rounded-full">
                                                                Installed
                                                            </span>
                                                        )}
                                                    </div>
                                                    <p className="text-sm text-muted-foreground">
                                                        {languageNames[model.language || ''] || model.language} • {model.size_display} • {model.backend}
                                                    </p>
                                                </div>
                                            </div>
                                            {!isModelInstalled(model.model_path || '') && model.download_url && (
                                                <button
                                                    onClick={() => handleDownload(model, 'stt')}
                                                    disabled={downloadingModel === model.id}
                                                    className="px-3 py-2 rounded-md bg-blue-600 text-white hover:bg-blue-700 transition-colors flex items-center gap-2 text-sm"
                                                >
                                                    {downloadingModel === model.id ? (
                                                        <Loader2 className="w-4 h-4 animate-spin" />
                                                    ) : (
                                                        <Download className="w-4 h-4" />
                                                    )}
                                                    Download
                                                </button>
                                            )}
                                        </div>
                                    </ConfigCard>
                                ))}
                            </div>
                        )}

                        {/* TTS Models Tab */}
                        {selectedTab === 'tts' && (
                            <div className="grid gap-4">
                                {filterByRegion(catalog.tts).map(model => (
                                    <ConfigCard key={model.id}>
                                        <div className="flex justify-between items-center">
                                            <div className="flex items-center gap-3">
                                                <div className="p-2 rounded-lg bg-green-100 dark:bg-green-900/30 text-green-600">
                                                    <Volume2 className="w-4 h-4" />
                                                </div>
                                                <div>
                                                    <div className="flex items-center gap-2">
                                                        <p className="font-medium">{model.name}</p>
                                                        {model.gender && (
                                                            <span className="px-2 py-0.5 text-xs bg-muted text-muted-foreground rounded-full">
                                                                {model.gender}
                                                            </span>
                                                        )}
                                                        {isModelInstalled(model.model_path || '') && (
                                                            <span className="px-2 py-0.5 text-xs bg-green-100 dark:bg-green-900/30 text-green-600 rounded-full">
                                                                Installed
                                                            </span>
                                                        )}
                                                    </div>
                                                    <p className="text-sm text-muted-foreground">
                                                        {languageNames[model.language || ''] || model.language} • {model.size_display} • {model.quality || 'medium'}
                                                    </p>
                                                </div>
                                            </div>
                                            {!isModelInstalled(model.model_path || '') && model.download_url && (
                                                <button
                                                    onClick={() => handleDownload(model, 'tts')}
                                                    disabled={downloadingModel === model.id}
                                                    className="px-3 py-2 rounded-md bg-green-600 text-white hover:bg-green-700 transition-colors flex items-center gap-2 text-sm"
                                                >
                                                    {downloadingModel === model.id ? (
                                                        <Loader2 className="w-4 h-4 animate-spin" />
                                                    ) : (
                                                        <Download className="w-4 h-4" />
                                                    )}
                                                    Download
                                                </button>
                                            )}
                                        </div>
                                    </ConfigCard>
                                ))}
                            </div>
                        )}

                        {/* LLM Models Tab */}
                        {selectedTab === 'llm' && (
                            <div className="grid gap-4">
                                {catalog.llm.map(model => (
                                    <ConfigCard key={model.id}>
                                        <div className="flex justify-between items-center">
                                            <div className="flex items-center gap-3">
                                                <div className="p-2 rounded-lg bg-purple-100 dark:bg-purple-900/30 text-purple-600">
                                                    <Brain className="w-4 h-4" />
                                                </div>
                                                <div>
                                                    <div className="flex items-center gap-2">
                                                        <p className="font-medium">{model.name}</p>
                                                        {isModelInstalled(model.model_path || '') && (
                                                            <span className="px-2 py-0.5 text-xs bg-green-100 dark:bg-green-900/30 text-green-600 rounded-full">
                                                                Installed
                                                            </span>
                                                        )}
                                                    </div>
                                                    <p className="text-sm text-muted-foreground">
                                                        {model.size_display}
                                                    </p>
                                                </div>
                                            </div>
                                            {!isModelInstalled(model.model_path || '') && model.download_url && (
                                                <button
                                                    onClick={() => handleDownload(model, 'llm')}
                                                    disabled={downloadingModel === model.id}
                                                    className="px-3 py-2 rounded-md bg-purple-600 text-white hover:bg-purple-700 transition-colors flex items-center gap-2 text-sm"
                                                >
                                                    {downloadingModel === model.id ? (
                                                        <Loader2 className="w-4 h-4 animate-spin" />
                                                    ) : (
                                                        <Download className="w-4 h-4" />
                                                    )}
                                                    Download
                                                </button>
                                            )}
                                        </div>
                                    </ConfigCard>
                                ))}
                            </div>
                        )}
                    </>
                )}
            </ConfigSection>
        </div>
    );
};

export default ModelsPage;

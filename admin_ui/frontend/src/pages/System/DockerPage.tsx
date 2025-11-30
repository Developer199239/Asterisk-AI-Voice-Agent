import React, { useState, useEffect } from 'react';
import { Container, RefreshCw, AlertCircle } from 'lucide-react';
import { ConfigSection } from '../../components/ui/ConfigSection';
import { ConfigCard } from '../../components/ui/ConfigCard';
import axios from 'axios';

interface ContainerInfo {
    id: string;
    name: string;
    image: string;
    status: string;
    state: string;
    cpu?: string;
    memory?: string;
    uptime?: string;
}

const DockerPage = () => {
    const [containers, setContainers] = useState<ContainerInfo[]>([]);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState<string | null>(null);
    const [actionLoading, setActionLoading] = useState<string | null>(null);

    const fetchContainers = async () => {
        setLoading(true);
        setError(null);
        try {
            const res = await axios.get('/api/system/containers');
            setContainers(res.data);
        } catch (err: any) {
            console.error('Failed to fetch containers', err);
            setError('Failed to load container status. Ensure Docker is running and the backend has access.');
        } finally {
            setLoading(false);
        }
    };

    useEffect(() => {
        fetchContainers();
    }, []);

    const handleRestart = async (id: string) => {
        setActionLoading(id);
        try {
            await axios.post(`/api/system/containers/${id}/restart`);
            await fetchContainers();
        } catch (err: any) {
            alert('Failed to restart container: ' + (err.response?.data?.detail || err.message));
        } finally {
            setActionLoading(null);
        }
    };

    const getStatusColor = (status: string) => {
        if (status.includes('running')) return 'bg-green-500/10 text-green-500 border-green-500/20';
        if (status.includes('exited')) return 'bg-red-500/10 text-red-500 border-red-500/20';
        return 'bg-gray-500/10 text-gray-500 border-gray-500/20';
    };

    return (
        <div className="space-y-6">
            <div className="flex justify-between items-center">
                <div>
                    <h1 className="text-3xl font-bold tracking-tight">Docker Containers</h1>
                    <p className="text-muted-foreground mt-1">
                        Monitor and manage the containerized services.
                    </p>
                </div>
                <button
                    onClick={fetchContainers}
                    disabled={loading}
                    className="inline-flex items-center justify-center whitespace-nowrap rounded-md text-sm font-medium transition-colors focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring disabled:pointer-events-none disabled:opacity-50 border border-input bg-background shadow-sm hover:bg-accent hover:text-accent-foreground h-9 px-4 py-2"
                >
                    <RefreshCw className={`w-4 h-4 mr-2 ${loading ? 'animate-spin' : ''}`} />
                    Refresh
                </button>
            </div>

            {error && (
                <div className="bg-destructive/10 border border-destructive/20 text-destructive p-4 rounded-md flex items-center">
                    <AlertCircle className="w-5 h-5 mr-2" />
                    {error}
                </div>
            )}

            <ConfigSection title="Service Status" description="Current state of system containers.">
                <div className="grid gap-4">
                    {loading && containers.length === 0 ? (
                        <div className="text-center p-8 text-muted-foreground">Loading container status...</div>
                    ) : containers.length === 0 && !error ? (
                        <div className="text-center p-8 text-muted-foreground">No containers found.</div>
                    ) : (
                        containers.map(container => (
                            <ConfigCard key={container.id} className="flex items-center justify-between p-4">
                                <div className="flex items-center gap-4">
                                    <div className="p-3 bg-primary/10 rounded-lg">
                                        <Container className="w-6 h-6 text-primary" />
                                    </div>
                                    <div>
                                        <h4 className="font-semibold text-lg">{container.name.replace(/^\//, '')}</h4>
                                        <p className="text-sm text-muted-foreground font-mono">{container.image}</p>
                                    </div>
                                </div>

                                <div className="flex items-center gap-8">
                                    <div className={`px-2.5 py-0.5 rounded-full text-xs font-medium border ${getStatusColor(container.status)}`}>
                                        {container.status.toUpperCase()}
                                    </div>
                                    <div className="flex items-center gap-1">
                                        <button
                                            onClick={() => handleRestart(container.id)}
                                            disabled={actionLoading === container.id}
                                            className="p-2 hover:bg-accent rounded-md text-muted-foreground hover:text-foreground disabled:opacity-50"
                                            title="Restart"
                                        >
                                            <RefreshCw className={`w-4 h-4 ${actionLoading === container.id ? 'animate-spin' : ''}`} />
                                        </button>
                                    </div>
                                </div>
                            </ConfigCard>
                        ))
                    )}
                </div>
            </ConfigSection>
        </div>
    );
};

export default DockerPage;

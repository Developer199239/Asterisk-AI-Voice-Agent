import React, { useState, useEffect } from 'react';
import { Activity, Cpu, HardDrive, RefreshCw } from 'lucide-react';
import axios from 'axios';
import { HealthWidget } from '../components/HealthWidget';

interface Container {
    id: string;
    name: string;
    status: string;
    state: string;
}

interface SystemMetrics {
    cpu: {
        percent: number;
        count: number;
    };
    memory: {
        total: number;
        available: number;
        percent: number;
        used: number;
    };
    disk: {
        total: number;
        free: number;
        percent: number;
    };
}

const Dashboard = () => {
    const [containers, setContainers] = useState<Container[]>([]);
    const [metrics, setMetrics] = useState<SystemMetrics | null>(null);
    const [loading, setLoading] = useState(true);
    const [refreshing, setRefreshing] = useState(false);

    const [error, setError] = useState<string | null>(null);
    const [errorDetails, setErrorDetails] = useState<string | null>(null);

    const fetchData = async () => {
        try {
            setError(null);
            setErrorDetails(null);
            const [containersRes, metricsRes] = await Promise.all([
                axios.get('/api/system/containers'),
                axios.get('/api/system/metrics')
            ]);
            setContainers(containersRes.data);
            setMetrics(metricsRes.data);
        } catch (err: any) {
            console.error('Failed to fetch dashboard data:', err);
            setError('Failed to connect to backend system API. Ensure the backend is running and Docker socket is reachable.');
            setErrorDetails(err?.message || JSON.stringify(err));
        } finally {
            setLoading(false);
            setRefreshing(false);
        }
    };

    useEffect(() => {
        fetchData();
        const interval = setInterval(fetchData, 5000); // Refresh every 5s
        return () => clearInterval(interval);
    }, []);

    const formatBytes = (bytes: number) => {
        if (bytes === 0) return '0 B';
        const k = 1024;
        const sizes = ['B', 'KB', 'MB', 'GB', 'TB'];
        const i = Math.floor(Math.log(bytes) / Math.log(k));
        return parseFloat((bytes / Math.pow(k, i)).toFixed(2)) + ' ' + sizes[i];
    };

    const MetricCard = ({ title, value, subValue, icon: Icon, color }: any) => (
        <div className="p-6 rounded-lg border border-border bg-card text-card-foreground shadow-sm">
            <div className="flex items-center justify-between mb-4">
                <h3 className="text-sm font-medium text-muted-foreground">{title}</h3>
                <Icon className={`w-4 h-4 ${color}`} />
            </div>
            <div className="text-2xl font-bold">{value}</div>
            {subValue && <p className="text-xs text-muted-foreground mt-1">{subValue}</p>}
        </div>
    );

    if (loading) {
        return (
            <div className="flex items-center justify-center h-full">
                <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-primary"></div>
            </div>
        );
    }

    if (error) {
        return (
            <div className="flex flex-col items-center justify-center h-full space-y-4">
                <div className="text-destructive text-center max-w-xl">
                    <h2 className="text-xl font-bold mb-2">Error Loading Dashboard</h2>
                    <p className="mb-2">{error}</p>
                    {errorDetails && <p className="text-xs text-muted-foreground break-all">Details: {errorDetails}</p>}
                    <p className="text-sm text-muted-foreground">If running locally, ensure Docker is running and that admin-ui can access /var/run/docker.sock.</p>
                </div>
                <button
                    onClick={() => { setError(null); setErrorDetails(null); setLoading(true); fetchData(); }}
                    className="px-4 py-2 rounded-md bg-primary text-primary-foreground hover:bg-primary/90"
                >
                    Retry
                </button>
            </div>
        );
    }

    return (
        <div className="space-y-8">
            <div className="flex justify-between items-center">
                <h1 className="text-3xl font-bold tracking-tight">Dashboard</h1>
                <button
                    onClick={() => { setRefreshing(true); fetchData(); }}
                    className="p-2 rounded-md hover:bg-accent hover:text-accent-foreground transition-colors"
                    disabled={refreshing}
                >
                    <RefreshCw className={`w-5 h-5 ${refreshing ? 'animate-spin' : ''}`} />
                </button>
            </div>

            {/* Health Widget */}
            <HealthWidget />

            {/* System Metrics */}
            <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
                <MetricCard
                    title="CPU Usage"
                    value={`${metrics?.cpu.percent.toFixed(1)}%`}
                    subValue={`${metrics?.cpu.count} Cores`}
                    icon={Cpu}
                    color="text-blue-500"
                />
                <MetricCard
                    title="Memory Usage"
                    value={`${metrics?.memory.percent.toFixed(1)}%`}
                    subValue={`${formatBytes(metrics?.memory.used || 0)} / ${formatBytes(metrics?.memory.total || 0)}`}
                    icon={Activity}
                    color="text-green-500"
                />
                <MetricCard
                    title="Disk Usage"
                    value={`${metrics?.disk.percent.toFixed(1)}%`}
                    subValue={`${formatBytes(metrics?.disk.free || 0)} Free`}
                    icon={HardDrive}
                    color="text-orange-500"
                />
            </div>
        </div>
    );
};

export default Dashboard;

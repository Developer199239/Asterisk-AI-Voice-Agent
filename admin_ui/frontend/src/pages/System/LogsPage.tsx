import React, { useState, useEffect, useRef } from 'react';
import axios from 'axios';
import { RefreshCw, Pause, Play, Terminal } from 'lucide-react';
import { useSearchParams } from 'react-router-dom';
import { parseAnsi } from '../../utils/ansi';

const LogsPage = () => {
    const [searchParams, setSearchParams] = useSearchParams();
    const [logs, setLogs] = useState('');
    const [loading, setLoading] = useState(false);
    const [autoRefresh, setAutoRefresh] = useState(true);
    const [container, setContainer] = useState(searchParams.get('container') || 'ai_engine');
    const logsEndRef = useRef<HTMLDivElement>(null);

    const fetchLogs = async () => {
        setLoading(true);
        try {
            const res = await axios.get(`/api/logs/${container}?tail=500`);
            setLogs(res.data.logs);
        } catch (err: any) {
            console.error("Failed to fetch logs", err);
            setLogs(`Failed to fetch logs for ${container}. Ensure the container is running and backend can access Docker. Details: ${err?.message || err}`);
        } finally {
            setLoading(false);
        }
    };

    useEffect(() => {
        fetchLogs();
        const interval = setInterval(() => {
            if (autoRefresh) {
                fetchLogs();
            }
        }, 3000);
        return () => clearInterval(interval);
    }, [autoRefresh, container]);

    useEffect(() => {
        if (autoRefresh) {
            logsEndRef.current?.scrollIntoView({ behavior: "smooth" });
        }
    }, [logs, autoRefresh]);

    return (
        <div className="space-y-6 h-[calc(100vh-140px)] flex flex-col">
            <div className="flex justify-between items-center flex-shrink-0">
                <div>
                    <h1 className="text-3xl font-bold tracking-tight">System Logs</h1>
                    <p className="text-muted-foreground mt-1">
                        Real-time logs from system services.
                    </p>
                </div>
                <div className="flex space-x-2 items-center">
                    <button
                        onClick={async () => {
                            try {
                                const response = await axios.get('/api/config/export-logs', { responseType: 'blob' });
                                const url = window.URL.createObjectURL(new Blob([response.data]));
                                const link = document.createElement('a');
                                link.href = url;
                                link.setAttribute('download', `debug-logs-${new Date().toISOString().slice(0, 19).replace(/[:T]/g, '-')}.zip`);
                                document.body.appendChild(link);
                                link.click();
                                link.remove();
                            } catch (err) {
                                console.error('Failed to export logs', err);
                                alert('Failed to export logs');
                            }
                        }}
                        className="inline-flex items-center justify-center whitespace-nowrap rounded-md text-sm font-medium transition-colors focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring disabled:pointer-events-none disabled:opacity-50 border border-input bg-background shadow-sm hover:bg-accent hover:text-accent-foreground h-9 px-3"
                        title="Export Logs & Config for Debugging"
                    >
                        <span className="mr-2">Export</span>
                        <Terminal className="w-4 h-4" />
                    </button>

                    <select
                        className="h-9 rounded-md border border-input bg-background px-3 py-1 text-sm shadow-sm transition-colors focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
                        value={container}
                        onChange={e => {
                            setContainer(e.target.value);
                            setSearchParams({ container: e.target.value });
                        }}
                    >
                        <option value="ai_engine">AI Engine</option>
                        <option value="local_ai_server">Local AI Server</option>
                        <option value="admin_ui">Admin UI</option>
                    </select>

                    <button
                        onClick={() => setAutoRefresh(!autoRefresh)}
                        className={`inline-flex items-center justify-center whitespace-nowrap rounded-md text-sm font-medium transition-colors focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring disabled:pointer-events-none disabled:opacity-50 h-9 px-3 shadow-sm ${autoRefresh
                            ? 'bg-primary text-primary-foreground hover:bg-primary/90'
                            : 'border border-input bg-background hover:bg-accent hover:text-accent-foreground'
                            }`}
                        title={autoRefresh ? "Pause Auto-refresh" : "Resume Auto-refresh"}
                    >
                        {autoRefresh ? <Pause className="w-4 h-4 mr-2" /> : <Play className="w-4 h-4 mr-2" />}
                        {autoRefresh ? 'Live' : 'Paused'}
                    </button>

                    <button
                        onClick={fetchLogs}
                        className="inline-flex items-center justify-center whitespace-nowrap rounded-md text-sm font-medium transition-colors focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring disabled:pointer-events-none disabled:opacity-50 border border-input bg-background shadow-sm hover:bg-accent hover:text-accent-foreground h-9 px-3"
                        title="Refresh Now"
                    >
                        <RefreshCw className={`w-4 h-4 ${loading ? 'animate-spin' : ''}`} />
                    </button>
                </div>
            </div>

            <div className="flex-1 min-h-0 border rounded-lg bg-[#09090b] text-gray-300 font-mono text-xs p-4 overflow-auto shadow-inner relative">
                <div className="absolute top-2 right-2 opacity-50 pointer-events-none">
                    <Terminal className="w-6 h-6" />
                </div>
                <pre className="whitespace-pre-wrap break-all">
                    {logs ? parseAnsi(logs) : "No logs available..."}
                </pre>
                <div ref={logsEndRef} />
            </div>
        </div>
    );
};

export default LogsPage;

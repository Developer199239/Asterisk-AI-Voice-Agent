import React, { useMemo, useState, useEffect, useRef } from 'react';
import axios from 'axios';
import { RefreshCw, Pause, Play, Terminal } from 'lucide-react';
import { useSearchParams } from 'react-router-dom';
import { parseAnsi } from '../../utils/ansi';

type LogLevel = 'error' | 'warning' | 'info' | 'debug';
type LogCategory = 'call' | 'provider' | 'audio' | 'transport' | 'vad' | 'tools' | 'config';

type LogEvent = {
    ts: string | null;
    level: LogLevel;
    msg: string;
    component: string | null;
    call_id: string | null;
    provider: string | null;
    context: string | null;
    pipeline: string | null;
    category: LogCategory;
    milestone: boolean;
    raw: string;
};

type Preset = 'important' | 'audio' | 'provider' | 'transport' | 'vad' | 'tools' | 'config';

const PRESET_DEFAULT_LEVELS: Record<Preset, LogLevel[]> = {
    important: ['error', 'warning', 'info'],
    audio: ['error', 'warning', 'info'],
    provider: ['error', 'warning', 'info'],
    transport: ['error', 'warning', 'info'],
    vad: ['error', 'warning', 'info'],
    tools: ['error', 'warning', 'info'],
    config: ['error', 'warning', 'info'],
};

const PRESET_DEFAULT_CATEGORIES: Record<Preset, LogCategory[] | null> = {
    important: null, // all categories, backend will tag milestones
    audio: ['audio'],
    provider: ['provider'],
    transport: ['transport'],
    vad: ['vad'],
    tools: ['tools'],
    config: ['config'],
};

const LogsPage = () => {
    const [searchParams, setSearchParams] = useSearchParams();
    const [logs, setLogs] = useState('');
    const [events, setEvents] = useState<LogEvent[]>([]);
    const [loading, setLoading] = useState(false);
    const [autoRefresh, setAutoRefresh] = useState(true);
    const [container, setContainer] = useState(searchParams.get('container') || 'ai_engine');
    const [mode, setMode] = useState<'events' | 'raw'>((searchParams.get('mode') as any) || 'events');
    const [preset, setPreset] = useState<Preset>((searchParams.get('preset') as any) || 'important');
    const [callId, setCallId] = useState(searchParams.get('call_id') || '');
    const [q, setQ] = useState(searchParams.get('q') || '');
    const [hidePayloads, setHidePayloads] = useState(searchParams.get('hide_payloads') !== 'false');
    const [since, setSince] = useState(searchParams.get('since') || '');
    const [until, setUntil] = useState(searchParams.get('until') || '');
    const [levels, setLevels] = useState<LogLevel[]>(PRESET_DEFAULT_LEVELS[preset]);
    const [categories, setCategories] = useState<LogCategory[] | null>(PRESET_DEFAULT_CATEGORIES[preset]);
    const logsEndRef = useRef<HTMLDivElement>(null);

    const updateUrlParams = (next: Record<string, string>) => {
        const merged: Record<string, string> = {};
        searchParams.forEach((v, k) => (merged[k] = v));
        Object.entries(next).forEach(([k, v]) => {
            if (!v) delete merged[k];
            else merged[k] = v;
        });
        setSearchParams(merged);
    };

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

    const fetchEvents = async () => {
        setLoading(true);
        try {
            const params: Record<string, any> = {
                limit: 500,
                hide_payloads: hidePayloads,
            };
            if (callId.trim()) params.call_id = callId.trim();
            if (q.trim()) params.q = q.trim();
            if (levels.length) params.levels = levels;
            if (categories && categories.length) params.categories = categories;
            if (since.trim()) params.since = since.trim();
            if (until.trim()) params.until = until.trim();

            const res = await axios.get(`/api/logs/${container}/events`, { params });
            setEvents(res.data.events || []);
        } catch (err: any) {
            console.error("Failed to fetch events", err);
            setEvents([]);
            setLogs(`Failed to fetch log events for ${container}. Details: ${err?.message || err}`);
        } finally {
            setLoading(false);
        }
    };

    useEffect(() => {
        if (mode === 'events') fetchEvents();
        else fetchLogs();
        const interval = setInterval(() => {
            if (autoRefresh) {
                if (mode === 'events') fetchEvents();
                else fetchLogs();
            }
        }, 3000);
        return () => clearInterval(interval);
    }, [autoRefresh, container, mode, callId, q, hidePayloads, since, until, levels.join(','), (categories || []).join(',')]);

    useEffect(() => {
        if (autoRefresh) {
            logsEndRef.current?.scrollIntoView({ behavior: "smooth" });
        }
    }, [logs, events, autoRefresh]);

    useEffect(() => {
        // Apply preset defaults when preset changes (without stomping URL-provided customizations on first load)
        setLevels(PRESET_DEFAULT_LEVELS[preset]);
        setCategories(PRESET_DEFAULT_CATEGORIES[preset]);
    }, [preset]);

    const filteredEvents = useMemo(() => {
        if (mode !== 'events') return [];
        if (preset !== 'important') return events;
        // Important Only: show all warnings/errors, and info milestones only
        return events.filter(e => {
            if (e.level === 'error' || e.level === 'warning') return true;
            if (e.level === 'info' && e.milestone) return true;
            return false;
        });
    }, [events, mode, preset]);

    const levelBadge = (lvl: LogLevel) => {
        const cls =
            lvl === 'error' ? 'bg-red-600/20 text-red-300 border-red-800' :
            lvl === 'warning' ? 'bg-yellow-600/20 text-yellow-200 border-yellow-800' :
            lvl === 'info' ? 'bg-blue-600/20 text-blue-200 border-blue-800' :
            'bg-gray-600/20 text-gray-200 border-gray-700';
        return <span className={`inline-flex items-center rounded border px-2 py-0.5 text-[10px] ${cls}`}>{lvl.toUpperCase()}</span>;
    };

    return (
        <div className="space-y-6 h-[calc(100vh-140px)] flex flex-col">
            <div className="flex justify-between items-center flex-shrink-0">
                <div>
                    <h1 className="text-3xl font-bold tracking-tight">System Logs</h1>
                    <p className="text-muted-foreground mt-1">
                        Real-time logs from system services (raw) and a filterable Events view for troubleshooting.
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
                            updateUrlParams({ container: e.target.value });
                        }}
                    >
                        <option value="ai_engine">AI Engine</option>
                        <option value="local_ai_server">Local AI Server</option>
                        <option value="admin_ui">Admin UI</option>
                    </select>

                    <select
                        className="h-9 rounded-md border border-input bg-background px-3 py-1 text-sm shadow-sm transition-colors focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
                        value={mode}
                        onChange={e => {
                            const nextMode = e.target.value as any;
                            setMode(nextMode);
                            updateUrlParams({ mode: nextMode });
                        }}
                        title="Logs Mode"
                    >
                        <option value="events">Events</option>
                        <option value="raw">Raw</option>
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
                        onClick={() => {
                            if (mode === 'events') fetchEvents();
                            else fetchLogs();
                        }}
                        className="inline-flex items-center justify-center whitespace-nowrap rounded-md text-sm font-medium transition-colors focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring disabled:pointer-events-none disabled:opacity-50 border border-input bg-background shadow-sm hover:bg-accent hover:text-accent-foreground h-9 px-3"
                        title="Refresh Now"
                    >
                        <RefreshCw className={`w-4 h-4 ${loading ? 'animate-spin' : ''}`} />
                    </button>
                </div>
            </div>

            {mode === 'events' && (
                <div className="flex flex-wrap items-center gap-2 border rounded-lg p-3 bg-background">
                    <div className="flex items-center gap-2">
                        <span className="text-xs text-muted-foreground">Preset</span>
                        <select
                            className="h-8 rounded-md border border-input bg-background px-2 py-1 text-xs"
                            value={preset}
                            onChange={e => {
                                const nextPreset = e.target.value as Preset;
                                setPreset(nextPreset);
                                updateUrlParams({ preset: nextPreset });
                            }}
                        >
                            <option value="important">Important Only</option>
                            <option value="audio">Audio Quality</option>
                            <option value="provider">Provider Session</option>
                            <option value="transport">Transport</option>
                            <option value="vad">Barge-in / VAD</option>
                            <option value="tools">Tools / MCP</option>
                            <option value="config">Config</option>
                        </select>
                    </div>

                    <div className="flex items-center gap-2">
                        <span className="text-xs text-muted-foreground">Call ID</span>
                        <input
                            className="h-8 w-[280px] rounded-md border border-input bg-background px-2 py-1 text-xs"
                            placeholder="e.g. 1766692793.2077"
                            value={callId}
                            onChange={e => {
                                setCallId(e.target.value);
                                updateUrlParams({ call_id: e.target.value });
                            }}
                        />
                    </div>

                    <div className="flex items-center gap-2">
                        <span className="text-xs text-muted-foreground">Search</span>
                        <input
                            className="h-8 w-[240px] rounded-md border border-input bg-background px-2 py-1 text-xs"
                            placeholder="text match…"
                            value={q}
                            onChange={e => {
                                setQ(e.target.value);
                                updateUrlParams({ q: e.target.value });
                            }}
                        />
                    </div>

                    <div className="flex items-center gap-2">
                        <span className="text-xs text-muted-foreground">Since</span>
                        <input
                            className="h-8 w-[240px] rounded-md border border-input bg-background px-2 py-1 text-xs"
                            placeholder="ISO8601 (optional)"
                            value={since}
                            onChange={e => {
                                setSince(e.target.value);
                                updateUrlParams({ since: e.target.value });
                            }}
                        />
                    </div>

                    <div className="flex items-center gap-2">
                        <span className="text-xs text-muted-foreground">Until</span>
                        <input
                            className="h-8 w-[240px] rounded-md border border-input bg-background px-2 py-1 text-xs"
                            placeholder="ISO8601 (optional)"
                            value={until}
                            onChange={e => {
                                setUntil(e.target.value);
                                updateUrlParams({ until: e.target.value });
                            }}
                        />
                    </div>

                    <label className="flex items-center gap-2 text-xs">
                        <input
                            type="checkbox"
                            checked={hidePayloads}
                            onChange={e => {
                                setHidePayloads(e.target.checked);
                                updateUrlParams({ hide_payloads: e.target.checked ? 'true' : 'false' });
                            }}
                        />
                        Hide transcripts / payloads
                    </label>
                </div>
            )}

            <div className="flex-1 min-h-0 border rounded-lg bg-[#09090b] text-gray-300 font-mono text-xs p-4 overflow-auto shadow-inner relative">
                <div className="absolute top-2 right-2 opacity-50 pointer-events-none">
                    <Terminal className="w-6 h-6" />
                </div>
                {mode === 'events' ? (
                    <div className="space-y-1">
                        {(filteredEvents.length ? filteredEvents : []).map((e, idx) => (
                            <div key={idx} className="flex gap-2 items-start hover:bg-white/5 px-2 py-1 rounded">
                                <div className="w-[90px] text-gray-500 shrink-0">
                                    {e.ts ? new Date(e.ts).toLocaleTimeString() : '--:--:--'}
                                </div>
                                <div className="shrink-0">{levelBadge(e.level)}</div>
                                <div className="shrink-0">
                                    <span className="inline-flex items-center rounded border border-gray-700 px-2 py-0.5 text-[10px] text-gray-200 bg-gray-600/10">
                                        {e.category}
                                    </span>
                                </div>
                                <div className="flex-1 break-words">
                                    <div className="text-gray-200">{e.msg}</div>
                                    <div className="text-[10px] text-gray-500 mt-0.5">
                                        {e.call_id ? `call_id=${e.call_id} ` : ''}{e.provider ? `provider=${e.provider} ` : ''}{e.context ? `context=${e.context} ` : ''}{e.component ? `component=${e.component}` : ''}
                                    </div>
                                </div>
                            </div>
                        ))}
                        {!filteredEvents.length && (
                            <div className="text-gray-400">No events match the current filters.</div>
                        )}
                    </div>
                ) : (
                    <pre className="whitespace-pre-wrap break-all">
                        {logs ? parseAnsi(logs) : "No logs available..."}
                    </pre>
                )}
                <div ref={logsEndRef} />
            </div>
        </div>
    );
};

export default LogsPage;

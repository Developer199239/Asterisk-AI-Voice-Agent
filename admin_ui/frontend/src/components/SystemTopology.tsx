import { useState, useEffect, useMemo } from 'react';
import { Activity, Phone, Cpu, Server, Mic, MessageSquare, Volume2, Zap, Radio } from 'lucide-react';
import axios from 'axios';
import yaml from 'js-yaml';

interface CallState {
  call_id: string;
  started_at: Date;
  provider?: string;
  pipeline?: string;
  state: 'arriving' | 'connected' | 'processing';
}

interface ProviderConfig {
  name: string;
  type: 'monolithic' | 'pipeline_component';
}

interface PipelineConfig {
  name: string;
  stt?: string;
  llm?: string;
  tts?: string;
}

interface LocalAIModels {
  stt?: { backend: string; loaded: boolean; path?: string };
  llm?: { loaded: boolean; path?: string };
  tts?: { backend: string; loaded: boolean; path?: string };
}

interface TopologyState {
  aiEngineStatus: 'connected' | 'error' | 'unknown';
  localAIStatus: 'connected' | 'error' | 'unknown';
  localAIModels: LocalAIModels | null;
  configuredProviders: ProviderConfig[];
  configuredPipelines: PipelineConfig[];
  defaultProvider: string | null;
  activePipeline: string | null;
  activeCalls: Map<string, CallState>;
}

// Known monolithic providers (full agents that handle STT+LLM+TTS internally)
const MONOLITHIC_PROVIDERS = ['deepgram', 'openai_realtime', 'google_live', 'elevenlabs_agent'];

export const SystemTopology = () => {
  const [state, setState] = useState<TopologyState>({
    aiEngineStatus: 'unknown',
    localAIStatus: 'unknown',
    localAIModels: null,
    configuredProviders: [],
    configuredPipelines: [],
    defaultProvider: null,
    activePipeline: null,
    activeCalls: new Map(),
  });
  const [loading, setLoading] = useState(true);

  // Fetch health status
  useEffect(() => {
    const fetchHealth = async () => {
      try {
        const res = await axios.get('/api/system/health');
        setState(prev => ({
          ...prev,
          aiEngineStatus: res.data.ai_engine?.status === 'connected' ? 'connected' : 'error',
          localAIStatus: res.data.local_ai_server?.status === 'connected' ? 'connected' : 'error',
          localAIModels: res.data.local_ai_server?.details?.models || null,
        }));
      } catch {
        setState(prev => ({
          ...prev,
          aiEngineStatus: 'error',
          localAIStatus: 'error',
        }));
      }
    };
    fetchHealth();
    const interval = setInterval(fetchHealth, 5000);
    return () => clearInterval(interval);
  }, []);

  // Fetch config (providers, pipelines)
  useEffect(() => {
    const fetchConfig = async () => {
      try {
        const res = await axios.get('/api/config/yaml');
        const parsed = yaml.load(res.data.content) as any;
        
        // Extract providers
        const providers: ProviderConfig[] = [];
        if (parsed?.providers && typeof parsed.providers === 'object') {
          for (const [name] of Object.entries(parsed.providers)) {
            providers.push({
              name,
              type: MONOLITHIC_PROVIDERS.includes(name) ? 'monolithic' : 'pipeline_component',
            });
          }
        }

        // Extract pipelines
        const pipelines: PipelineConfig[] = [];
        if (parsed?.pipelines && typeof parsed.pipelines === 'object') {
          for (const [name, config] of Object.entries(parsed.pipelines)) {
            const cfg = config as any;
            pipelines.push({
              name,
              stt: cfg?.stt?.provider,
              llm: cfg?.llm?.provider,
              tts: cfg?.tts?.provider,
            });
          }
        }

        setState(prev => ({
          ...prev,
          configuredProviders: providers,
          configuredPipelines: pipelines,
          defaultProvider: parsed?.default_provider || null,
          activePipeline: parsed?.active_pipeline || null,
        }));
        setLoading(false);
      } catch {
        setLoading(false);
      }
    };
    fetchConfig();
    const interval = setInterval(fetchConfig, 10000);
    return () => clearInterval(interval);
  }, []);

  // Poll for active calls from logs
  useEffect(() => {
    const fetchCallEvents = async () => {
      try {
        const res = await axios.get('/api/logs/ai_engine/events', {
          params: { limit: 100, since: '60s' }
        });
        
        const events = res.data.events || [];
        const calls = new Map<string, CallState>(state.activeCalls);
        const now = new Date();
        
        // Track which calls we've seen end
        const endedCalls = new Set<string>();
        
        for (const event of events) {
          const msg = (event.msg || '').toLowerCase();
          const callId = event.call_id;
          
          if (!callId) continue;
          
          // Detect call start
          if (msg.includes('stasisstart') || msg.includes('stasis start')) {
            if (!calls.has(callId) && !endedCalls.has(callId)) {
              calls.set(callId, {
                call_id: callId,
                started_at: event.ts ? new Date(event.ts) : now,
                state: 'arriving',
              });
            }
          }
          
          // Detect provider assignment
          if (msg.includes('audio profile resolved') || msg.includes('provider selected')) {
            const call = calls.get(callId);
            if (call) {
              call.provider = event.provider || call.provider;
              call.state = 'connected';
            }
          }
          
          // Detect pipeline usage
          if (msg.includes('pipeline') && event.pipeline) {
            const call = calls.get(callId);
            if (call) {
              call.pipeline = event.pipeline;
            }
          }
          
          // Detect call end
          if (msg.includes('stasis ended') || msg.includes('call cleanup') || msg.includes('channel destroyed')) {
            endedCalls.add(callId);
            calls.delete(callId);
          }
        }
        
        // Clean up stale calls (older than 5 minutes)
        const fiveMinutesAgo = new Date(now.getTime() - 5 * 60 * 1000);
        for (const [callId, call] of calls) {
          if (call.started_at < fiveMinutesAgo) {
            calls.delete(callId);
          }
        }
        
        setState(prev => ({ ...prev, activeCalls: calls }));
      } catch (err) {
        console.error('Failed to fetch call events', err);
      }
    };
    
    fetchCallEvents();
    const interval = setInterval(fetchCallEvents, 2000);
    return () => clearInterval(interval);
  }, []);

  // Derive active providers/pipelines from calls
  const activeProviders = useMemo(() => {
    const counts = new Map<string, number>();
    for (const call of state.activeCalls.values()) {
      if (call.provider) {
        counts.set(call.provider, (counts.get(call.provider) || 0) + 1);
      }
    }
    return counts;
  }, [state.activeCalls]);

  const activePipelines = useMemo(() => {
    const counts = new Map<string, number>();
    for (const call of state.activeCalls.values()) {
      if (call.pipeline) {
        counts.set(call.pipeline, (counts.get(call.pipeline) || 0) + 1);
      }
    }
    return counts;
  }, [state.activeCalls]);

  const totalActiveCalls = state.activeCalls.size;
  const hasActiveCalls = totalActiveCalls > 0;

  // Node component
  const Node = ({ 
    label, 
    icon: Icon, 
    status, 
    count, 
    isDefault,
    subLabel,
    size = 'normal'
  }: { 
    label: string; 
    icon: any; 
    status: 'active' | 'ready' | 'error' | 'idle';
    count?: number;
    isDefault?: boolean;
    subLabel?: string;
    size?: 'small' | 'normal';
  }) => {
    const statusColors = {
      active: 'border-green-500 bg-green-500/10 shadow-green-500/20',
      ready: 'border-border bg-card',
      error: 'border-red-500 bg-red-500/10',
      idle: 'border-border bg-muted/50',
    };
    
    const iconColors = {
      active: 'text-green-500',
      ready: 'text-muted-foreground',
      error: 'text-red-500',
      idle: 'text-muted-foreground/50',
    };

    const pulseClass = status === 'active' ? 'animate-pulse' : '';
    const sizeClass = size === 'small' ? 'p-2 min-w-[80px]' : 'p-3 min-w-[100px]';

    return (
      <div className={`relative flex flex-col items-center ${sizeClass} rounded-lg border-2 ${statusColors[status]} shadow-sm transition-all duration-300 ${pulseClass}`}>
        {isDefault && (
          <div className="absolute -top-2 -right-2 text-yellow-500 text-xs">⭐</div>
        )}
        <Icon className={`w-5 h-5 ${iconColors[status]} mb-1`} />
        <span className={`text-xs font-medium ${status === 'active' ? 'text-green-500' : 'text-foreground'}`}>
          {label}
        </span>
        {subLabel && (
          <span className="text-[10px] text-muted-foreground truncate max-w-[80px]">{subLabel}</span>
        )}
        {count !== undefined && count > 0 && (
          <span className="mt-1 px-1.5 py-0.5 rounded-full bg-green-500 text-white text-[10px] font-bold">
            {count}
          </span>
        )}
        {status === 'active' && (
          <div className="absolute inset-0 rounded-lg border-2 border-green-500 animate-ping opacity-20" />
        )}
      </div>
    );
  };

  // Edge/connection line
  const Edge = ({ animated = false, vertical = false }: { animated?: boolean; vertical?: boolean }) => {
    if (vertical) {
      return (
        <div className="flex flex-col items-center h-6">
          <div className={`w-0.5 h-full ${animated ? 'bg-gradient-to-b from-green-500 to-green-300' : 'bg-border'}`}>
            {animated && (
              <div className="w-full h-2 bg-green-400 animate-bounce" style={{ animationDuration: '1s' }} />
            )}
          </div>
          <div className={`w-0 h-0 border-l-4 border-r-4 border-t-4 ${animated ? 'border-t-green-500' : 'border-t-border'} border-l-transparent border-r-transparent`} />
        </div>
      );
    }
    
    return (
      <div className="flex items-center mx-1">
        <div className={`w-8 h-0.5 ${animated ? 'bg-gradient-to-r from-green-500 to-green-300' : 'bg-border'} relative overflow-hidden`}>
          {animated && (
            <div 
              className="absolute inset-y-0 w-3 bg-green-300 animate-flow"
              style={{ animation: 'flow 1s linear infinite' }}
            />
          )}
        </div>
        <div className={`w-0 h-0 border-t-4 border-b-4 border-l-4 ${animated ? 'border-l-green-500' : 'border-l-border'} border-t-transparent border-b-transparent`} />
      </div>
    );
  };

  if (loading) {
    return (
      <div className="rounded-lg border border-border bg-card p-6">
        <div className="animate-pulse flex items-center gap-3">
          <div className="h-6 w-6 bg-muted rounded" />
          <div className="h-4 w-48 bg-muted rounded" />
        </div>
      </div>
    );
  }

  return (
    <div className="rounded-lg border border-border bg-card overflow-hidden">
      {/* Header */}
      <div className="flex items-center justify-between px-4 py-3 border-b border-border bg-muted/30">
        <div className="flex items-center gap-2">
          <Radio className={`w-4 h-4 ${hasActiveCalls ? 'text-green-500 animate-pulse' : 'text-muted-foreground'}`} />
          <span className="text-sm font-medium">Live System Topology</span>
        </div>
        <div className="flex items-center gap-2 text-xs">
          <Phone className={`w-3.5 h-3.5 ${hasActiveCalls ? 'text-green-500' : 'text-muted-foreground'}`} />
          <span className={hasActiveCalls ? 'text-green-500 font-medium' : 'text-muted-foreground'}>
            {totalActiveCalls} active call{totalActiveCalls !== 1 ? 's' : ''}
          </span>
        </div>
      </div>

      <div className="p-4 space-y-6">
        {/* Main Flow: Asterisk → AI Engine → Providers */}
        <div className="flex items-center justify-center gap-1 flex-wrap">
          {/* Asterisk PBX */}
          <Node
            label="Asterisk"
            icon={Phone}
            status={hasActiveCalls ? 'active' : 'ready'}
            count={totalActiveCalls}
            subLabel="PBX"
          />
          
          <Edge animated={hasActiveCalls} />
          
          {/* AI Engine */}
          <Node
            label="AI Engine"
            icon={Cpu}
            status={state.aiEngineStatus === 'connected' ? (hasActiveCalls ? 'active' : 'ready') : 'error'}
            count={totalActiveCalls}
            subLabel="Core"
          />
          
          <Edge animated={hasActiveCalls} />
          
          {/* Providers Section */}
          <div className="flex flex-col gap-2 p-3 rounded-lg border border-dashed border-border bg-muted/20">
            <div className="text-[10px] text-muted-foreground uppercase tracking-wide mb-1">Providers</div>
            <div className="flex flex-wrap gap-2 justify-center">
              {state.configuredProviders.length === 0 ? (
                <span className="text-xs text-muted-foreground">No providers configured</span>
              ) : (
                state.configuredProviders.map(provider => {
                  const activeCount = activeProviders.get(provider.name) || 0;
                  const isActive = activeCount > 0;
                  const isDefault = provider.name === state.defaultProvider;
                  
                  return (
                    <Node
                      key={provider.name}
                      label={provider.name.replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase()).substring(0, 12)}
                      icon={provider.type === 'monolithic' ? Zap : Server}
                      status={isActive ? 'active' : 'ready'}
                      count={activeCount || undefined}
                      isDefault={isDefault}
                      size="small"
                    />
                  );
                })
              )}
            </div>
          </div>
        </div>

        {/* Pipelines Section */}
        {state.configuredPipelines.length > 0 && (
          <div className="flex flex-col items-center">
            <div className="text-[10px] text-muted-foreground uppercase tracking-wide mb-2">Pipelines</div>
            <div className="flex flex-wrap gap-3 justify-center">
              {state.configuredPipelines.map(pipeline => {
                const activeCount = activePipelines.get(pipeline.name) || 0;
                const isActive = activeCount > 0;
                const isDefault = pipeline.name === state.activePipeline;
                
                return (
                  <div 
                    key={pipeline.name}
                    className={`flex items-center gap-1 p-2 rounded-lg border ${
                      isActive ? 'border-green-500 bg-green-500/10' : 'border-border bg-card'
                    } ${isActive ? 'animate-pulse' : ''}`}
                  >
                    {isDefault && <span className="text-yellow-500 text-xs mr-1">⭐</span>}
                    <div className="flex items-center gap-1">
                      <div className={`p-1 rounded ${isActive ? 'bg-green-500/20' : 'bg-muted'}`}>
                        <Mic className={`w-3 h-3 ${isActive ? 'text-green-500' : 'text-muted-foreground'}`} />
                      </div>
                      <span className="text-[10px] text-muted-foreground">→</span>
                      <div className={`p-1 rounded ${isActive ? 'bg-green-500/20' : 'bg-muted'}`}>
                        <MessageSquare className={`w-3 h-3 ${isActive ? 'text-green-500' : 'text-muted-foreground'}`} />
                      </div>
                      <span className="text-[10px] text-muted-foreground">→</span>
                      <div className={`p-1 rounded ${isActive ? 'bg-green-500/20' : 'bg-muted'}`}>
                        <Volume2 className={`w-3 h-3 ${isActive ? 'text-green-500' : 'text-muted-foreground'}`} />
                      </div>
                    </div>
                    <div className="ml-2">
                      <div className={`text-xs font-medium ${isActive ? 'text-green-500' : 'text-foreground'}`}>
                        {pipeline.name.replace(/_/g, ' ')}
                      </div>
                      {activeCount > 0 && (
                        <span className="text-[10px] text-green-500">{activeCount} active</span>
                      )}
                    </div>
                  </div>
                );
              })}
            </div>
          </div>
        )}

        {/* Local AI Server Section */}
        <div className="flex flex-col items-center pt-2 border-t border-border">
          <div className="text-[10px] text-muted-foreground uppercase tracking-wide mb-2">Local AI Server</div>
          <div className={`flex items-center gap-2 p-3 rounded-lg border ${
            state.localAIStatus === 'connected' ? 'border-border bg-card' : 'border-red-500 bg-red-500/10'
          }`}>
            <Activity className={`w-4 h-4 ${state.localAIStatus === 'connected' ? 'text-green-500' : 'text-red-500'}`} />
            <span className={`text-xs font-medium ${state.localAIStatus === 'connected' ? 'text-green-500' : 'text-red-500'}`}>
              {state.localAIStatus === 'connected' ? 'Connected' : 'Disconnected'}
            </span>
            
            {state.localAIStatus === 'connected' && state.localAIModels && (
              <div className="flex items-center gap-2 ml-3 pl-3 border-l border-border">
                {/* STT */}
                <div className="flex items-center gap-1">
                  <Mic className={`w-3 h-3 ${state.localAIModels.stt?.loaded ? 'text-green-500' : 'text-muted-foreground'}`} />
                  <span className="text-[10px] text-muted-foreground">
                    {state.localAIModels.stt?.backend || 'STT'}
                  </span>
                </div>
                <span className="text-muted-foreground">→</span>
                {/* LLM */}
                <div className="flex items-center gap-1">
                  <MessageSquare className={`w-3 h-3 ${state.localAIModels.llm?.loaded ? 'text-green-500' : 'text-muted-foreground'}`} />
                  <span className="text-[10px] text-muted-foreground">LLM</span>
                </div>
                <span className="text-muted-foreground">→</span>
                {/* TTS */}
                <div className="flex items-center gap-1">
                  <Volume2 className={`w-3 h-3 ${state.localAIModels.tts?.loaded ? 'text-green-500' : 'text-muted-foreground'}`} />
                  <span className="text-[10px] text-muted-foreground">
                    {state.localAIModels.tts?.backend || 'TTS'}
                  </span>
                </div>
              </div>
            )}
          </div>
        </div>

        {/* Legend */}
        <div className="flex items-center justify-center gap-4 pt-2 text-[10px] text-muted-foreground">
          <div className="flex items-center gap-1">
            <div className="w-2 h-2 rounded-full bg-green-500 animate-pulse" />
            <span>Active</span>
          </div>
          <div className="flex items-center gap-1">
            <div className="w-2 h-2 rounded-full bg-border" />
            <span>Ready</span>
          </div>
          <div className="flex items-center gap-1">
            <span className="text-yellow-500">⭐</span>
            <span>Default</span>
          </div>
        </div>
      </div>

      {/* CSS for flow animation */}
      <style>{`
        @keyframes flow {
          0% { transform: translateX(-12px); }
          100% { transform: translateX(32px); }
        }
        .animate-flow {
          animation: flow 1s linear infinite;
        }
      `}</style>
    </div>
  );
};

export default SystemTopology;

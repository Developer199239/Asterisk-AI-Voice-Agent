import { useState, useEffect } from 'react';
import { 
  CheckCircle2, 
  AlertTriangle, 
  XCircle, 
  RefreshCw, 
  Copy, 
  ExternalLink,
  Server,
  HardDrive,
  Shield,
  Box,
  Globe
} from 'lucide-react';
import { ConfigCard } from './ui/ConfigCard';
import axios from 'axios';

// Types
interface PlatformCheck {
  id: string;
  status: 'ok' | 'warning' | 'error';
  message: string;
  blocking: boolean;
  action?: {
    type: 'command' | 'link' | 'modal';
    label: string;
    value: string;
    rootless_value?: string;
  };
}

interface PlatformInfo {
  os: {
    id: string;
    version: string;
    family: string;
    arch: string;
    is_eol: boolean;
    in_container: boolean;
  };
  docker: {
    installed: boolean;
    version: string | null;
    mode: string;
    status: string;
    message: string | null;
  };
  compose: {
    installed: boolean;
    version: string | null;
    type: string;
    status: string;
    message: string | null;
  };
  selinux?: {
    present: boolean;
    mode: string | null;
    tools_installed: boolean;
  };
  directories: {
    media: {
      path: string;
      exists: boolean;
      writable: boolean;
      status: string;
    };
  };
  asterisk?: {
    detected: boolean;
    version: string | null;
    config_dir: string | null;
    freepbx: {
      detected: boolean;
      version: string | null;
    };
  };
}

interface PlatformResponse {
  platform: PlatformInfo;
  checks: PlatformCheck[];
  summary: {
    total_checks: number;
    passed: number;
    warnings: number;
    errors: number;
    blocking_errors: number;
    ready: boolean;
  };
}

// Status icon component
const StatusIcon = ({ status }: { status: string }) => {
  switch (status) {
    case 'ok':
      return <CheckCircle2 className="w-4 h-4 text-green-500" />;
    case 'warning':
      return <AlertTriangle className="w-4 h-4 text-yellow-500" />;
    case 'error':
      return <XCircle className="w-4 h-4 text-red-500" />;
    default:
      return null;
  }
};

// Copy button component
const CopyButton = ({ text }: { text: string }) => {
  const [copied, setCopied] = useState(false);

  const handleCopy = async () => {
    try {
      await navigator.clipboard.writeText(text);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch (err) {
      console.error('Failed to copy:', err);
    }
  };

  return (
    <button
      onClick={handleCopy}
      className="flex items-center gap-1 px-2 py-1 text-xs bg-gray-700 hover:bg-gray-600 rounded transition-colors"
      title="Copy command"
    >
      <Copy className="w-3 h-3" />
      {copied ? 'Copied!' : 'Copy'}
    </button>
  );
};

// Check row component
const CheckRow = ({ check, isRootless }: { check: PlatformCheck; isRootless: boolean }) => {
  const [expanded, setExpanded] = useState(false);

  const actionValue = isRootless && check.action?.rootless_value 
    ? check.action.rootless_value 
    : check.action?.value;

  return (
    <div className={`border-b border-gray-700 last:border-0 ${check.blocking ? 'bg-red-900/20' : ''}`}>
      <div 
        className="flex items-center justify-between p-3 cursor-pointer hover:bg-gray-800/50"
        onClick={() => check.action && setExpanded(!expanded)}
      >
        <div className="flex items-center gap-3">
          <StatusIcon status={check.status} />
          <span className={`text-sm ${check.status === 'error' ? 'text-red-300' : 'text-gray-300'}`}>
            {check.message}
          </span>
          {check.blocking && (
            <span className="px-2 py-0.5 text-xs bg-red-600 text-white rounded">
              Blocking
            </span>
          )}
        </div>
        {check.action && (
          <span className="text-xs text-gray-500">
            {expanded ? '▲' : '▼'}
          </span>
        )}
      </div>
      
      {expanded && check.action && (
        <div className="px-3 pb-3 bg-gray-800/30">
          {check.action.type === 'command' && (
            <div className="flex items-center gap-2">
              <code className="flex-1 px-3 py-2 text-xs bg-gray-900 text-green-400 rounded font-mono overflow-x-auto">
                {actionValue}
              </code>
              <CopyButton text={actionValue || ''} />
            </div>
          )}
          {check.action.type === 'link' && (
            <a
              href={check.action.value}
              target="_blank"
              rel="noopener noreferrer"
              className="flex items-center gap-2 text-blue-400 hover:text-blue-300 text-sm"
            >
              <ExternalLink className="w-4 h-4" />
              {check.action.label}
            </a>
          )}
        </div>
      )}
    </div>
  );
};

// Main component
export const SystemStatus = () => {
  const [data, setData] = useState<PlatformResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const fetchPlatform = async () => {
    try {
      const res = await axios.get('/api/system/platform');
      setData(res.data);
      setError(null);
    } catch (err) {
      console.error('Failed to fetch platform status:', err);
      setError('Failed to load system status');
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  };

  useEffect(() => {
    fetchPlatform();
    // Refresh every 30 seconds
    const interval = setInterval(fetchPlatform, 30000);
    return () => clearInterval(interval);
  }, []);

  const handleRefresh = () => {
    setRefreshing(true);
    fetchPlatform();
  };

  const isRootless = data?.platform?.docker?.mode === 'rootless';

  if (loading) {
    return (
      <ConfigCard title="System Status" icon={<Server className="w-5 h-5" />}>
        <div className="flex items-center justify-center p-8">
          <RefreshCw className="w-6 h-6 animate-spin text-gray-400" />
        </div>
      </ConfigCard>
    );
  }

  if (error) {
    return (
      <ConfigCard title="System Status" icon={<Server className="w-5 h-5" />}>
        <div className="p-4 text-center text-red-400">
          {error}
          <button 
            onClick={handleRefresh}
            className="ml-2 text-blue-400 hover:text-blue-300"
          >
            Retry
          </button>
        </div>
      </ConfigCard>
    );
  }

  if (!data) return null;

  const { platform, checks, summary } = data;

  return (
    <ConfigCard 
      title="System Status" 
      icon={<Server className="w-5 h-5" />}
      action={
        <button
          onClick={handleRefresh}
          disabled={refreshing}
          className="p-1.5 hover:bg-gray-700 rounded-lg transition-colors"
          title="Refresh"
        >
          <RefreshCw className={`w-4 h-4 ${refreshing ? 'animate-spin' : ''}`} />
        </button>
      }
    >
      {/* Summary Banner */}
      <div className={`px-4 py-3 ${summary.ready ? 'bg-green-900/30' : 'bg-red-900/30'} border-b border-gray-700`}>
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-3">
            {summary.ready ? (
              <CheckCircle2 className="w-5 h-5 text-green-500" />
            ) : (
              <XCircle className="w-5 h-5 text-red-500" />
            )}
            <span className={`font-medium ${summary.ready ? 'text-green-400' : 'text-red-400'}`}>
              {summary.ready ? 'System Ready' : 'Action Required'}
            </span>
          </div>
          <div className="flex gap-4 text-sm text-gray-400">
            <span className="text-green-400">{summary.passed} passed</span>
            {summary.warnings > 0 && <span className="text-yellow-400">{summary.warnings} warnings</span>}
            {summary.errors > 0 && <span className="text-red-400">{summary.errors} errors</span>}
          </div>
        </div>
      </div>

      {/* Platform Info Grid */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4 p-4 border-b border-gray-700">
        <div className="flex items-center gap-2">
          <Globe className="w-4 h-4 text-gray-500" />
          <div>
            <div className="text-xs text-gray-500">OS</div>
            <div className="text-sm text-gray-300">
              {platform.os.id} {platform.os.version}
              {platform.os.is_eol && <span className="ml-1 text-yellow-400">(EOL)</span>}
            </div>
          </div>
        </div>
        <div className="flex items-center gap-2">
          <Box className="w-4 h-4 text-gray-500" />
          <div>
            <div className="text-xs text-gray-500">Docker</div>
            <div className="text-sm text-gray-300">
              {platform.docker.version || 'Not installed'}
              {platform.docker.mode === 'rootless' && <span className="ml-1 text-blue-400">(rootless)</span>}
            </div>
          </div>
        </div>
        <div className="flex items-center gap-2">
          <HardDrive className="w-4 h-4 text-gray-500" />
          <div>
            <div className="text-xs text-gray-500">Compose</div>
            <div className="text-sm text-gray-300">
              {platform.compose.version || 'Not installed'}
            </div>
          </div>
        </div>
        {platform.selinux?.present && (
          <div className="flex items-center gap-2">
            <Shield className="w-4 h-4 text-gray-500" />
            <div>
              <div className="text-xs text-gray-500">SELinux</div>
              <div className="text-sm text-gray-300 capitalize">
                {platform.selinux.mode || 'disabled'}
              </div>
            </div>
          </div>
        )}
        {platform.asterisk?.detected && (
          <div className="flex items-center gap-2">
            <Server className="w-4 h-4 text-gray-500" />
            <div>
              <div className="text-xs text-gray-500">Asterisk</div>
              <div className="text-sm text-gray-300">
                {platform.asterisk.version || 'Detected'}
                {platform.asterisk.freepbx?.detected && (
                  <span className="ml-1 text-purple-400">(FreePBX)</span>
                )}
              </div>
            </div>
          </div>
        )}
      </div>

      {/* Checks List */}
      <div className="divide-y divide-gray-700">
        {checks.map((check) => (
          <CheckRow key={check.id} check={check} isRootless={isRootless} />
        ))}
      </div>
    </ConfigCard>
  );
};

export default SystemStatus;

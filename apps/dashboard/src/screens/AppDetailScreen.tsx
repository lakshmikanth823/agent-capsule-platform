import React, { useState, useEffect } from 'react';
import { AppDetail, AppVersion, UserProfile } from '../types';
import { api } from '../api';
import { ShareDialog } from '../components/ShareDialog';
import { 
  ArrowLeft, 
  ExternalLink, 
  Share2, 
  Copy, 
  Check, 
  Terminal, 
  AlertOctagon, 
  History, 
  FileText, 
  RefreshCw, 
  CheckCircle2,
  Database,
  Globe,
  Layers,
  ShieldAlert,
  Power,
  AlertTriangle
} from 'lucide-react';


interface AppDetailScreenProps {
  appId: string;
  currentUser: UserProfile | null;
  onBack: () => void;
}

export const AppDetailScreen: React.FC<AppDetailScreenProps> = ({
  appId,
  currentUser,
  onBack,
}) => {
  const [app, setApp] = useState<AppDetail | null>(null);
  const [versions, setVersions] = useState<AppVersion[]>([]);
  const [logs, setLogs] = useState<string[]>([]);
  const [loading, setLoading] = useState(true);
  const [activeTab, setActiveTab] = useState<'overview' | 'logs' | 'errors' | 'versions'>('overview');
  const [copied, setCopied] = useState(false);
  const [showShareDialog, setShowShareDialog] = useState(false);
  const [logTail, setLogTail] = useState(100);
  const [logFilter, setLogFilter] = useState('');
  const [autoRefresh, setAutoRefresh] = useState(true);
  const [showSuspendModal, setShowSuspendModal] = useState(false);
  const [suspendReason, setSuspendReason] = useState('');
  const [suspendActionLoading, setSuspendActionLoading] = useState(false);
  const [suspendError, setSuspendError] = useState<string | null>(null);

  useEffect(() => {
    loadApp();
  }, [appId]);

  useEffect(() => {
    let interval: NodeJS.Timeout;
    if (autoRefresh && activeTab === 'logs') {
      interval = setInterval(fetchLogs, 5000);
    }
    return () => clearInterval(interval);
  }, [autoRefresh, activeTab, appId, logTail]);

  const loadApp = async () => {
    try {
      setLoading(true);
      const [appData, versionsData, logsData] = await Promise.all([
        api.getApp(appId),
        api.listVersions(appId).catch(() => []),
        api.getLogs(appId, logTail).catch(() => ({ logs: [] })),
      ]);
      setApp(appData);
      setVersions(versionsData);
      setLogs(logsData.logs || []);
    } catch {
      // ignore
    } finally {
      setLoading(false);
    }
  };

  const fetchLogs = async () => {
    try {
      const logsData = await api.getLogs(appId, logTail);
      setLogs(logsData.logs || []);
    } catch {
      // ignore
    }
  };

  const handleCopyUrl = async () => {
    if (!app) return;
    const url = app.app_url || `http://${app.app_key}.apps.localhost:8080`;
    try {
      await navigator.clipboard.writeText(url);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      // fallback
    }
  };

  const handleSuspend = async () => {
    if (!suspendReason.trim() || !app) return;
    try {
      setSuspendActionLoading(true);
      setSuspendError(null);
      await api.suspendApp(app.id, suspendReason.trim());
      setShowSuspendModal(false);
      setSuspendReason('');
      await loadApp();
    } catch (err: any) {
      setSuspendError(err.message || 'Failed to suspend capsule');
    } finally {
      setSuspendActionLoading(false);
    }
  };

  const handleResume = async () => {
    if (!app) return;
    try {
      setSuspendActionLoading(true);
      await api.resumeApp(app.id);
      await loadApp();
    } catch (err: any) {
      alert(err.message || 'Failed to resume capsule');
    } finally {
      setSuspendActionLoading(false);
    }
  };


  if (loading || !app) {
    return (
      <div className="py-20 text-center text-sm text-slate-400">
        Loading capsule details...
      </div>
    );
  }

  const appUrl = app.app_url || `http://${app.app_key}.apps.localhost:8080`;
  const isActive = app.status === 'active';
  const filteredLogs = logs.filter((l) => l.toLowerCase().includes(logFilter.toLowerCase()));
  const errorLogs = logs.filter((l) => l.toLowerCase().includes('error') || l.toLowerCase().includes('fail') || l.toLowerCase().includes('crash'));

  return (
    <div className="space-y-6 max-w-6xl mx-auto">
      {/* Back button */}
      <button
        onClick={onBack}
        className="inline-flex items-center gap-2 text-xs font-semibold text-slate-500 hover:text-slate-900 transition-colors"
      >
        <ArrowLeft className="w-4 h-4" />
        Back to Capsules
      </button>

      {/* Header Banner */}
      <div className="p-6 bg-white border border-slate-200 rounded-2xl shadow-sm space-y-4">
        <div className="flex flex-col md:flex-row md:items-center justify-between gap-4">
          <div className="space-y-1">
            <div className="flex items-center gap-3">
              <h1 className="text-2xl font-bold text-slate-900">{app.name}</h1>
              <span
                className={`px-3 py-0.5 rounded-full text-xs font-bold uppercase tracking-wider ${
                  isActive
                    ? 'bg-emerald-100 text-emerald-800 border border-emerald-200'
                    : app.status === 'suspended'
                    ? 'bg-rose-100 text-rose-800 border border-rose-200'
                    : 'bg-amber-100 text-amber-800 border border-amber-200'
                }`}
              >
                {app.status}
              </span>
              <span className="text-xs font-mono px-2 py-0.5 rounded bg-slate-100 text-slate-700 border border-slate-200">
                {app.current_version_id ? 'v1' : 'v0.7'}
              </span>
            </div>
            <p className="text-xs text-slate-500 font-mono">
              App Key: <span className="text-slate-700">{app.app_key}</span> • ID: <span className="text-slate-700">{app.id}</span>
            </p>
          </div>

          <div className="flex items-center gap-3">
            <button
              onClick={() => setShowShareDialog(true)}
              className="px-4 py-2 text-xs font-semibold rounded-lg border border-slate-300 bg-white hover:bg-slate-50 text-slate-700 flex items-center gap-2 shadow-sm transition-colors"
            >
              <Share2 className="w-4 h-4 text-slate-500" />
              Share
            </button>

            {isActive ? (
              <button
                onClick={() => {
                  setSuspendReason('');
                  setSuspendError(null);
                  setShowSuspendModal(true);
                }}
                className="px-4 py-2 text-xs font-semibold rounded-lg border border-rose-200 bg-rose-50 hover:bg-rose-100 text-rose-700 flex items-center gap-2 shadow-sm transition-colors"
              >
                <Power className="w-4 h-4 text-rose-600" />
                Suspend Capsule
              </button>
            ) : (
              <button
                onClick={handleResume}
                disabled={suspendActionLoading}
                className="px-4 py-2 text-xs font-semibold rounded-lg border border-emerald-300 bg-emerald-50 hover:bg-emerald-100 text-emerald-700 flex items-center gap-2 shadow-sm transition-colors disabled:opacity-50"
              >
                <CheckCircle2 className="w-4 h-4 text-emerald-600" />
                {suspendActionLoading ? 'Resuming...' : 'Resume Capsule'}
              </button>
            )}

            <a
              href={appUrl}
              target="_blank"
              rel="noreferrer"
              className={`px-4 py-2 text-xs font-semibold rounded-lg flex items-center gap-2 shadow-sm transition-colors ${
                isActive
                  ? 'bg-indigo-600 hover:bg-indigo-700 text-white'
                  : 'bg-slate-200 text-slate-400 pointer-events-none'
              }`}
            >
              <ExternalLink className="w-4 h-4" />
              Open App
            </a>
          </div>

        </div>

        {/* URL Box with Copy Button */}
        <div className="pt-2 flex items-center gap-3 border-t border-slate-100">
          <span className="text-xs font-semibold text-slate-500 uppercase tracking-wider">Live URL:</span>
          <code className="px-3 py-1.5 rounded-lg bg-slate-100 border border-slate-200 text-xs font-mono text-indigo-700 font-medium select-all">
            {appUrl}
          </code>
          <button
            onClick={handleCopyUrl}
            className="p-1.5 rounded-lg border border-slate-200 hover:bg-slate-100 text-slate-600 transition-colors flex items-center gap-1 text-xs"
            title="Copy URL"
          >
            {copied ? <Check className="w-3.5 h-3.5 text-emerald-600" /> : <Copy className="w-3.5 h-3.5" />}
            <span>{copied ? 'Copied' : 'Copy'}</span>
          </button>
        </div>
      </div>

      {/* Navigation Tabs */}
      <div className="flex items-center gap-2 border-b border-slate-200">
        <button
          onClick={() => setActiveTab('overview')}
          className={`px-4 py-2.5 text-xs font-bold border-b-2 transition-colors flex items-center gap-2 ${
            activeTab === 'overview'
              ? 'border-indigo-600 text-indigo-600'
              : 'border-transparent text-slate-500 hover:text-slate-900'
          }`}
        >
          <FileText className="w-4 h-4" />
          Overview
        </button>

        <button
          onClick={() => setActiveTab('logs')}
          className={`px-4 py-2.5 text-xs font-bold border-b-2 transition-colors flex items-center gap-2 ${
            activeTab === 'logs'
              ? 'border-indigo-600 text-indigo-600'
              : 'border-transparent text-slate-500 hover:text-slate-900'
          }`}
        >
          <Terminal className="w-4 h-4" />
          Logs
          <span className="ml-1 px-1.5 py-0.2 rounded-full text-[10px] bg-slate-100 text-slate-600">
            {logs.length}
          </span>
        </button>

        <button
          onClick={() => setActiveTab('errors')}
          className={`px-4 py-2.5 text-xs font-bold border-b-2 transition-colors flex items-center gap-2 ${
            activeTab === 'errors'
              ? 'border-indigo-600 text-indigo-600'
              : 'border-transparent text-slate-500 hover:text-slate-900'
          }`}
        >
          <AlertOctagon className="w-4 h-4" />
          Errors
          {errorLogs.length > 0 && (
            <span className="ml-1 px-1.5 py-0.2 rounded-full text-[10px] bg-rose-100 text-rose-700 font-bold">
              {errorLogs.length}
            </span>
          )}
        </button>

        <button
          onClick={() => setActiveTab('versions')}
          className={`px-4 py-2.5 text-xs font-bold border-b-2 transition-colors flex items-center gap-2 ${
            activeTab === 'versions'
              ? 'border-indigo-600 text-indigo-600'
              : 'border-transparent text-slate-500 hover:text-slate-900'
          }`}
        >
          <History className="w-4 h-4" />
          Version History
          <span className="ml-1 px-1.5 py-0.2 rounded-full text-[10px] bg-slate-100 text-slate-600">
            {versions.length}
          </span>
        </button>
      </div>

      {/* Tab Contents */}
      {activeTab === 'overview' && (
        <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
          {/* Manifest & Runtime */}
          <div className="p-6 bg-white border border-slate-200 rounded-xl space-y-4">
            <h3 className="text-sm font-bold text-slate-900 flex items-center gap-2">
              <Layers className="w-4 h-4 text-indigo-600" />
              Runtime & Resource Specs
            </h3>

            <div className="divide-y divide-slate-100 text-xs">
              <div className="py-2.5 flex justify-between">
                <span className="text-slate-500">Runtime Engine</span>
                <span className="font-mono font-medium text-slate-800">Node.js 22 (LTS)</span>
              </div>
              <div className="py-2.5 flex justify-between">
                <span className="text-slate-500">Security Boundary</span>
                <span className="font-medium text-slate-800">Non-root, read-only rootfs, dropped caps</span>
              </div>
              <div className="py-2.5 flex justify-between">
                <span className="text-slate-500">Memory Limit</span>
                <span className="font-mono font-medium text-slate-800">256 MB</span>
              </div>
              <div className="py-2.5 flex justify-between">
                <span className="text-slate-500">CPU Allocation</span>
                <span className="font-mono font-medium text-slate-800">0.5 cores</span>
              </div>
              <div className="py-2.5 flex justify-between">
                <span className="text-slate-500">Idle Suspension Timeout</span>
                <span className="font-mono font-medium text-slate-800">30 seconds</span>
              </div>
            </div>
          </div>

          {/* Declared Roles & Database */}
          <div className="p-6 bg-white border border-slate-200 rounded-xl space-y-4">
            <h3 className="text-sm font-bold text-slate-900 flex items-center gap-2">
              <Database className="w-4 h-4 text-sky-600" />
              Storage & Application Roles
            </h3>

            <div className="divide-y divide-slate-100 text-xs">
              <div className="py-2.5 flex justify-between">
                <span className="text-slate-500">Database Engine</span>
                <span className="font-mono font-medium text-slate-800">SQLite (WAL mode, single writer)</span>
              </div>
              <div className="py-2.5 flex justify-between">
                <span className="text-slate-500">Storage Location</span>
                <span className="font-mono font-medium text-slate-800">/data/app.sqlite (persistent)</span>
              </div>
              <div className="py-2.5 flex justify-between">
                <span className="text-slate-500">Database Size Limit</span>
                <span className="font-mono font-medium text-slate-800">500 MB max</span>
              </div>
              <div className="py-2.5 flex justify-between items-center">
                <span className="text-slate-500">Declared Manifest Roles</span>
                <div className="flex gap-1.5">
                  {(app.manifest?.roles || ['employee', 'manager', 'hr']).map((r) => (
                    <span key={r} className="px-2 py-0.5 rounded text-[11px] font-semibold bg-indigo-50 text-indigo-700 capitalize border border-indigo-100">
                      {r}
                    </span>
                  ))}
                </div>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Logs Tab */}
      {activeTab === 'logs' && (
        <div className="bg-white border border-slate-200 rounded-xl overflow-hidden shadow-sm">
          {/* Logs Toolbar */}
          <div className="p-4 border-b border-slate-200 bg-slate-50 flex flex-wrap items-center justify-between gap-4">
            <div className="flex items-center gap-3">
              <input
                type="text"
                value={logFilter}
                onChange={(e) => setLogFilter(e.target.value)}
                placeholder="Filter logs..."
                className="px-3 py-1.5 text-xs border border-slate-300 rounded-lg bg-white w-64 focus:outline-none focus:ring-2 focus:ring-indigo-500"
              />
              <select
                value={logTail}
                onChange={(e) => setLogTail(Number(e.target.value))}
                className="px-2.5 py-1.5 text-xs border border-slate-300 rounded-lg bg-white"
              >
                <option value={50}>Last 50 lines</option>
                <option value={100}>Last 100 lines</option>
                <option value={500}>Last 500 lines</option>
              </select>
            </div>

            <div className="flex items-center gap-3">
              <label className="flex items-center gap-2 text-xs text-slate-600 cursor-pointer">
                <input
                  type="checkbox"
                  checked={autoRefresh}
                  onChange={(e) => setAutoRefresh(e.target.checked)}
                  className="rounded text-indigo-600 focus:ring-indigo-500"
                />
                Auto-refresh (5s)
              </label>
              <button
                onClick={fetchLogs}
                className="p-1.5 rounded-lg border border-slate-300 bg-white hover:bg-slate-100 text-slate-700 transition-colors"
                title="Refresh logs"
              >
                <RefreshCw className="w-3.5 h-3.5" />
              </button>
            </div>
          </div>

          {/* Log Stream Terminal */}
          <div className="p-4 bg-slate-950 text-slate-200 font-mono text-xs overflow-x-auto min-h-[350px] max-h-[500px] overflow-y-auto space-y-1">
            {filteredLogs.length === 0 ? (
              <p className="text-slate-500 italic">No logs available matching filter.</p>
            ) : (
              filteredLogs.map((line, idx) => {
                const isSystem = line.includes('[system]') || line.includes('[sandbox]');
                const isHttp = line.includes('[http]') || line.includes('[edge-proxy]');
                const isError = line.toLowerCase().includes('error');

                let textColor = 'text-slate-300';
                if (isSystem) textColor = 'text-sky-400';
                if (isHttp) textColor = 'text-emerald-400';
                if (isError) textColor = 'text-rose-400';

                return (
                  <div key={idx} className={`${textColor} whitespace-pre-wrap leading-relaxed hover:bg-slate-900/50 px-1 rounded`}>
                    {line}
                  </div>
                );
              })
            )}
          </div>
        </div>
      )}

      {/* Errors Tab */}
      {activeTab === 'errors' && (
        <div className="bg-white border border-slate-200 rounded-xl p-6">
          <h3 className="text-sm font-bold text-slate-900 mb-4 flex items-center gap-2">
            <AlertOctagon className="w-4 h-4 text-rose-600" />
            Capsule Errors & Crash Logs
          </h3>

          {errorLogs.length === 0 ? (
            <div className="p-8 text-center bg-slate-50 rounded-xl border border-slate-200">
              <CheckCircle2 className="w-8 h-8 text-emerald-500 mx-auto mb-2" />
              <p className="text-sm font-semibold text-slate-900">No runtime errors detected</p>
              <p className="text-xs text-slate-500 mt-1">
                The capsule is running smoothly with 0 fatal errors or crashes.
              </p>
            </div>
          ) : (
            <div className="space-y-2">
              {errorLogs.map((line, idx) => (
                <div key={idx} className="p-3 bg-rose-50 border border-rose-200 rounded-lg text-xs font-mono text-rose-800">
                  {line}
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {/* Versions Tab */}
      {activeTab === 'versions' && (
        <div className="bg-white border border-slate-200 rounded-xl overflow-hidden">
          <div className="p-4 border-b border-slate-200 bg-slate-50">
            <h3 className="text-sm font-bold text-slate-900">Published Versions</h3>
          </div>

          <div className="divide-y divide-slate-100">
            {versions.length === 0 ? (
              <div className="p-6 text-center text-xs text-slate-400">
                No versions recorded yet.
              </div>
            ) : (
              versions.map((ver) => (
                <div key={ver.id} className="p-4 hover:bg-slate-50 text-xs flex items-center justify-between">
                  <div className="space-y-1">
                    <div className="flex items-center gap-2">
                      <span className="font-mono font-bold text-slate-900 bg-slate-100 px-2 py-0.5 rounded">
                        v{ver.version_number}
                      </span>
                      <span className="font-medium text-slate-700">
                        {ver.change_description || 'Initial capsule release'}
                      </span>
                      <span className="px-2 py-0.5 rounded text-[10px] font-semibold bg-emerald-100 text-emerald-800 uppercase">
                        {ver.status}
                      </span>
                    </div>
                    <p className="text-slate-400 font-mono text-[11px]">
                      Published at: {new Date(ver.published_at || ver.created_at).toLocaleString()} • DB Snapshot: {ver.db_snapshot_ref || 'None'}
                    </p>
                  </div>
                </div>
              ))
            )}
          </div>
        </div>
      )}

      {/* Share Dialog */}
      {showShareDialog && (
        <ShareDialog
          app={app}
          currentUser={currentUser}
          onClose={() => setShowShareDialog(false)}
          onShareUpdated={loadApp}
        />
      )}

      {/* Suspend Confirmation Modal */}
      {showSuspendModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 backdrop-blur-sm p-4">
          <div className="bg-white border border-slate-200 rounded-2xl max-w-md w-full p-6 shadow-xl space-y-4">
            <div className="flex items-center gap-3">
              <div className="w-10 h-10 rounded-xl bg-rose-100 flex items-center justify-center text-rose-600">
                <AlertTriangle className="w-5 h-5" />
              </div>
              <div>
                <h3 className="text-base font-bold text-slate-900">Suspend Capsule</h3>
                <p className="text-xs text-slate-500">Immediate emergency kill switch</p>
              </div>
            </div>

            <p className="text-xs text-slate-600 leading-relaxed">
              Suspending this capsule will immediately stop all running sandboxes, terminate requests in flight within 5 seconds, and block incoming traffic with a 503 Suspended page.
            </p>

            <div className="space-y-1.5">
              <label className="text-xs font-semibold text-slate-700 block">
                Reason for suspension <span className="text-rose-500">*</span>
              </label>
              <textarea
                value={suspendReason}
                onChange={(e) => setSuspendReason(e.target.value)}
                placeholder="Describe reason (e.g. security breach, anomalous egress, policy violation)..."
                rows={3}
                className="w-full text-xs p-3 border border-slate-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-rose-500 focus:border-rose-500 resize-none font-sans"
              />
            </div>

            {suspendError && (
              <div className="p-3 bg-rose-50 border border-rose-200 rounded-lg text-xs text-rose-700">
                {suspendError}
              </div>
            )}

            <div className="flex items-center justify-end gap-3 pt-2">
              <button
                onClick={() => setShowSuspendModal(false)}
                disabled={suspendActionLoading}
                className="px-4 py-2 text-xs font-semibold text-slate-600 hover:bg-slate-100 rounded-lg transition-colors"
              >
                Cancel
              </button>
              <button
                onClick={handleSuspend}
                disabled={!suspendReason.trim() || suspendActionLoading}
                className="px-4 py-2 text-xs font-semibold text-white bg-rose-600 hover:bg-rose-700 disabled:opacity-50 disabled:hover:bg-rose-600 rounded-lg shadow-sm transition-colors flex items-center gap-2"
              >
                <Power className="w-3.5 h-3.5" />
                {suspendActionLoading ? 'Suspending...' : 'Confirm Suspension'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );

};

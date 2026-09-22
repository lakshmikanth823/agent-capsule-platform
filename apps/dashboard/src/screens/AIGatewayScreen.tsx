import React, { useState, useEffect } from 'react';
import { UserProfile, AIUsageSummary, AIRequestRecord } from '../types';
import { api } from '../api';
import { 
  Sparkles, 
  DollarSign, 
  Cpu, 
  Layers, 
  ShieldCheck, 
  AlertTriangle, 
  RefreshCw, 
  Trash2, 
  Search,
  Filter,
  CheckCircle,
  XCircle,
  Clock,
  Lock
} from 'lucide-react';

interface AIGatewayScreenProps {
  currentUser: UserProfile | null;
}

export const AIGatewayScreen: React.FC<AIGatewayScreenProps> = ({ currentUser }) => {
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [summary, setSummary] = useState<AIUsageSummary | null>(null);
  const [requests, setRequests] = useState<AIRequestRecord[]>([]);
  const [totalRequestsCount, setTotalRequestsCount] = useState(0);
  const [activeTab, setActiveTab] = useState<'apps' | 'models' | 'logs'>('apps');

  // Filters for logs
  const [statusFilter, setStatusFilter] = useState('');
  const [modelFilter, setModelFilter] = useState('');
  const [searchQuery, setSearchQuery] = useState('');

  // Purge modal state
  const [showPurgeModal, setShowPurgeModal] = useState(false);
  const [retentionDaysInput, setRetentionDaysInput] = useState('30');
  const [purgeLoading, setPurgeLoading] = useState(false);
  const [purgeSuccessMessage, setPurgeSuccessMessage] = useState<string | null>(null);

  const orgId = currentUser?.organization_id;

  useEffect(() => {
    if (orgId) {
      loadData();
    }
  }, [orgId, statusFilter, modelFilter]);

  const loadData = async () => {
    if (!orgId) return;
    try {
      setLoading(true);
      setError(null);

      const [usageData, requestsData] = await Promise.all([
        api.getOrgAIUsage(orgId),
        api.getOrgAIRequests(orgId, {
          status: statusFilter || undefined,
          model: modelFilter || undefined,
          limit: 50,
        }),
      ]);

      setSummary(usageData);
      setRequests(requestsData.items);
      setTotalRequestsCount(requestsData.total);
    } catch (err: any) {
      setError(err.message || 'Failed to load AI Gateway usage metrics.');
    } finally {
      setLoading(false);
    }
  };

  const handlePurge = async () => {
    if (!orgId) return;
    try {
      setPurgeLoading(true);
      setPurgeSuccessMessage(null);
      const days = parseInt(retentionDaysInput, 10) || 30;
      const res = await api.purgeExpiredAIContent(orgId, days);
      setPurgeSuccessMessage(`Successfully purged content for ${res.purged_records_count} expired records.`);
      setTimeout(() => {
        setShowPurgeModal(false);
        setPurgeSuccessMessage(null);
        loadData();
      }, 1500);
    } catch (err: any) {
      setError(err.message || 'Failed to purge expired content.');
    } finally {
      setPurgeLoading(false);
    }
  };

  const filteredRequests = requests.filter((r) => {
    if (!searchQuery) return true;
    const q = searchQuery.toLowerCase();
    return (
      r.id.toLowerCase().includes(q) ||
      r.app_id.toLowerCase().includes(q) ||
      r.model.toLowerCase().includes(q)
    );
  });

  return (
    <div className="space-y-6">
      {/* Top Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 border-b border-slate-200 pb-4">
        <div>
          <h1 className="text-xl font-bold text-slate-900 flex items-center gap-2">
            <Sparkles className="w-5 h-5 text-indigo-600" />
            AI Gateway & Usage Metering
          </h1>
          <p className="text-xs text-slate-500 mt-1">
            Centralized LLM proxy with hard-stop monthly budgets, model allowlists, token metering, and privacy-first logging.
          </p>
        </div>

        <div className="flex items-center gap-2">
          <button
            onClick={loadData}
            disabled={loading}
            className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium text-slate-700 bg-white border border-slate-200 rounded-lg hover:bg-slate-50 transition"
          >
            <RefreshCw className={`w-3.5 h-3.5 ${loading ? 'animate-spin' : ''}`} />
            Refresh
          </button>

          {currentUser?.platform_role === 'owner' && (
            <button
              onClick={() => setShowPurgeModal(true)}
              className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium text-rose-600 bg-rose-50 border border-rose-200 rounded-lg hover:bg-rose-100 transition"
            >
              <Trash2 className="w-3.5 h-3.5" />
              Purge Expired Content
            </button>
          )}
        </div>
      </div>

      {error && (
        <div className="p-4 bg-rose-50 border border-rose-200 rounded-lg flex items-center gap-3 text-rose-700 text-xs">
          <AlertTriangle className="w-4 h-4 shrink-0 text-rose-600" />
          <span>{error}</span>
        </div>
      )}

      {/* KPI Cards */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
        <div className="p-4 bg-white border border-slate-200 rounded-xl shadow-xs">
          <div className="flex items-center justify-between text-slate-500 mb-2">
            <span className="text-xs font-medium uppercase tracking-wider">Estimated Spend</span>
            <DollarSign className="w-4 h-4 text-emerald-600" />
          </div>
          <div className="text-2xl font-bold text-slate-900">
            ${summary ? summary.total_estimated_cost_usd.toFixed(4) : '0.0000'}
          </div>
          <div className="text-[11px] text-slate-500 mt-1">Current calendar month</div>
        </div>

        <div className="p-4 bg-white border border-slate-200 rounded-xl shadow-xs">
          <div className="flex items-center justify-between text-slate-500 mb-2">
            <span className="text-xs font-medium uppercase tracking-wider">Total Tokens</span>
            <Cpu className="w-4 h-4 text-indigo-600" />
          </div>
          <div className="text-2xl font-bold text-slate-900">
            {summary ? summary.total_tokens.toLocaleString() : '0'}
          </div>
          <div className="text-[11px] text-slate-500 mt-1">
            {summary ? `${summary.prompt_tokens.toLocaleString()} in / ${summary.completion_tokens.toLocaleString()} out` : '0 in / 0 out'}
          </div>
        </div>

        <div className="p-4 bg-white border border-slate-200 rounded-xl shadow-xs">
          <div className="flex items-center justify-between text-slate-500 mb-2">
            <span className="text-xs font-medium uppercase tracking-wider">Total Invocations</span>
            <Layers className="w-4 h-4 text-purple-600" />
          </div>
          <div className="text-2xl font-bold text-slate-900">
            {summary ? summary.total_requests.toLocaleString() : '0'}
          </div>
          <div className="text-[11px] text-slate-500 mt-1">Recorded gateway requests</div>
        </div>

        <div className="p-4 bg-white border border-slate-200 rounded-xl shadow-xs">
          <div className="flex items-center justify-between text-slate-500 mb-2">
            <span className="text-xs font-medium uppercase tracking-wider">Active Models</span>
            <Sparkles className="w-4 h-4 text-amber-500" />
          </div>
          <div className="text-2xl font-bold text-slate-900">
            {summary ? summary.by_model.length : 0}
          </div>
          <div className="text-[11px] text-slate-500 mt-1">Permitted by environment profile</div>
        </div>
      </div>

      {/* Governance & Privacy Banner */}
      <div className="p-4 bg-indigo-50/50 border border-indigo-100 rounded-xl text-xs space-y-2">
        <div className="flex items-start gap-2.5">
          <ShieldCheck className="w-4 h-4 text-indigo-600 shrink-0 mt-0.5" />
          <div>
            <span className="font-semibold text-indigo-950">Zero-Secret Boundary & Privacy-First Logging Active: </span>
            <span className="text-indigo-800">
              Provider API keys are stored only in the platform and never accessible to capsule applications.
              By default, the AI Gateway records metadata and token metrics only. Prompt and response contents are not logged unless explicitly enabled with automated retention expiration.
            </span>
          </div>
        </div>
      </div>

      {/* Tabs */}
      <div className="flex border-b border-slate-200 text-xs font-medium">
        <button
          onClick={() => setActiveTab('apps')}
          className={`px-4 py-2.5 border-b-2 transition ${
            activeTab === 'apps'
              ? 'border-indigo-600 text-indigo-600 font-semibold'
              : 'border-transparent text-slate-500 hover:text-slate-800'
          }`}
        >
          App Budgets & Spend ({summary?.by_app.length || 0})
        </button>
        <button
          onClick={() => setActiveTab('models')}
          className={`px-4 py-2.5 border-b-2 transition ${
            activeTab === 'models'
              ? 'border-indigo-600 text-indigo-600 font-semibold'
              : 'border-transparent text-slate-500 hover:text-slate-800'
          }`}
        >
          Model Usage ({summary?.by_model.length || 0})
        </button>
        <button
          onClick={() => setActiveTab('logs')}
          className={`px-4 py-2.5 border-b-2 transition ${
            activeTab === 'logs'
              ? 'border-indigo-600 text-indigo-600 font-semibold'
              : 'border-transparent text-slate-500 hover:text-slate-800'
          }`}
        >
          Invocation Audit Log ({totalRequestsCount})
        </button>
      </div>

      {/* Tab Content: Apps */}
      {activeTab === 'apps' && (
        <div className="bg-white border border-slate-200 rounded-xl overflow-hidden shadow-xs">
          <div className="p-4 border-b border-slate-100 flex items-center justify-between">
            <h3 className="font-semibold text-xs text-slate-800">Per-App Monthly AI Consumption</h3>
            <span className="text-[11px] text-slate-500">Hard stop enforced at manifest limit</span>
          </div>

          {!summary?.by_app.length ? (
            <div className="p-8 text-center text-xs text-slate-500">
              No application AI usage recorded for this period yet.
            </div>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-left text-xs">
                <thead className="bg-slate-50/75 border-b border-slate-200 text-[11px] font-semibold text-slate-500 uppercase tracking-wider">
                  <tr>
                    <th className="py-2.5 px-4">Application</th>
                    <th className="py-2.5 px-4">Requests</th>
                    <th className="py-2.5 px-4">Total Tokens</th>
                    <th className="py-2.5 px-4">Estimated Spend</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-100">
                  {summary.by_app.map((appItem) => (
                    <tr key={appItem.app_id} className="hover:bg-slate-50/50 transition">
                      <td className="py-3 px-4">
                        <div className="font-medium text-slate-900">{appItem.app_name}</div>
                        <div className="text-[11px] text-slate-400 font-mono">{appItem.app_id}</div>
                      </td>
                      <td className="py-3 px-4 text-slate-700">{appItem.requests.toLocaleString()}</td>
                      <td className="py-3 px-4 text-slate-700">{appItem.tokens.toLocaleString()}</td>
                      <td className="py-3 px-4 font-semibold text-slate-900">
                        ${appItem.cost_usd.toFixed(4)}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}

      {/* Tab Content: Models */}
      {activeTab === 'models' && (
        <div className="bg-white border border-slate-200 rounded-xl overflow-hidden shadow-xs">
          <div className="p-4 border-b border-slate-100 flex items-center justify-between">
            <h3 className="font-semibold text-xs text-slate-800">Usage Breakdown by Model</h3>
            <span className="text-[11px] text-slate-500">Standardized token rates applied</span>
          </div>

          {!summary?.by_model.length ? (
            <div className="p-8 text-center text-xs text-slate-500">
              No model invocations recorded yet.
            </div>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-left text-xs">
                <thead className="bg-slate-50/75 border-b border-slate-200 text-[11px] font-semibold text-slate-500 uppercase tracking-wider">
                  <tr>
                    <th className="py-2.5 px-4">Model Name</th>
                    <th className="py-2.5 px-4">Requests</th>
                    <th className="py-2.5 px-4">Total Tokens</th>
                    <th className="py-2.5 px-4">Cost (USD)</th>
                    <th className="py-2.5 px-4">Share of Spend</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-100">
                  {summary.by_model.map((m) => {
                    const pct = summary.total_estimated_cost_usd > 0
                      ? ((m.cost_usd / summary.total_estimated_cost_usd) * 100).toFixed(1)
                      : '0.0';
                    return (
                      <tr key={m.model} className="hover:bg-slate-50/50 transition">
                        <td className="py-3 px-4 font-medium text-slate-900 font-mono">
                          {m.model}
                        </td>
                        <td className="py-3 px-4 text-slate-700">{m.requests.toLocaleString()}</td>
                        <td className="py-3 px-4 text-slate-700">{m.tokens.toLocaleString()}</td>
                        <td className="py-3 px-4 font-semibold text-slate-900">${m.cost_usd.toFixed(4)}</td>
                        <td className="py-3 px-4">
                          <div className="flex items-center gap-2">
                            <div className="w-16 bg-slate-100 h-2 rounded-full overflow-hidden">
                              <div
                                className="bg-indigo-600 h-full rounded-full"
                                style={{ width: `${Math.min(100, parseFloat(pct))}%` }}
                              />
                            </div>
                            <span className="text-[11px] text-slate-500">{pct}%</span>
                          </div>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}

      {/* Tab Content: Logs */}
      {activeTab === 'logs' && (
        <div className="space-y-4">
          {/* Filters Bar */}
          <div className="flex flex-col sm:flex-row items-center gap-3 bg-white p-3 border border-slate-200 rounded-xl">
            <div className="relative flex-1 w-full">
              <Search className="w-3.5 h-3.5 absolute left-3 top-2.5 text-slate-400" />
              <input
                type="text"
                placeholder="Search by ID, App, or Model..."
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                className="w-full pl-9 pr-3 py-1.5 text-xs border border-slate-200 rounded-lg focus:outline-hidden focus:ring-1 focus:ring-indigo-500"
              />
            </div>

            <div className="flex items-center gap-2 w-full sm:w-auto">
              <select
                value={statusFilter}
                onChange={(e) => setStatusFilter(e.target.value)}
                className="text-xs border border-slate-200 rounded-lg px-2.5 py-1.5 bg-white text-slate-700"
              >
                <option value="">All Statuses</option>
                <option value="success">Success</option>
                <option value="rate_limited">Rate Limited</option>
                <option value="budget_exceeded">Budget Exceeded</option>
                <option value="error">Error</option>
              </select>

              <select
                value={modelFilter}
                onChange={(e) => setModelFilter(e.target.value)}
                className="text-xs border border-slate-200 rounded-lg px-2.5 py-1.5 bg-white text-slate-700"
              >
                <option value="">All Models</option>
                {summary?.by_model.map((m) => (
                  <option key={m.model} value={m.model}>
                    {m.model}
                  </option>
                ))}
              </select>
            </div>
          </div>

          {/* Logs Table */}
          <div className="bg-white border border-slate-200 rounded-xl overflow-hidden shadow-xs">
            {!filteredRequests.length ? (
              <div className="p-8 text-center text-xs text-slate-500">
                No matching AI Gateway requests found.
              </div>
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full text-left text-xs">
                  <thead className="bg-slate-50/75 border-b border-slate-200 text-[11px] font-semibold text-slate-500 uppercase tracking-wider">
                    <tr>
                      <th className="py-2.5 px-4">Time</th>
                      <th className="py-2.5 px-4">Model</th>
                      <th className="py-2.5 px-4">Tokens</th>
                      <th className="py-2.5 px-4">Cost (USD)</th>
                      <th className="py-2.5 px-4">Latency</th>
                      <th className="py-2.5 px-4">Status</th>
                      <th className="py-2.5 px-4">Security / Privacy</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-slate-100">
                    {filteredRequests.map((req) => (
                      <tr key={req.id} className="hover:bg-slate-50/50 transition">
                        <td className="py-2.5 px-4 text-slate-500 font-mono text-[11px]">
                          {new Date(req.created_at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' })}
                        </td>
                        <td className="py-2.5 px-4 font-mono text-slate-800">
                          {req.model}
                        </td>
                        <td className="py-2.5 px-4 text-slate-700">
                          {req.total_tokens.toLocaleString()} <span className="text-[10px] text-slate-400">({req.prompt_tokens}/{req.completion_tokens})</span>
                        </td>
                        <td className="py-2.5 px-4 text-slate-900 font-medium">
                          ${req.estimated_cost_usd.toFixed(6)}
                        </td>
                        <td className="py-2.5 px-4 text-slate-500 font-mono text-[11px]">
                          {req.duration_ms}ms
                        </td>
                        <td className="py-2.5 px-4">
                          {req.status === 'success' ? (
                            <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[10px] font-medium bg-emerald-50 text-emerald-700 border border-emerald-200">
                              <CheckCircle className="w-3 h-3" />
                              Success
                            </span>
                          ) : req.status === 'rate_limited' ? (
                            <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[10px] font-medium bg-amber-50 text-amber-700 border border-amber-200">
                              <Clock className="w-3 h-3" />
                              Rate Limited
                            </span>
                          ) : req.status === 'budget_exceeded' ? (
                            <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[10px] font-medium bg-rose-50 text-rose-700 border border-rose-200">
                              <Lock className="w-3 h-3" />
                              Budget Cutoff
                            </span>
                          ) : (
                            <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[10px] font-medium bg-rose-50 text-rose-700 border border-rose-200">
                              <XCircle className="w-3 h-3" />
                              Error
                            </span>
                          )}
                        </td>
                        <td className="py-2.5 px-4">
                          <div className="flex items-center gap-1.5">
                            {req.redacted && (
                              <span className="px-1.5 py-0.5 rounded text-[10px] font-medium bg-amber-50 text-amber-700 border border-amber-200">
                                Redacted
                              </span>
                            )}
                            {req.has_content ? (
                              <span className="px-1.5 py-0.5 rounded text-[10px] font-medium bg-purple-50 text-purple-700 border border-purple-200">
                                Content Logged
                              </span>
                            ) : (
                              <span className="px-1.5 py-0.5 rounded text-[10px] font-medium bg-slate-50 text-slate-600 border border-slate-200">
                                Metadata Only
                              </span>
                            )}
                          </div>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        </div>
      )}

      {/* Purge Modal */}
      {showPurgeModal && (
        <div className="fixed inset-0 bg-slate-900/40 backdrop-blur-xs flex items-center justify-center p-4 z-50">
          <div className="bg-white rounded-xl shadow-xl max-w-md w-full p-5 border border-slate-200 space-y-4">
            <div className="flex items-center justify-between border-b border-slate-100 pb-3">
              <h3 className="font-bold text-sm text-slate-900 flex items-center gap-2">
                <Trash2 className="w-4 h-4 text-rose-600" />
                Purge Expired AI Content
              </h3>
              <button
                onClick={() => setShowPurgeModal(false)}
                className="text-slate-400 hover:text-slate-600 text-xs"
              >
                ✕
              </button>
            </div>

            <p className="text-xs text-slate-600">
              This operation purges stored prompt and response contents older than the specified retention window. Token counts and cost metrics will be preserved.
            </p>

            <div>
              <label className="block text-[11px] font-medium text-slate-700 mb-1">
                Retention Window (Days)
              </label>
              <input
                type="number"
                min="1"
                max="3650"
                value={retentionDaysInput}
                onChange={(e) => setRetentionDaysInput(e.target.value)}
                className="w-full text-xs border border-slate-200 rounded-lg px-3 py-1.5 focus:outline-hidden focus:ring-1 focus:ring-indigo-500"
              />
            </div>

            {purgeSuccessMessage && (
              <div className="p-3 bg-emerald-50 border border-emerald-200 rounded-lg text-xs text-emerald-700">
                {purgeSuccessMessage}
              </div>
            )}

            <div className="flex justify-end gap-2 pt-2">
              <button
                onClick={() => setShowPurgeModal(false)}
                className="px-3 py-1.5 text-xs text-slate-600 bg-white border border-slate-200 rounded-lg hover:bg-slate-50 transition"
              >
                Cancel
              </button>
              <button
                onClick={handlePurge}
                disabled={purgeLoading}
                className="px-3 py-1.5 text-xs text-white bg-rose-600 rounded-lg hover:bg-rose-700 transition flex items-center gap-1.5"
              >
                {purgeLoading && <RefreshCw className="w-3.5 h-3.5 animate-spin" />}
                Purge Content Now
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};

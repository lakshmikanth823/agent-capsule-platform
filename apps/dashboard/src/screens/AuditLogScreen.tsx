import React, { useState, useEffect } from 'react';
import { UserProfile, AuditEvent, AppSummary } from '../types';
import { api } from '../api';
import {
  ShieldCheck,
  ShieldAlert,
  Download,
  Filter,
  Search,
  RefreshCw,
  Clock,
  User,
  Bot,
  ExternalLink,
  ChevronLeft,
  ChevronRight,
  CheckCircle2,
  XCircle,
  AlertCircle,
  Hash,
  Radio,
  Sliders,
  X
} from 'lucide-react';

interface AuditLogScreenProps {
  currentUser: UserProfile;
}

export const AuditLogScreen: React.FC<AuditLogScreenProps> = ({ currentUser }) => {
  const [events, setEvents] = useState<AuditEvent[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [apps, setApps] = useState<AppSummary[]>([]);
  const [verifying, setVerifying] = useState(false);
  const [verifyResult, setVerifyResult] = useState<{
    valid: boolean;
    total_events?: number;
    tampered_at_sequence?: number;
    reason?: string;
  } | null>(null);

  // Filters
  const [selectedAppId, setSelectedAppId] = useState<string>('');
  const [searchAction, setSearchAction] = useState<string>('');
  const [searchActor, setSearchActor] = useState<string>('');
  const [searchAgentTool, setSearchAgentTool] = useState<string>('');
  const [selectedOutcome, setSelectedOutcome] = useState<string>('');
  const [startTime, setStartTime] = useState<string>('');
  const [endTime, setEndTime] = useState<string>('');

  // Pagination
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(50);

  // Detail Drawer
  const [selectedEvent, setSelectedEvent] = useState<AuditEvent | null>(null);

  // Webhook Modal
  const [showWebhookModal, setShowWebhookModal] = useState(false);
  const [webhookUrl, setWebhookUrl] = useState('');
  const [webhookSecret, setWebhookSecret] = useState('');
  const [webhookActive, setWebhookActive] = useState(true);
  const [webhookConfigured, setWebhookConfigured] = useState(false);
  const [webhookTesting, setWebhookTesting] = useState(false);
  const [notification, setNotification] = useState<{ type: 'success' | 'error'; message: string } | null>(null);

  const isAdmin = currentUser.platform_role === 'owner' || currentUser.platform_role === 'editor';

  useEffect(() => {
    loadApps();
    loadAuditEvents();
    if (isAdmin) {
      loadWebhookConfig();
    }
  }, [page, pageSize, selectedAppId, selectedOutcome]);

  const loadApps = async () => {
    try {
      const items = await api.listApps();
      setApps(items);
    } catch {
      // Ignore
    }
  };

  const loadWebhookConfig = async () => {
    try {
      const data = await api.getAuditWebhook(currentUser.organization_id);
      if (data.configured && data.webhook) {
        setWebhookConfigured(true);
        setWebhookUrl(data.webhook.url);
        setWebhookActive(data.webhook.is_active);
      }
    } catch {
      // Ignore
    }
  };

  const loadAuditEvents = async () => {
    try {
      setLoading(true);
      const params: Record<string, any> = {
        limit: pageSize,
        offset: (page - 1) * pageSize,
      };
      if (selectedAppId) params.app_id = selectedAppId;
      if (searchAction) params.action = searchAction;
      if (searchActor) params.actor_user_id = searchActor;
      if (searchAgentTool) params.agent_or_tool = searchAgentTool;
      if (selectedOutcome) params.outcome = selectedOutcome;
      if (startTime) params.start_time = new Date(startTime).toISOString();
      if (endTime) params.end_time = new Date(endTime).toISOString();

      const data = await api.listOrgAuditEvents(currentUser.organization_id, params);
      setEvents(data.items);
      setTotal(data.total);
    } catch (err: any) {
      setNotification({ type: 'error', message: err.message || 'Failed to load audit events' });
    } finally {
      setLoading(false);
    }
  };

  const handleVerifyChain = async () => {
    try {
      setVerifying(true);
      const report = await api.verifyAuditChain(currentUser.organization_id);
      setVerifyResult(report);
      if (report.valid) {
        setNotification({
          type: 'success',
          message: `Hash chain verified successfully (${report.total_events} events cryptographically unbroken).`,
        });
      } else {
        setNotification({
          type: 'error',
          message: `Tampering detected at sequence ${report.tampered_at_sequence}: ${report.reason}`,
        });
      }
    } catch (err: any) {
      setNotification({ type: 'error', message: err.message || 'Verification failed' });
    } finally {
      setVerifying(false);
    }
  };

  const handleEnforceRetention = async () => {
    try {
      const res = await api.enforceAuditRetention(currentUser.organization_id);
      setNotification({
        type: 'success',
        message: `Retention enforced: pruned ${res.purged_count} expired records (${res.retention_days} days policy). Checkpoint anchored.`,
      });
      loadAuditEvents();
    } catch (err: any) {
      setNotification({ type: 'error', message: err.message || 'Failed to enforce retention' });
    }
  };

  const handleSaveWebhook = async (e: React.FormEvent) => {
    e.preventDefault();
    try {
      await api.updateAuditWebhook(currentUser.organization_id, {
        url: webhookUrl,
        secret_token: webhookSecret || undefined,
        is_active: webhookActive,
      });
      setWebhookConfigured(true);
      setShowWebhookModal(false);
      setNotification({ type: 'success', message: 'Audit streaming webhook saved.' });
    } catch (err: any) {
      setNotification({ type: 'error', message: err.message || 'Failed to save webhook' });
    }
  };

  const handleTestWebhook = async () => {
    try {
      setWebhookTesting(true);
      const res = await api.testAuditWebhook(currentUser.organization_id);
      if (res.delivered) {
        setNotification({ type: 'success', message: 'Test webhook event delivered successfully.' });
      } else {
        setNotification({ type: 'error', message: 'Webhook endpoint returned an error or was unreachable.' });
      }
    } catch (err: any) {
      setNotification({ type: 'error', message: err.message || 'Webhook test dispatch failed' });
    } finally {
      setWebhookTesting(false);
    }
  };

  const handleExport = (format: 'csv' | 'json') => {
    const token = localStorage.getItem('capsule_token');
    const baseUrl = window.location.hostname.includes('platform.localhost') || window.location.port === '8080' ? '/v1' : 'http://localhost:8000/v1';
    let url = `${baseUrl}/organizations/${currentUser.organization_id}/audit/export?format=${format}`;
    if (selectedAppId) url += `&app_id=${encodeURIComponent(selectedAppId)}`;
    if (searchAction) url += `&action=${encodeURIComponent(searchAction)}`;
    if (selectedOutcome) url += `&outcome=${encodeURIComponent(selectedOutcome)}`;

    // Trigger download via fetch with bearer token
    fetch(url, {
      headers: { Authorization: `Bearer ${token}` },
    })
      .then((res) => res.blob())
      .then((blob) => {
        const downloadUrl = window.URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = downloadUrl;
        a.download = `audit_export_${currentUser.organization_id}.${format}`;
        document.body.appendChild(a);
        a.click();
        a.remove();
      })
      .catch(() => {
        setNotification({ type: 'error', message: 'Export download failed.' });
      });
  };

  const totalPages = Math.max(1, Math.ceil(total / pageSize));

  return (
    <div className="max-w-7xl mx-auto space-y-6">
      {/* Header */}
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-4 bg-white p-6 rounded-xl border border-slate-200 shadow-sm">
        <div>
          <div className="flex items-center gap-3">
            <div className="p-2 bg-indigo-50 text-indigo-600 rounded-lg">
              <ShieldCheck className="w-6 h-6" />
            </div>
            <div>
              <h1 className="text-xl font-bold text-slate-900">Audit Logs & Cryptographic Vault</h1>
              <p className="text-xs text-slate-500">
                Append-only, tamper-evident record of all platform mutations, security events, and capability grants.
              </p>
            </div>
          </div>
        </div>

        {/* Action Controls */}
        <div className="flex flex-wrap items-center gap-2">
          {isAdmin && (
            <>
              <button
                onClick={handleVerifyChain}
                disabled={verifying}
                className={`inline-flex items-center gap-1.5 px-3 py-1.5 text-xs font-semibold rounded-lg border transition-colors ${
                  verifyResult?.valid === false
                    ? 'bg-rose-50 border-rose-300 text-rose-700 hover:bg-rose-100'
                    : 'bg-emerald-50 border-emerald-300 text-emerald-700 hover:bg-emerald-100'
                }`}
                title="Verifies cryptographic hash chain integrity"
              >
                {verifying ? (
                  <RefreshCw className="w-3.5 h-3.5 animate-spin" />
                ) : verifyResult?.valid === false ? (
                  <ShieldAlert className="w-3.5 h-3.5 text-rose-600" />
                ) : (
                  <ShieldCheck className="w-3.5 h-3.5 text-emerald-600" />
                )}
                {verifying ? 'Verifying...' : verifyResult?.valid === false ? 'Tampered Chain' : 'Verify Ledger'}
              </button>

              <button
                onClick={() => setShowWebhookModal(true)}
                className="inline-flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium rounded-lg border border-slate-300 bg-white text-slate-700 hover:bg-slate-50"
              >
                <Radio className="w-3.5 h-3.5 text-indigo-600" />
                SIEM Webhook
              </button>

              <button
                onClick={handleEnforceRetention}
                className="inline-flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium rounded-lg border border-slate-300 bg-white text-slate-700 hover:bg-slate-50"
                title="Prunes expired records and establishes checkpoint anchor"
              >
                <Clock className="w-3.5 h-3.5 text-slate-500" />
                Retention
              </button>
            </>
          )}

          {/* Export Dropdown / Buttons */}
          <div className="flex items-center rounded-lg border border-slate-300 bg-white overflow-hidden">
            <button
              onClick={() => handleExport('csv')}
              className="inline-flex items-center gap-1 px-3 py-1.5 text-xs font-medium text-slate-700 hover:bg-slate-50 border-r border-slate-200"
            >
              <Download className="w-3 h-3 text-slate-500" /> CSV
            </button>
            <button
              onClick={() => handleExport('json')}
              className="inline-flex items-center gap-1 px-3 py-1.5 text-xs font-medium text-slate-700 hover:bg-slate-50"
            >
              <Download className="w-3 h-3 text-slate-500" /> JSON
            </button>
          </div>
        </div>
      </div>

      {/* Notifications */}
      {notification && (
        <div
          className={`p-4 rounded-lg text-xs flex items-center justify-between ${
            notification.type === 'success'
              ? 'bg-emerald-50 border border-emerald-200 text-emerald-800'
              : 'bg-rose-50 border border-rose-200 text-rose-800'
          }`}
        >
          <div className="flex items-center gap-2">
            {notification.type === 'success' ? (
              <CheckCircle2 className="w-4 h-4 text-emerald-600 shrink-0" />
            ) : (
              <AlertCircle className="w-4 h-4 text-rose-600 shrink-0" />
            )}
            <span>{notification.message}</span>
          </div>
          <button onClick={() => setNotification(null)} className="text-slate-400 hover:text-slate-600">
            <X className="w-3.5 h-3.5" />
          </button>
        </div>
      )}

      {/* Filter Bar */}
      <div className="bg-white p-4 rounded-xl border border-slate-200 space-y-3">
        <div className="flex items-center gap-2 text-xs font-bold text-slate-700 uppercase tracking-wider">
          <Filter className="w-3.5 h-3.5 text-slate-400" /> Filters & Query Constraints
        </div>
        <div className="grid grid-cols-1 md:grid-cols-5 gap-3">
          {/* App selector */}
          <div>
            <label className="block text-[11px] font-medium text-slate-500 mb-1">Capsule / App</label>
            <select
              value={selectedAppId}
              onChange={(e) => {
                setSelectedAppId(e.target.value);
                setPage(1);
              }}
              className="w-full text-xs px-2.5 py-1.5 border border-slate-300 rounded-lg focus:outline-none focus:ring-1 focus:ring-indigo-500"
            >
              <option value="">All Applications</option>
              {apps.map((a) => (
                <option key={a.id} value={a.id}>
                  {a.name} ({a.app_key})
                </option>
              ))}
            </select>
          </div>

          {/* Action search */}
          <div>
            <label className="block text-[11px] font-medium text-slate-500 mb-1">Action Name</label>
            <div className="relative">
              <input
                type="text"
                placeholder="e.g. app.publish"
                value={searchAction}
                onChange={(e) => setSearchAction(e.target.value)}
                onKeyDown={(e) => e.key === 'Enter' && loadAuditEvents()}
                className="w-full text-xs pl-7 pr-2.5 py-1.5 border border-slate-300 rounded-lg focus:outline-none focus:ring-1 focus:ring-indigo-500"
              />
              <Search className="w-3.5 h-3.5 text-slate-400 absolute left-2 top-2" />
            </div>
          </div>

          {/* Agent or Tool */}
          <div>
            <label className="block text-[11px] font-medium text-slate-500 mb-1">Agent / Tool</label>
            <div className="relative">
              <input
                type="text"
                placeholder="e.g. capsule-cli"
                value={searchAgentTool}
                onChange={(e) => setSearchAgentTool(e.target.value)}
                onKeyDown={(e) => e.key === 'Enter' && loadAuditEvents()}
                className="w-full text-xs pl-7 pr-2.5 py-1.5 border border-slate-300 rounded-lg focus:outline-none focus:ring-1 focus:ring-indigo-500"
              />
              <Bot className="w-3.5 h-3.5 text-slate-400 absolute left-2 top-2" />
            </div>
          </div>

          {/* Outcome */}
          <div>
            <label className="block text-[11px] font-medium text-slate-500 mb-1">Outcome</label>
            <select
              value={selectedOutcome}
              onChange={(e) => {
                setSelectedOutcome(e.target.value);
                setPage(1);
              }}
              className="w-full text-xs px-2.5 py-1.5 border border-slate-300 rounded-lg focus:outline-none focus:ring-1 focus:ring-indigo-500"
            >
              <option value="">All Outcomes</option>
              <option value="success">Success</option>
              <option value="denied">Denied</option>
              <option value="failed">Failed</option>
            </select>
          </div>

          {/* Search Button */}
          <div className="flex items-end gap-2">
            <button
              onClick={() => {
                setPage(1);
                loadAuditEvents();
              }}
              className="flex-1 bg-indigo-600 hover:bg-indigo-700 text-white font-medium py-1.5 px-3 rounded-lg text-xs transition-colors flex items-center justify-center gap-1"
            >
              <Search className="w-3.5 h-3.5" /> Apply Filter
            </button>
            <button
              onClick={() => {
                setSelectedAppId('');
                setSearchAction('');
                setSearchActor('');
                setSearchAgentTool('');
                setSelectedOutcome('');
                setStartTime('');
                setEndTime('');
                setPage(1);
                setTimeout(loadAuditEvents, 0);
              }}
              className="px-2.5 py-1.5 border border-slate-300 text-slate-600 hover:bg-slate-50 rounded-lg text-xs"
              title="Clear all filters"
            >
              Reset
            </button>
          </div>
        </div>
      </div>

      {/* Events Table */}
      <div className="bg-white rounded-xl border border-slate-200 overflow-hidden shadow-sm">
        <div className="p-4 border-b border-slate-200 flex items-center justify-between text-xs text-slate-500">
          <span>Showing {events.length} of {total} audit records</span>
          <div className="flex items-center gap-2 font-mono text-[11px]">
            <span className="inline-block w-2 h-2 rounded-full bg-emerald-500"></span>
            Append-only DB trigger active
          </div>
        </div>

        <div className="overflow-x-auto">
          <table className="w-full text-left border-collapse text-xs">
            <thead>
              <tr className="bg-slate-50 border-b border-slate-200 text-slate-600 font-semibold">
                <th className="py-2.5 px-3 w-16">Seq #</th>
                <th className="py-2.5 px-3">Timestamp</th>
                <th className="py-2.5 px-3">Action</th>
                <th className="py-2.5 px-3">Actor & Tool</th>
                <th className="py-2.5 px-3">Outcome</th>
                <th className="py-2.5 px-3 font-mono">Event Hash</th>
                <th className="py-2.5 px-3 text-right">Details</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {loading ? (
                <tr>
                  <td colSpan={7} className="py-12 text-center text-slate-400">
                    <RefreshCw className="w-5 h-5 animate-spin mx-auto mb-2 text-indigo-500" />
                    Loading cryptographically chained records...
                  </td>
                </tr>
              ) : events.length === 0 ? (
                <tr>
                  <td colSpan={7} className="py-12 text-center text-slate-400">
                    No audit records match the current filter criteria.
                  </td>
                </tr>
              ) : (
                events.map((e) => (
                  <tr key={e.id} className="hover:bg-slate-50/80 transition-colors">
                    <td className="py-2.5 px-3 font-mono font-bold text-slate-500">
                      #{e.sequence_number ?? '-'}
                    </td>
                    <td className="py-2.5 px-3 text-slate-600 font-mono text-[11px] whitespace-nowrap">
                      {new Date(e.occurred_at).toLocaleString()}
                    </td>
                    <td className="py-2.5 px-3 font-medium text-slate-800">
                      <span className="font-mono bg-slate-100 text-slate-800 px-1.5 py-0.5 rounded text-[11px]">
                        {e.action}
                      </span>
                    </td>
                    <td className="py-2.5 px-3 text-slate-600">
                      <div className="flex flex-col gap-0.5">
                        <span className="text-[11px] font-medium text-slate-700 flex items-center gap-1">
                          <User className="w-3 h-3 text-slate-400" />
                          {e.actor_user_id ? e.actor_user_id.slice(0, 8) + '...' : 'System'}
                        </span>
                        {(e.actor_agent || e.actor_tool) && (
                          <span className="text-[10px] text-slate-400 font-mono flex items-center gap-1">
                            <Bot className="w-2.5 h-2.5 text-indigo-400" />
                            {e.actor_agent || 'agent'}:{e.actor_tool || 'tool'}
                          </span>
                        )}
                      </div>
                    </td>
                    <td className="py-2.5 px-3">
                      <span
                        className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[10px] font-semibold ${
                          e.outcome === 'success'
                            ? 'bg-emerald-50 text-emerald-700 border border-emerald-200'
                            : e.outcome === 'denied'
                            ? 'bg-amber-50 text-amber-700 border border-amber-200'
                            : 'bg-rose-50 text-rose-700 border border-rose-200'
                        }`}
                      >
                        {e.outcome === 'success' ? (
                          <CheckCircle2 className="w-2.5 h-2.5" />
                        ) : (
                          <XCircle className="w-2.5 h-2.5" />
                        )}
                        {e.outcome}
                      </span>
                    </td>
                    <td className="py-2.5 px-3 font-mono text-[10px] text-slate-400" title={e.event_hash}>
                      {e.event_hash ? e.event_hash.slice(0, 10) + '...' : '-'}
                    </td>
                    <td className="py-2.5 px-3 text-right">
                      <button
                        onClick={() => setSelectedEvent(e)}
                        className="text-xs text-indigo-600 hover:text-indigo-800 font-medium px-2 py-1 rounded hover:bg-indigo-50"
                      >
                        Inspect
                      </button>
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>

        {/* Pagination Controls */}
        <div className="p-3 border-t border-slate-200 flex items-center justify-between text-xs text-slate-600 bg-slate-50">
          <div className="flex items-center gap-2">
            <span>Rows per page:</span>
            <select
              value={pageSize}
              onChange={(e) => {
                setPageSize(Number(e.target.value));
                setPage(1);
              }}
              className="text-xs border border-slate-300 rounded px-2 py-1 bg-white"
            >
              <option value={25}>25</option>
              <option value={50}>50</option>
              <option value={100}>100</option>
            </select>
          </div>
          <div className="flex items-center gap-3">
            <span>
              Page {page} of {totalPages}
            </span>
            <div className="flex items-center gap-1">
              <button
                disabled={page <= 1}
                onClick={() => setPage((p) => Math.max(1, p - 1))}
                className="p-1 border border-slate-300 rounded bg-white disabled:opacity-40 disabled:cursor-not-allowed hover:bg-slate-100"
              >
                <ChevronLeft className="w-4 h-4" />
              </button>
              <button
                disabled={page >= totalPages}
                onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
                className="p-1 border border-slate-300 rounded bg-white disabled:opacity-40 disabled:cursor-not-allowed hover:bg-slate-100"
              >
                <ChevronRight className="w-4 h-4" />
              </button>
            </div>
          </div>
        </div>
      </div>

      {/* Event Detail Drawer / Modal */}
      {selectedEvent && (
        <div className="fixed inset-0 z-50 bg-black/40 flex items-center justify-center p-4 backdrop-blur-sm">
          <div className="bg-white w-full max-w-2xl rounded-2xl shadow-xl border border-slate-200 overflow-hidden flex flex-col max-h-[85vh]">
            <div className="p-4 border-b border-slate-200 flex items-center justify-between bg-slate-50">
              <div className="flex items-center gap-2">
                <Hash className="w-4 h-4 text-indigo-600" />
                <h3 className="text-sm font-bold text-slate-900">
                  Audit Event #{selectedEvent.sequence_number ?? 'N/A'} Detail
                </h3>
              </div>
              <button
                onClick={() => setSelectedEvent(null)}
                className="p-1 text-slate-400 hover:text-slate-600 rounded-lg"
              >
                <X className="w-4 h-4" />
              </button>
            </div>

            <div className="p-6 overflow-y-auto space-y-4 text-xs">
              <div className="grid grid-cols-2 gap-3 bg-slate-50 p-3 rounded-lg border border-slate-100">
                <div>
                  <span className="text-slate-400 font-medium">Event ID</span>
                  <p className="font-mono text-slate-800 text-[11px] truncate">{selectedEvent.id}</p>
                </div>
                <div>
                  <span className="text-slate-400 font-medium">Occurred At</span>
                  <p className="font-mono text-slate-800 text-[11px]">
                    {new Date(selectedEvent.occurred_at).toUTCString()}
                  </p>
                </div>
                <div>
                  <span className="text-slate-400 font-medium">Action</span>
                  <p className="font-bold text-slate-900">{selectedEvent.action}</p>
                </div>
                <div>
                  <span className="text-slate-400 font-medium">Outcome</span>
                  <p className="font-semibold text-emerald-700">{selectedEvent.outcome}</p>
                </div>
                <div>
                  <span className="text-slate-400 font-medium">Actor User ID</span>
                  <p className="font-mono text-slate-800 text-[11px] truncate">
                    {selectedEvent.actor_user_id || 'System'}
                  </p>
                </div>
                <div>
                  <span className="text-slate-400 font-medium">Agent / Tool</span>
                  <p className="font-mono text-slate-800 text-[11px]">
                    {selectedEvent.actor_agent || '-'}:{selectedEvent.actor_tool || '-'}
                  </p>
                </div>
              </div>

              {/* Cryptographic Chain Info */}
              <div className="space-y-2">
                <h4 className="text-xs font-bold text-slate-700 uppercase tracking-wider flex items-center gap-1.5">
                  <ShieldCheck className="w-3.5 h-3.5 text-emerald-600" /> Cryptographic Chain Integrity
                </h4>
                <div className="bg-slate-900 text-slate-200 p-3 rounded-lg font-mono text-[11px] space-y-1.5 overflow-x-auto">
                  <div>
                    <span className="text-slate-400">Previous Hash:</span>
                    <p className="text-emerald-400 break-all">{selectedEvent.prev_hash || 'None'}</p>
                  </div>
                  <div>
                    <span className="text-slate-400">Event Hash:</span>
                    <p className="text-indigo-400 break-all">{selectedEvent.event_hash || 'None'}</p>
                  </div>
                </div>
              </div>

              {/* Event Metadata */}
              <div className="space-y-2">
                <h4 className="text-xs font-bold text-slate-700 uppercase tracking-wider">
                  Event Metadata (Sanitized)
                </h4>
                <pre className="bg-slate-50 border border-slate-200 p-3 rounded-lg font-mono text-[11px] text-slate-800 overflow-x-auto">
                  {JSON.stringify(selectedEvent.metadata || {}, null, 2)}
                </pre>
              </div>
            </div>

            <div className="p-4 border-t border-slate-200 bg-slate-50 text-right">
              <button
                onClick={() => setSelectedEvent(null)}
                className="px-4 py-1.5 bg-slate-800 text-white rounded-lg text-xs font-medium hover:bg-slate-900"
              >
                Close
              </button>
            </div>
          </div>
        </div>
      )}

      {/* SIEM / Streaming Webhook Modal */}
      {showWebhookModal && (
        <div className="fixed inset-0 z-50 bg-black/40 flex items-center justify-center p-4 backdrop-blur-sm">
          <div className="bg-white w-full max-w-lg rounded-2xl shadow-xl border border-slate-200 overflow-hidden">
            <div className="p-4 border-b border-slate-200 flex items-center justify-between bg-slate-50">
              <div className="flex items-center gap-2">
                <Radio className="w-4 h-4 text-indigo-600" />
                <h3 className="text-sm font-bold text-slate-900">Streaming SIEM Webhook</h3>
              </div>
              <button
                onClick={() => setShowWebhookModal(false)}
                className="p-1 text-slate-400 hover:text-slate-600 rounded-lg"
              >
                <X className="w-4 h-4" />
              </button>
            </div>

            <form onSubmit={handleSaveWebhook} className="p-6 space-y-4 text-xs">
              <p className="text-slate-500">
                Automatically stream every audit event to your external log monitoring system (Datadog, Splunk, SumoLogic) with HMAC-SHA256 signature verification.
              </p>

              <div>
                <label className="block text-slate-700 font-medium mb-1">Webhook Endpoint URL</label>
                <input
                  type="url"
                  required
                  placeholder="https://siem.example.com/api/v1/capsule-logs"
                  value={webhookUrl}
                  onChange={(e) => setWebhookUrl(e.target.value)}
                  className="w-full px-3 py-2 border border-slate-300 rounded-lg font-mono text-xs focus:ring-1 focus:ring-indigo-500"
                />
              </div>

              <div>
                <label className="block text-slate-700 font-medium mb-1">
                  HMAC Secret Token {webhookConfigured && '(leave blank to retain existing)'}
                </label>
                <input
                  type="password"
                  placeholder={webhookConfigured ? '••••••••••••••••' : 'Enter signing secret'}
                  value={webhookSecret}
                  onChange={(e) => setWebhookSecret(e.target.value)}
                  className="w-full px-3 py-2 border border-slate-300 rounded-lg font-mono text-xs focus:ring-1 focus:ring-indigo-500"
                />
              </div>

              <div className="flex items-center gap-2 pt-1">
                <input
                  type="checkbox"
                  id="wh-active"
                  checked={webhookActive}
                  onChange={(e) => setWebhookActive(e.target.checked)}
                  className="rounded text-indigo-600 focus:ring-indigo-500"
                />
                <label htmlFor="wh-active" className="text-slate-700 font-medium">
                  Active (Stream events in real time)
                </label>
              </div>

              <div className="flex items-center justify-between pt-4 border-t border-slate-100">
                {webhookConfigured ? (
                  <button
                    type="button"
                    onClick={handleTestWebhook}
                    disabled={webhookTesting}
                    className="px-3 py-1.5 border border-slate-300 text-slate-700 rounded-lg hover:bg-slate-50"
                  >
                    {webhookTesting ? 'Testing...' : 'Send Test Ping'}
                  </button>
                ) : (
                  <div></div>
                )}
                <div className="flex items-center gap-2">
                  <button
                    type="button"
                    onClick={() => setShowWebhookModal(false)}
                    className="px-3 py-1.5 text-slate-500 hover:text-slate-700"
                  >
                    Cancel
                  </button>
                  <button
                    type="submit"
                    className="px-4 py-1.5 bg-indigo-600 text-white rounded-lg font-medium hover:bg-indigo-700"
                  >
                    Save Webhook
                  </button>
                </div>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
};

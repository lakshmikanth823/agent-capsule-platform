import React, { useState, useEffect } from 'react';
import { UserProfile, InventoryItem } from '../types';
import { api } from '../api';
import {
  ClipboardList,
  Shield,
  Download,
  Filter,
  Search,
  RefreshCw,
  Clock,
  User,
  Users,
  AlertTriangle,
  CheckCircle2,
  XCircle,
  Archive,
  ArrowRightLeft,
  ExternalLink,
  Layers,
  FileCode,
  X,
  Play
} from 'lucide-react';

interface InventoryScreenProps {
  currentUser: UserProfile;
  onSelectApp?: (appId: string) => void;
}

export const InventoryScreen: React.FC<InventoryScreenProps> = ({ currentUser, onSelectApp }) => {
  const [items, setItems] = useState<InventoryItem[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [searchQuery, setSearchQuery] = useState('');
  const [statusFilter, setStatusFilter] = useState('all');
  const [govFilter, setGovFilter] = useState('all');
  const [runningCycle, setRunningCycle] = useState(false);
  const [cycleNotice, setCycleNotice] = useState<string | null>(null);

  // Transfer ownership modal state
  const [transferModalApp, setTransferModalApp] = useState<InventoryItem | null>(null);
  const [transferTargetId, setTransferTargetId] = useState('');
  const [transferReason, setTransferReason] = useState('Administrative ownership transfer');
  const [transferLoading, setTransferLoading] = useState(false);
  const [transferError, setTransferError] = useState<string | null>(null);

  useEffect(() => {
    fetchInventory();
  }, [currentUser.organization_id]);

  const fetchInventory = async () => {
    try {
      setLoading(true);
      const res = await api.getInventory(currentUser.organization_id);
      setItems(res.items || []);
      setTotal(res.total || 0);
    } catch (err: any) {
      console.error('Failed to load inventory:', err);
    } finally {
      setLoading(false);
    }
  };

  const handleExportCsv = async () => {
    try {
      const csvText = await api.exportInventoryCsv(currentUser.organization_id);
      const blob = new Blob([csvText], { type: 'text/csv' });
      const url = window.URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `inventory-${currentUser.organization_id}-${new Date().toISOString().slice(0, 10)}.csv`;
      a.click();
      window.URL.revokeObjectURL(url);
    } catch (err: any) {
      alert('Failed to export CSV: ' + err.message);
    }
  };

  const handleExportJson = () => {
    const jsonText = JSON.stringify({ organization_id: currentUser.organization_id, items, total }, null, 2);
    const blob = new Blob([jsonText], { type: 'application/json' });
    const url = window.URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `inventory-${currentUser.organization_id}-${new Date().toISOString().slice(0, 10)}.json`;
    a.click();
    window.URL.revokeObjectURL(url);
  };

  const handleRunGovernanceCycle = async () => {
    try {
      setRunningCycle(true);
      setCycleNotice(null);
      const res = await api.runGovernanceCycle(currentUser.organization_id);
      const s = res.stats || {};
      setCycleNotice(
        `Cycle evaluated: ${s.grace_periods_expired || 0} grace periods expired, ${s.warnings_sent || 0} warnings sent, ${s.archived_count || 0} apps archived, ${s.purged_count || 0} purged.`
      );
      await fetchInventory();
    } catch (err: any) {
      setCycleNotice(`Cycle failed: ${err.message}`);
    } finally {
      setRunningCycle(false);
    }
  };

  const handleDownloadAppData = async (appId: string, appKey: string) => {
    try {
      const data = await api.getAppExportData(appId);
      const jsonText = JSON.stringify(data, null, 2);
      const blob = new Blob([jsonText], { type: 'application/json' });
      const url = window.URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `capsule-export-${appKey}-${new Date().toISOString().slice(0, 10)}.json`;
      a.click();
      window.URL.revokeObjectURL(url);
    } catch (err: any) {
      alert('Failed to download capsule data: ' + err.message);
    }
  };

  const executeTransfer = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!transferModalApp || !transferTargetId) return;

    try {
      setTransferLoading(true);
      setTransferError(null);
      await api.transferOwnership(transferModalApp.id, transferTargetId, transferReason);
      setTransferModalApp(null);
      setTransferTargetId('');
      await fetchInventory();
    } catch (err: any) {
      setTransferError(err.message || 'Failed to transfer ownership');
    } finally {
      setTransferLoading(false);
    }
  };

  // KPIs
  const activeCount = items.filter((i) => i.status === 'active').length;
  const pendingOwnerCount = items.filter((i) => i.governance_state === 'pending_owner').length;
  const warningCount = items.filter((i) => (i.expiry_status || '').startsWith('warning')).length;
  const archivedCount = items.filter((i) => i.status === 'archived' || i.status === 'suspended').length;

  // Filtered items
  const filtered = items.filter((item) => {
    const q = searchQuery.toLowerCase();
    const matchQuery =
      !q ||
      item.name.toLowerCase().includes(q) ||
      item.app_key.toLowerCase().includes(q) ||
      (item.owner?.email || '').toLowerCase().includes(q);

    const matchStatus = statusFilter === 'all' || item.status === statusFilter;
    const matchGov = govFilter === 'all' || item.governance_state === govFilter;

    return matchQuery && matchStatus && matchGov;
  });

  return (
    <div className="max-w-7xl mx-auto space-y-6">
      {/* Header */}
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-4">
        <div>
          <h2 className="text-xl font-bold text-slate-900 flex items-center gap-2">
            <ClipboardList className="w-6 h-6 text-indigo-600" />
            Application Inventory & Governance
          </h2>
          <p className="text-xs text-slate-500 mt-0.5">
            Central registry of all capsules, active owners, governance lifecycle state, user counts, and expiry controls (FR-033 to FR-036).
          </p>
        </div>

        <div className="flex flex-wrap items-center gap-2">
          {currentUser.platform_role === 'owner' && (
            <button
              onClick={handleRunGovernanceCycle}
              disabled={runningCycle}
              className="inline-flex items-center gap-1.5 px-3 py-1.5 bg-indigo-50 border border-indigo-200 text-indigo-700 hover:bg-indigo-100 rounded-lg text-xs font-semibold transition disabled:opacity-50"
            >
              <Play className={`w-3.5 h-3.5 ${runningCycle ? 'animate-spin' : ''}`} />
              {runningCycle ? 'Running Cycle...' : 'Run Governance Cycle'}
            </button>
          )}

          <button
            onClick={handleExportCsv}
            className="inline-flex items-center gap-1.5 px-3 py-1.5 bg-white border border-slate-200 text-slate-700 hover:bg-slate-50 rounded-lg text-xs font-semibold shadow-sm transition"
          >
            <Download className="w-3.5 h-3.5 text-slate-500" />
            Export CSV
          </button>

          <button
            onClick={handleExportJson}
            className="inline-flex items-center gap-1.5 px-3 py-1.5 bg-white border border-slate-200 text-slate-700 hover:bg-slate-50 rounded-lg text-xs font-semibold shadow-sm transition"
          >
            <FileCode className="w-3.5 h-3.5 text-slate-500" />
            Export JSON
          </button>

          <button
            onClick={fetchInventory}
            disabled={loading}
            className="p-1.5 bg-white border border-slate-200 hover:bg-slate-50 rounded-lg text-slate-600 shadow-sm transition"
            title="Refresh Inventory"
          >
            <RefreshCw className={`w-4 h-4 ${loading ? 'animate-spin text-indigo-600' : ''}`} />
          </button>
        </div>
      </div>

      {/* Cycle Notice */}
      {cycleNotice && (
        <div className="p-3 bg-indigo-50 border border-indigo-200 rounded-lg text-xs text-indigo-800 flex items-center justify-between">
          <span>{cycleNotice}</span>
          <button onClick={() => setCycleNotice(null)} className="text-indigo-400 hover:text-indigo-600">
            <X className="w-4 h-4" />
          </button>
        </div>
      )}

      {/* KPI Cards */}
      <div className="grid grid-cols-2 sm:grid-cols-5 gap-3">
        <div className="p-4 bg-white border border-slate-200 rounded-xl shadow-sm">
          <span className="text-[11px] font-medium uppercase tracking-wider text-slate-500">Total Capsules</span>
          <div className="mt-1 text-2xl font-bold text-slate-900">{total}</div>
        </div>

        <div className="p-4 bg-white border border-slate-200 rounded-xl shadow-sm">
          <span className="text-[11px] font-medium uppercase tracking-wider text-emerald-600">Active</span>
          <div className="mt-1 text-2xl font-bold text-emerald-700">{activeCount}</div>
        </div>

        <div className="p-4 bg-white border border-slate-200 rounded-xl shadow-sm">
          <span className="text-[11px] font-medium uppercase tracking-wider text-amber-600">Pending Owner (Grace)</span>
          <div className="mt-1 text-2xl font-bold text-amber-600">{pendingOwnerCount}</div>
        </div>

        <div className="p-4 bg-white border border-slate-200 rounded-xl shadow-sm">
          <span className="text-[11px] font-medium uppercase tracking-wider text-orange-600">Expiring Soon</span>
          <div className="mt-1 text-2xl font-bold text-orange-600">{warningCount}</div>
        </div>

        <div className="p-4 bg-white border border-slate-200 rounded-xl shadow-sm">
          <span className="text-[11px] font-medium uppercase tracking-wider text-rose-600">Archived / Suspended</span>
          <div className="mt-1 text-2xl font-bold text-rose-600">{archivedCount}</div>
        </div>
      </div>

      {/* Filter Bar */}
      <div className="p-4 bg-white border border-slate-200 rounded-xl shadow-sm flex flex-col sm:flex-row gap-3 items-center justify-between">
        <div className="relative flex-1 w-full">
          <Search className="w-4 h-4 text-slate-400 absolute left-3 top-2.5" />
          <input
            type="text"
            placeholder="Search capsule name, key, or owner email..."
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            className="w-full pl-9 pr-3 py-1.5 text-xs bg-slate-50 border border-slate-200 rounded-lg focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:bg-white transition"
          />
        </div>

        <div className="flex flex-wrap items-center gap-2 w-full sm:w-auto">
          <select
            value={statusFilter}
            onChange={(e) => setStatusFilter(e.target.value)}
            className="text-xs bg-slate-50 border border-slate-200 rounded-lg px-2.5 py-1.5 text-slate-700 focus:outline-none focus:ring-2 focus:ring-indigo-500"
          >
            <option value="all">All Statuses</option>
            <option value="active">Active</option>
            <option value="suspended">Suspended</option>
            <option value="archived">Archived</option>
            <option value="draft">Draft</option>
          </select>

          <select
            value={govFilter}
            onChange={(e) => setGovFilter(e.target.value)}
            className="text-xs bg-slate-50 border border-slate-200 rounded-lg px-2.5 py-1.5 text-slate-700 focus:outline-none focus:ring-2 focus:ring-indigo-500"
          >
            <option value="all">All Governance States</option>
            <option value="normal">Normal</option>
            <option value="pending_owner">Pending Owner (In Grace)</option>
            <option value="grace_period_expired">Grace Period Expired</option>
            <option value="archived">Archived</option>
          </select>
        </div>
      </div>

      {/* Inventory Table */}
      <div className="bg-white border border-slate-200 rounded-xl shadow-sm overflow-hidden">
        <div className="overflow-x-auto">
          <table className="w-full text-left text-xs">
            <thead className="bg-slate-50 text-slate-500 font-semibold border-b border-slate-200">
              <tr>
                <th className="py-3 px-4">Capsule</th>
                <th className="py-3 px-4">Owner & Nominee</th>
                <th className="py-3 px-4">Status</th>
                <th className="py-3 px-4">Governance / Expiry</th>
                <th className="py-3 px-4">Users</th>
                <th className="py-3 px-4">Capabilities</th>
                <th className="py-3 px-4">Version</th>
                <th className="py-3 px-4">Last Activity</th>
                <th className="py-3 px-4 text-right">Actions</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {loading ? (
                <tr>
                  <td colSpan={9} className="py-12 text-center text-slate-400 font-mono">
                    Loading application inventory...
                  </td>
                </tr>
              ) : filtered.length === 0 ? (
                <tr>
                  <td colSpan={9} className="py-12 text-center text-slate-400">
                    No applications match the specified criteria.
                  </td>
                </tr>
              ) : (
                filtered.map((item) => {
                  const isUnowned = !item.owner;
                  const isPendingOwner = item.governance_state === 'pending_owner';

                  return (
                    <tr key={item.id} className="hover:bg-slate-50/80 transition">
                      {/* Capsule Name & Key */}
                      <td className="py-3 px-4">
                        <div className="font-semibold text-slate-900">
                          {onSelectApp ? (
                            <button
                              onClick={() => onSelectApp(item.id)}
                              className="hover:text-indigo-600 hover:underline text-left"
                            >
                              {item.name}
                            </button>
                          ) : (
                            item.name
                          )}
                        </div>
                        <div className="text-[11px] font-mono text-slate-400">{item.app_key}</div>
                      </td>

                      {/* Owner & Nominee */}
                      <td className="py-3 px-4">
                        {isPendingOwner ? (
                          <div className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[10px] font-medium bg-amber-100 text-amber-800">
                            <AlertTriangle className="w-3 h-3" />
                            Unowned (Grace Period)
                          </div>
                        ) : item.owner ? (
                          <div>
                            <div className="font-medium text-slate-800">{item.owner.display_name}</div>
                            <div className="text-[11px] font-mono text-slate-400">{item.owner.email}</div>
                          </div>
                        ) : (
                          <span className="text-slate-400 italic">No Owner</span>
                        )}

                        {item.nominated_owner && (
                          <div className="text-[10px] text-slate-400 flex items-center gap-1 mt-0.5">
                            <span className="text-slate-500">Nominee:</span>
                            <span className="font-mono">{item.nominated_owner.email}</span>
                          </div>
                        )}
                      </td>

                      {/* Status */}
                      <td className="py-3 px-4">
                        <span
                          className={`inline-flex items-center px-2 py-0.5 rounded text-[11px] font-medium ${
                            item.status === 'active'
                              ? 'bg-emerald-100 text-emerald-800'
                              : item.status === 'suspended'
                              ? 'bg-amber-100 text-amber-800'
                              : item.status === 'archived'
                              ? 'bg-slate-100 text-slate-700'
                              : 'bg-blue-100 text-blue-800'
                          }`}
                        >
                          {item.status}
                        </span>
                      </td>

                      {/* Governance / Expiry */}
                      <td className="py-3 px-4">
                        {isPendingOwner ? (
                          <span className="inline-flex items-center gap-1 text-[11px] font-medium text-amber-700">
                            <Clock className="w-3.5 h-3.5" />
                            Pending Owner
                          </span>
                        ) : item.expiry_status?.startsWith('warning') ? (
                          <span className="inline-flex items-center gap-1 text-[11px] font-medium text-orange-600">
                            <AlertTriangle className="w-3.5 h-3.5" />
                            {item.expiry_status.replace('_', ' ')}
                          </span>
                        ) : item.status === 'archived' ? (
                          <span className="inline-flex items-center gap-1 text-[11px] font-medium text-slate-500">
                            <Archive className="w-3.5 h-3.5" />
                            Archived
                          </span>
                        ) : (
                          <span className="inline-flex items-center gap-1 text-[11px] font-medium text-emerald-600">
                            <CheckCircle2 className="w-3.5 h-3.5" />
                            Healthy
                          </span>
                        )}
                        {item.expires_at && (
                          <div className="text-[10px] text-slate-400 mt-0.5">
                            Expires: {new Date(item.expires_at).toLocaleDateString()}
                          </div>
                        )}
                      </td>

                      {/* User Count */}
                      <td className="py-3 px-4">
                        <span className="inline-flex items-center gap-1 font-mono text-slate-700">
                          <Users className="w-3.5 h-3.5 text-slate-400" />
                          {item.user_count}
                        </span>
                      </td>

                      {/* Capabilities */}
                      <td className="py-3 px-4">
                        <div className="flex flex-wrap gap-1 max-w-[160px]">
                          {(item.capabilities || []).map((cap) => (
                            <span
                              key={cap}
                              className="px-1.5 py-0.5 bg-slate-100 text-slate-600 rounded text-[10px] font-mono"
                            >
                              {cap}
                            </span>
                          ))}
                          {(!item.capabilities || item.capabilities.length === 0) && (
                            <span className="text-slate-400 text-[11px] italic">None</span>
                          )}
                        </div>
                      </td>

                      {/* Version */}
                      <td className="py-3 px-4">
                        <span className="font-mono text-indigo-600 font-semibold">{item.current_version}</span>
                      </td>

                      {/* Last Activity */}
                      <td className="py-3 px-4 text-slate-500">
                        {item.last_activity_at ? (
                          <span title={item.last_activity_at}>
                            {new Date(item.last_activity_at).toLocaleDateString()}
                          </span>
                        ) : (
                          <span className="text-slate-400 italic">No activity</span>
                        )}
                      </td>

                      {/* Actions */}
                      <td className="py-3 px-4 text-right space-x-1 whitespace-nowrap">
                        <button
                          onClick={() => {
                            setTransferModalApp(item);
                            setTransferTargetId('');
                            setTransferError(null);
                          }}
                          className="p-1 text-slate-500 hover:text-indigo-600 hover:bg-indigo-50 rounded transition"
                          title="Transfer Ownership"
                        >
                          <ArrowRightLeft className="w-4 h-4" />
                        </button>

                        <button
                          onClick={() => handleDownloadAppData(item.id, item.app_key)}
                          className="p-1 text-slate-500 hover:text-emerald-600 hover:bg-emerald-50 rounded transition"
                          title="Download Data Snapshot"
                        >
                          <Download className="w-4 h-4" />
                        </button>
                      </td>
                    </tr>
                  );
                })
              )}
            </tbody>
          </table>
        </div>
      </div>

      {/* Ownership Transfer Modal */}
      {transferModalApp && (
        <div className="fixed inset-0 bg-slate-900/40 backdrop-blur-sm z-50 flex items-center justify-center p-4">
          <div className="bg-white rounded-2xl shadow-xl max-w-md w-full p-6 space-y-4 border border-slate-200">
            <div className="flex items-center justify-between pb-3 border-b border-slate-100">
              <h3 className="text-sm font-bold text-slate-900 flex items-center gap-2">
                <ArrowRightLeft className="w-4 h-4 text-indigo-600" />
                Transfer Application Ownership
              </h3>
              <button
                onClick={() => setTransferModalApp(null)}
                className="text-slate-400 hover:text-slate-600"
              >
                <X className="w-4 h-4" />
              </button>
            </div>

            <form onSubmit={executeTransfer} className="space-y-4 text-xs">
              <div>
                <label className="block text-slate-600 font-medium mb-1">Target Capsule</label>
                <div className="p-2.5 bg-slate-50 rounded-lg border border-slate-200 font-semibold text-slate-800">
                  {transferModalApp.name}{' '}
                  <span className="font-mono text-slate-400 text-[11px]">({transferModalApp.app_key})</span>
                </div>
              </div>

              <div>
                <label className="block text-slate-600 font-medium mb-1">Current Owner</label>
                <div className="text-slate-500">
                  {transferModalApp.owner ? transferModalApp.owner.email : 'Unowned (In Grace Period)'}
                </div>
              </div>

              <div>
                <label className="block text-slate-700 font-semibold mb-1">
                  New Owner User ID (UUID) <span className="text-rose-500">*</span>
                </label>
                <input
                  type="text"
                  required
                  placeholder="e.g. 550e8400-e29b-41d4-a716-446655440000"
                  value={transferTargetId}
                  onChange={(e) => setTransferTargetId(e.target.value)}
                  className="w-full px-3 py-2 text-xs bg-slate-50 border border-slate-200 rounded-lg font-mono focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:bg-white"
                />
                <p className="text-[10px] text-slate-400 mt-1">
                  Target user must be an active member of this organization.
                </p>
              </div>

              <div>
                <label className="block text-slate-700 font-semibold mb-1">Reason for Transfer</label>
                <input
                  type="text"
                  value={transferReason}
                  onChange={(e) => setTransferReason(e.target.value)}
                  className="w-full px-3 py-2 text-xs bg-slate-50 border border-slate-200 rounded-lg focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:bg-white"
                />
              </div>

              {transferError && (
                <div className="p-3 bg-rose-50 border border-rose-200 text-rose-700 rounded-lg text-xs">
                  {transferError}
                </div>
              )}

              <div className="pt-3 border-t border-slate-100 flex justify-end gap-2">
                <button
                  type="button"
                  onClick={() => setTransferModalApp(null)}
                  className="px-3 py-1.5 text-slate-600 hover:bg-slate-100 rounded-lg font-semibold"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  disabled={transferLoading}
                  className="px-4 py-1.5 bg-indigo-600 text-white rounded-lg font-semibold hover:bg-indigo-700 transition disabled:opacity-50"
                >
                  {transferLoading ? 'Transferring...' : 'Confirm Transfer'}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
};

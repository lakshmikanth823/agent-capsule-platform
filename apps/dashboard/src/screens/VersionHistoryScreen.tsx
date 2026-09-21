import React, { useState, useEffect } from 'react';
import { AppSummary, AppVersion } from '../types';
import { api } from '../api';
import { History, Database, Package, Calendar, User, ArrowRight, RotateCcw, AlertTriangle, X, Check } from 'lucide-react';

interface VersionHistoryScreenProps {
  onSelectApp: (appId: string) => void;
}

export const VersionHistoryScreen: React.FC<VersionHistoryScreenProps> = ({ onSelectApp }) => {
  const [apps, setApps] = useState<AppSummary[]>([]);
  const [selectedAppId, setSelectedAppId] = useState<string>('');
  const [versions, setVersions] = useState<AppVersion[]>([]);
  const [loading, setLoading] = useState(true);

  // Rollback Modal State
  const [rollbackModalVer, setRollbackModalVer] = useState<AppVersion | null>(null);
  const [rollbackMode, setRollbackMode] = useState<'code_only' | 'code_and_data'>('code_only');
  const [confirmDataRestore, setConfirmDataRestore] = useState(false);
  const [rollbackReason, setRollbackReason] = useState('');
  const [rollbackLoading, setRollbackLoading] = useState(false);
  const [rollbackError, setRollbackError] = useState<string | null>(null);
  const [rollbackSuccess, setRollbackSuccess] = useState<string | null>(null);

  useEffect(() => {
    loadApps();
  }, []);

  useEffect(() => {
    if (selectedAppId) {
      loadVersions(selectedAppId);
    }
  }, [selectedAppId]);

  const loadApps = async () => {
    try {
      setLoading(true);
      const list = await api.listApps();
      setApps(list);
      if (list.length > 0) {
        setSelectedAppId(list[0].id);
      }
    } finally {
      setLoading(false);
    }
  };

  const loadVersions = async (appId: string) => {
    try {
      const list = await api.listVersions(appId);
      setVersions(list);
    } catch {
      setVersions([]);
    }
  };

  const handleExecuteRollback = async () => {
    if (!rollbackModalVer) return;
    try {
      setRollbackLoading(true);
      setRollbackError(null);
      await api.rollbackApp(rollbackModalVer.app_id, {
        target_version_number: rollbackModalVer.version_number,
        mode: rollbackMode,
        confirm_data_restore: rollbackMode === 'code_and_data' ? confirmDataRestore : false,
        reason: rollbackReason || undefined,
      });

      setRollbackSuccess(`Successfully rolled back to version ${rollbackModalVer.version_number}!`);
      setTimeout(() => {
        setRollbackModalVer(null);
        setRollbackSuccess(null);
        loadVersions(rollbackModalVer.app_id);
      }, 1200);
    } catch (err: any) {
      setRollbackError(err.message || 'Rollback failed.');
    } finally {
      setRollbackLoading(false);
    }
  };

  return (
    <div className="space-y-6 max-w-5xl mx-auto">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-xl font-bold text-slate-900 tracking-tight flex items-center gap-2">
            <History className="w-5 h-5 text-indigo-600" />
            Version History & Snapshots
          </h2>
          <p className="text-xs text-slate-500 mt-1">
            Audit immutable versions, artifacts, and database state snapshots.
          </p>
        </div>

        {apps.length > 0 && (
          <select
            value={selectedAppId}
            onChange={(e) => setSelectedAppId(e.target.value)}
            className="px-3 py-1.5 text-xs font-semibold border border-slate-300 rounded-lg bg-white shadow-sm"
          >
            {apps.map((app) => (
              <option key={app.id} value={app.id}>
                {app.name} ({app.app_key})
              </option>
            ))}
          </select>
        )}
      </div>

      {loading ? (
        <div className="py-16 text-center text-xs text-slate-400">Loading version history...</div>
      ) : versions.length === 0 ? (
        <div className="p-8 bg-white border border-slate-200 rounded-2xl text-center">
          <p className="text-sm font-semibold text-slate-700">No published versions found</p>
          <p className="text-xs text-slate-400 mt-1">
            Publish a release via CLI: <code className="font-mono text-indigo-600">capsule publish</code>
          </p>
        </div>
      ) : (
        <div className="relative border-l-2 border-indigo-200 ml-4 pl-6 space-y-6">
          {versions.map((ver, idx) => (
            <div key={ver.id} className="relative group">
              {/* Timeline marker */}
              <div className="absolute -left-[31px] top-1.5 w-4 h-4 rounded-full bg-indigo-600 border-4 border-white shadow" />

              <div className="bg-white border border-slate-200 rounded-xl p-5 shadow-sm hover:border-indigo-300 transition-all">
                <div className="flex items-center justify-between mb-2">
                  <div className="flex items-center gap-2">
                    <span className="font-mono font-bold text-sm bg-indigo-50 text-indigo-700 px-2 py-0.5 rounded border border-indigo-200">
                      v{ver.version_number}
                    </span>
                    <h3 className="text-sm font-bold text-slate-900">
                      {ver.change_description || 'Production release'}
                    </h3>
                  </div>
                  <div className="flex items-center gap-2">
                    <span className={`px-2 py-0.5 rounded text-[10px] font-bold uppercase ${
                      ver.status === 'published' ? 'bg-emerald-100 text-emerald-800' : 'bg-amber-100 text-amber-800'
                    }`}>
                      {ver.status}
                    </span>
                    <button
                      onClick={() => {
                        setRollbackModalVer(ver);
                        setRollbackMode('code_only');
                        setConfirmDataRestore(false);
                        setRollbackReason('');
                        setRollbackError(null);
                        setRollbackSuccess(null);
                      }}
                      className="px-2.5 py-1 text-xs font-semibold text-slate-700 bg-slate-100 hover:bg-indigo-50 hover:text-indigo-600 rounded-lg flex items-center gap-1 transition-colors border border-slate-200"
                      title="Roll back to this version"
                    >
                      <RotateCcw className="w-3 h-3" />
                      Rollback
                    </button>
                  </div>
                </div>

                <div className="grid grid-cols-1 md:grid-cols-4 gap-3 my-3 text-xs text-slate-600 bg-slate-50 p-3 rounded-lg border border-slate-100">
                  <div className="flex items-center gap-2">
                    <Calendar className="w-3.5 h-3.5 text-slate-400" />
                    <span>{new Date(ver.published_at || ver.created_at).toLocaleString()}</span>
                  </div>
                  <div className="flex items-center gap-2">
                    <User className="w-3.5 h-3.5 text-slate-400" />
                    <span className="truncate">Publisher: {ver.publisher_name || ver.publisher_agent || 'Alice Owner'}</span>
                  </div>
                  <div className="flex items-center gap-2">
                    <Package className="w-3.5 h-3.5 text-slate-400" />
                    <span className="font-mono truncate">
                      Artifact: {ver.source_artifact_ref || 'Local bundle'}
                    </span>
                  </div>
                  <div className="flex items-center gap-2">
                    <Database className="w-3.5 h-3.5 text-slate-400" />
                    <span className="font-mono truncate">
                      Snapshot: {ver.db_snapshot_ref || 'None'}
                    </span>
                  </div>
                </div>

                <div className="flex items-center justify-between text-xs text-slate-500 pt-2 border-t border-slate-100">
                  <span className="font-mono text-[11px]">
                    Version ID: {ver.id}
                  </span>
                  <button
                    onClick={() => onSelectApp(ver.app_id)}
                    className="text-indigo-600 hover:text-indigo-800 font-semibold flex items-center gap-1 transition-colors"
                  >
                    View in Capsule Detail
                    <ArrowRight className="w-3.5 h-3.5" />
                  </button>
                </div>
              </div>
            </div>
          ))}
        </div>
      )}

      {/* Rollback Modal */}
      {rollbackModalVer && (
        <div className="fixed inset-0 bg-slate-900/50 backdrop-blur-sm flex items-center justify-center p-4 z-50">
          <div className="bg-white rounded-2xl max-w-lg w-full p-6 shadow-2xl border border-slate-100 space-y-5">
            <div className="flex items-center justify-between border-b border-slate-100 pb-3">
              <div className="flex items-center gap-2">
                <RotateCcw className="w-5 h-5 text-indigo-600" />
                <h3 className="text-base font-bold text-slate-900">
                  Rollback to Version {rollbackModalVer.version_number}
                </h3>
              </div>
              <button
                onClick={() => setRollbackModalVer(null)}
                className="text-slate-400 hover:text-slate-600 p-1"
              >
                <X className="w-5 h-5" />
              </button>
            </div>

            {rollbackError && (
              <div className="p-3 bg-red-50 border border-red-200 text-red-700 text-xs rounded-lg flex items-start gap-2">
                <AlertTriangle className="w-4 h-4 mt-0.5 shrink-0" />
                <span>{rollbackError}</span>
              </div>
            )}

            {rollbackSuccess && (
              <div className="p-3 bg-emerald-50 border border-emerald-200 text-emerald-700 text-xs rounded-lg flex items-center gap-2">
                <Check className="w-4 h-4 shrink-0" />
                <span>{rollbackSuccess}</span>
              </div>
            )}

            <div className="space-y-4 text-xs">
              <label className="block font-semibold text-slate-700">Choose Rollback Mode:</label>

              <div className="space-y-2">
                <label className={`block p-3 rounded-xl border cursor-pointer transition-all ${
                  rollbackMode === 'code_only' ? 'border-indigo-600 bg-indigo-50/40 ring-1 ring-indigo-600' : 'border-slate-200 hover:border-slate-300'
                }`}>
                  <div className="flex items-center gap-2">
                    <input
                      type="radio"
                      name="rollback_mode"
                      value="code_only"
                      checked={rollbackMode === 'code_only'}
                      onChange={() => setRollbackMode('code_only')}
                      className="text-indigo-600"
                    />
                    <span className="font-bold text-slate-800">Code-only (Recommended)</span>
                  </div>
                  <p className="text-slate-500 mt-1 pl-5">
                    Restores application code and manifest to v{rollbackModalVer.version_number} while preserving current database records.
                  </p>
                </label>

                <label className={`block p-3 rounded-xl border cursor-pointer transition-all ${
                  rollbackMode === 'code_and_data' ? 'border-amber-600 bg-amber-50/40 ring-1 ring-amber-600' : 'border-slate-200 hover:border-slate-300'
                }`}>
                  <div className="flex items-center gap-2">
                    <input
                      type="radio"
                      name="rollback_mode"
                      value="code_and_data"
                      checked={rollbackMode === 'code_and_data'}
                      onChange={() => setRollbackMode('code_and_data')}
                      className="text-amber-600"
                    />
                    <span className="font-bold text-slate-800">Code + Data Restore (Destructive)</span>
                  </div>
                  <p className="text-slate-500 mt-1 pl-5">
                    Restores application code AND overwrites current database with the snapshot from v{rollbackModalVer.version_number}.
                  </p>
                </label>
              </div>

              {rollbackMode === 'code_and_data' && (
                <div className="p-4 bg-amber-50 border border-amber-200 rounded-xl space-y-3">
                  <div className="flex items-start gap-2 text-amber-800 font-semibold">
                    <AlertTriangle className="w-4 h-4 shrink-0 mt-0.5" />
                    <span>Data Loss Warning</span>
                  </div>
                  <p className="text-amber-700 text-[11px] leading-relaxed">
                    This operation will replace current database state with the snapshot associated with version {rollbackModalVer.version_number}.
                    Any records created after {new Date(rollbackModalVer.published_at || rollbackModalVer.created_at).toLocaleString()} may be lost.
                    A fresh recovery snapshot will be created immediately before rollback so this operation can be undone.
                  </p>
                  <label className="flex items-center gap-2 pt-1 cursor-pointer font-medium text-amber-900">
                    <input
                      type="checkbox"
                      checked={confirmDataRestore}
                      onChange={(e) => setConfirmDataRestore(e.target.checked)}
                      className="rounded border-amber-400 text-amber-600 focus:ring-amber-500"
                    />
                    <span>I confirm and authorize database state replacement</span>
                  </label>
                </div>
              )}

              <div>
                <label className="block font-semibold text-slate-700 mb-1">Reason (Optional):</label>
                <input
                  type="text"
                  placeholder="e.g. Revert bug introduced in previous version"
                  value={rollbackReason}
                  onChange={(e) => setRollbackReason(e.target.value)}
                  className="w-full px-3 py-2 border border-slate-300 rounded-lg text-xs"
                />
              </div>
            </div>

            <div className="flex items-center justify-end gap-3 pt-3 border-t border-slate-100">
              <button
                type="button"
                onClick={() => setRollbackModalVer(null)}
                disabled={rollbackLoading}
                className="px-4 py-2 text-xs font-semibold text-slate-600 hover:bg-slate-100 rounded-lg"
              >
                Cancel
              </button>
              <button
                type="button"
                onClick={handleExecuteRollback}
                disabled={rollbackLoading || (rollbackMode === 'code_and_data' && !confirmDataRestore)}
                className={`px-4 py-2 text-xs font-semibold text-white rounded-lg flex items-center gap-2 transition-all ${
                  rollbackMode === 'code_and_data' ? 'bg-amber-600 hover:bg-amber-700 disabled:opacity-50' : 'bg-indigo-600 hover:bg-indigo-700 disabled:opacity-50'
                }`}
              >
                {rollbackLoading ? 'Rolling back...' : `Execute Rollback to v${rollbackModalVer.version_number}`}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};

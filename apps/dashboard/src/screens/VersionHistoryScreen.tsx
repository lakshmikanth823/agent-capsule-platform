import React, { useState, useEffect } from 'react';
import { AppSummary, AppVersion } from '../types';
import { api } from '../api';
import { History, Database, Package, Calendar, User, ArrowRight } from 'lucide-react';

interface VersionHistoryScreenProps {
  onSelectApp: (appId: string) => void;
}

export const VersionHistoryScreen: React.FC<VersionHistoryScreenProps> = ({ onSelectApp }) => {
  const [apps, setApps] = useState<AppSummary[]>([]);
  const [selectedAppId, setSelectedAppId] = useState<string>('');
  const [versions, setVersions] = useState<AppVersion[]>([]);
  const [loading, setLoading] = useState(true);

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
                  <span className="px-2 py-0.5 rounded text-[10px] font-bold bg-emerald-100 text-emerald-800 uppercase">
                    {ver.status}
                  </span>
                </div>

                <div className="grid grid-cols-1 md:grid-cols-3 gap-3 my-3 text-xs text-slate-600 bg-slate-50 p-3 rounded-lg border border-slate-100">
                  <div className="flex items-center gap-2">
                    <Calendar className="w-3.5 h-3.5 text-slate-400" />
                    <span>{new Date(ver.published_at || ver.created_at).toLocaleString()}</span>
                  </div>
                  <div className="flex items-center gap-2">
                    <Package className="w-3.5 h-3.5 text-slate-400" />
                    <span className="font-mono truncate">
                      Artifact: {ver.source_artifact_ref || 'Local build bundle'}
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
    </div>
  );
};

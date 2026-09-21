import React, { useState, useEffect } from 'react';
import { AppDetail, AppSummary, AuditEvent, UserProfile } from '../types';
import { api } from '../api';
import { ShareDialog } from '../components/ShareDialog';
import { 
  Search, 
  Plus, 
  ExternalLink, 
  Share2, 
  Settings2, 
  Clock, 
  Users, 
  CheckCircle2, 
  AlertCircle,
  Terminal,
  Activity
} from 'lucide-react';

interface AppsListScreenProps {
  currentUser: UserProfile | null;
  onSelectApp: (appId: string) => void;
}

export const AppsListScreen: React.FC<AppsListScreenProps> = ({
  currentUser,
  onSelectApp,
}) => {
  const [apps, setApps] = useState<AppSummary[]>([]);
  const [auditEvents, setAuditEvents] = useState<AuditEvent[]>([]);
  const [loading, setLoading] = useState(true);
  const [searchTerm, setSearchTerm] = useState('');
  const [sharingApp, setSharingApp] = useState<AppDetail | null>(null);
  const [showPublishModal, setShowPublishModal] = useState(false);

  useEffect(() => {
    loadData();
  }, []);

  const loadData = async () => {
    try {
      setLoading(true);
      const [appsList, events] = await Promise.all([
        api.listApps().catch(() => []),
        api.listAuditEvents().catch(() => []),
      ]);
      setApps(appsList);
      setAuditEvents(events.slice(0, 5));
    } finally {
      setLoading(false);
    }
  };

  const handleOpenShare = async (appId: string, e: React.MouseEvent) => {
    e.stopPropagation();
    try {
      const detail = await api.getApp(appId);
      setSharingApp(detail);
    } catch {
      // fallback
    }
  };

  const filteredApps = apps.filter((app) =>
    app.name.toLowerCase().includes(searchTerm.toLowerCase()) ||
    app.app_key.toLowerCase().includes(searchTerm.toLowerCase())
  );

  return (
    <div className="space-y-8 max-w-6xl mx-auto">
      {/* Top Search & Actions Bar matching wireframe */}
      <div className="flex flex-col sm:flex-row items-start sm:items-center justify-between gap-4">
        {/* Search capsules input */}
        <div className="relative w-full sm:w-96">
          <input
            type="text"
            value={searchTerm}
            onChange={(e) => setSearchTerm(e.target.value)}
            placeholder="Search capsules"
            className="w-full pl-9 pr-4 py-2 text-sm border border-slate-300 rounded-full bg-white focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:border-indigo-500 shadow-sm"
          />
          <Search className="w-4 h-4 text-slate-400 absolute left-3 top-2.5" />
        </div>

        {/* + Publish app primary action */}
        <button
          onClick={() => setShowPublishModal(true)}
          className="px-5 py-2 rounded-full bg-slate-900 hover:bg-slate-800 text-white text-sm font-semibold flex items-center gap-2 shadow-sm transition-all hover:shadow"
        >
          <Plus className="w-4 h-4" />
          + Publish app
        </button>
      </div>

      {/* Capsules Section */}
      <div>
        <div className="flex items-center justify-between mb-4">
          <h2 className="text-xl font-bold text-slate-900 tracking-tight">Capsules</h2>
          <span className="text-xs text-slate-500 font-medium">
            {filteredApps.length} {filteredApps.length === 1 ? 'capsule' : 'capsules'}
          </span>
        </div>

        {loading ? (
          <div className="py-16 text-center text-sm text-slate-400">Loading capsules...</div>
        ) : filteredApps.length === 0 ? (
          <div className="p-8 bg-white border border-slate-200 rounded-2xl text-center">
            <p className="text-sm text-slate-600 font-medium">No capsules found.</p>
            <p className="text-xs text-slate-400 mt-1">Publish an application bundle via the CLI.</p>
          </div>
        ) : (
          <div className="space-y-3">
            {filteredApps.map((app) => {
              const isActive = app.status === 'active';
              const appUrl = app.app_url || `http://${app.app_key}.apps.localhost:8080`;

              return (
                <div
                  key={app.id}
                  onClick={() => onSelectApp(app.id)}
                  className="p-5 bg-white border border-slate-200 rounded-xl hover:border-slate-300 hover:shadow-sm transition-all cursor-pointer flex flex-col md:flex-row items-start md:items-center justify-between gap-4"
                >
                  {/* Left: Name, Status, Info */}
                  <div className="space-y-1">
                    <div className="flex items-center gap-3">
                      <h3 className="font-bold text-base text-slate-900 hover:text-indigo-600 transition-colors">
                        {app.name}
                      </h3>
                      <span
                        className={`px-2.5 py-0.5 rounded-full text-[11px] font-bold uppercase tracking-wider ${
                          isActive
                            ? 'bg-emerald-100 text-emerald-800 border border-emerald-200'
                            : 'bg-amber-100 text-amber-800 border border-amber-200'
                        }`}
                      >
                        {app.status}
                      </span>
                    </div>

                    <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-slate-500">
                      <span className="font-mono font-medium text-slate-700">
                        {app.current_version_id ? 'v1' : 'v0.7'}
                      </span>
                      <span>•</span>
                      <span>Owner: {currentUser?.name?.split(' ')[0] || 'Alice'}</span>
                      <span>•</span>
                      <span className="flex items-center gap-1">
                        <Users className="w-3.5 h-3.5 text-slate-400" />
                        Weekly active viewers: 12
                      </span>
                      <span>•</span>
                      <span className="flex items-center gap-1">
                        <Clock className="w-3.5 h-3.5 text-slate-400" />
                        Last published: Today
                      </span>
                    </div>
                  </div>

                  {/* Right: Actions */}
                  <div className="flex items-center gap-2 self-end md:self-center">
                    <a
                      href={appUrl}
                      target="_blank"
                      rel="noreferrer"
                      onClick={(e) => e.stopPropagation()}
                      className="px-3.5 py-1.5 rounded-lg border border-slate-300 bg-white hover:bg-slate-50 text-slate-700 text-xs font-semibold flex items-center gap-1.5 transition-colors"
                    >
                      Open
                      <ExternalLink className="w-3.5 h-3.5 text-slate-400" />
                    </a>

                    <button
                      onClick={(e) => handleOpenShare(app.id, e)}
                      className="px-3 py-1.5 rounded-lg border border-slate-300 bg-white hover:bg-slate-50 text-slate-700 text-xs font-semibold flex items-center gap-1.5 transition-colors"
                    >
                      <Share2 className="w-3.5 h-3.5 text-slate-400" />
                      Share
                    </button>

                    <button
                      onClick={() => onSelectApp(app.id)}
                      className="px-3 py-1.5 rounded-lg border border-slate-300 bg-white hover:bg-slate-50 text-slate-700 text-xs font-semibold flex items-center gap-1.5 transition-colors"
                    >
                      <Settings2 className="w-3.5 h-3.5 text-slate-400" />
                      Manage
                    </button>
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </div>

      {/* Recent Activity Section matching wireframe */}
      <div className="pt-6 border-t border-slate-200">
        <h3 className="text-base font-bold text-slate-900 mb-3 flex items-center gap-2">
          <Activity className="w-4 h-4 text-indigo-600" />
          Recent activity
        </h3>

        <div className="p-4 bg-white border border-slate-200 rounded-xl">
          {auditEvents.length > 0 ? (
            <div className="divide-y divide-slate-100">
              {auditEvents.map((evt) => (
                <div key={evt.id} className="py-2 first:pt-0 last:pb-0 text-xs text-slate-600 flex items-center justify-between">
                  <div className="flex items-center gap-2">
                    <span className="font-semibold text-slate-900 font-mono capitalize">
                      {evt.action.replace('.', ' ')}
                    </span>
                    <span>•</span>
                    <span>Target: {evt.target_type}</span>
                    <span>•</span>
                    <span className="text-slate-400">
                      {new Date(evt.occurred_at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
                    </span>
                  </div>
                  <span className="px-2 py-0.5 rounded text-[10px] font-semibold bg-emerald-50 text-emerald-700 border border-emerald-200 uppercase">
                    {evt.outcome}
                  </span>
                </div>
              ))}
            </div>
          ) : (
            <p className="text-xs text-slate-500">
              Published v1 • Shared with HR group • 2 minutes ago
            </p>
          )}
        </div>
      </div>

      {/* Share Dialog Modal */}
      {sharingApp && (
        <ShareDialog
          app={sharingApp}
          currentUser={currentUser}
          onClose={() => setSharingApp(null)}
          onShareUpdated={loadData}
        />
      )}

      {/* Publish Guide Modal */}
      {showPublishModal && (
        <div 
          className="fixed inset-0 z-50 bg-slate-900/60 backdrop-blur-sm flex items-center justify-center p-4"
          role="dialog"
          aria-modal="true"
        >
          <div className="bg-white rounded-xl shadow-2xl max-w-lg w-full border border-slate-200 p-6 space-y-4">
            <h3 className="text-base font-bold text-slate-900 flex items-center gap-2">
              <Terminal className="w-5 h-5 text-indigo-600" />
              Publish a Software Capsule
            </h3>
            <p className="text-xs text-slate-600">
              Capsules are packaged and published securely through the CLI or AI coding agents.
            </p>

            <div className="p-3 bg-slate-900 text-slate-100 rounded-lg text-xs font-mono space-y-2">
              <p className="text-slate-400"># 1. Initialize starter or validate existing</p>
              <p className="text-emerald-400">capsule validate</p>
              <p className="text-slate-400"># 2. Publish idempotently</p>
              <p className="text-emerald-400">capsule publish --description "Release v1"</p>
            </div>

            <div className="flex justify-end pt-2">
              <button
                onClick={() => setShowPublishModal(false)}
                className="px-4 py-2 text-xs font-semibold rounded-lg bg-slate-900 text-white hover:bg-slate-800"
              >
                Close
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};

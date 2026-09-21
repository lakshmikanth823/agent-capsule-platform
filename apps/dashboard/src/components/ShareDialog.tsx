import React, { useState, useEffect } from 'react';
import { AppDetail, AppShare, UserProfile } from '../types';
import { api } from '../api';
import { 
  X, 
  Copy, 
  Check, 
  AlertTriangle, 
  ShieldAlert, 
  Database, 
  HardDrive, 
  Globe, 
  UserCheck, 
  Cpu, 
  Share2, 
  Trash2,
  Lock
} from 'lucide-react';

interface ShareDialogProps {
  app: AppDetail;
  currentUser: UserProfile | null;
  onClose: () => void;
  onShareUpdated?: () => void;
}

export const ShareDialog: React.FC<ShareDialogProps> = ({
  app,
  currentUser,
  onClose,
  onShareUpdated,
}) => {
  const [shares, setShares] = useState<AppShare[]>([]);
  const [loading, setLoading] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [copied, setCopied] = useState(false);
  const [targetInput, setTargetInput] = useState('');
  const [selectedRole, setSelectedRole] = useState('');
  const [error, setError] = useState<string | null>(null);

  // Manifest declared roles
  const declaredRoles = app.manifest?.roles || ['employee', 'manager', 'hr'];

  // Check if current user is owner or editor
  const canManageShares = 
    currentUser?.platform_role === 'owner' || 
    currentUser?.platform_role === 'editor' ||
    currentUser?.id === app.owner_user_id;

  // Derive app URL
  const appUrl = app.app_url || `http://${app.app_key}.apps.localhost:8080`;

  useEffect(() => {
    if (declaredRoles.length > 0 && !selectedRole) {
      setSelectedRole(declaredRoles[0]);
    }
    loadShares();
  }, [app.id]);

  const loadShares = async () => {
    try {
      setLoading(true);
      const res = await api.listShares(app.id);
      setShares(res.shares || []);
    } catch (err: any) {
      setError(err.message || 'Failed to load shares');
    } finally {
      setLoading(false);
    }
  };

  const handleCopyLink = async () => {
    try {
      await navigator.clipboard.writeText(appUrl);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      // fallback
    }
  };

  const handleAddShare = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!targetInput.trim() || !selectedRole) return;

    try {
      setSubmitting(true);
      setError(null);

      const isEmail = targetInput.includes('@');
      await api.createShare(app.id, {
        user_email: isEmail ? targetInput.trim() : undefined,
        group_name: !isEmail ? targetInput.trim() : undefined,
        app_role: selectedRole,
      });

      setTargetInput('');
      await loadShares();
      if (onShareUpdated) onShareUpdated();
    } catch (err: any) {
      setError(err.message || 'Failed to assign share');
    } finally {
      setSubmitting(false);
    }
  };

  const handleRevokeShare = async (shareId: string) => {
    try {
      setError(null);
      await api.revokeShare(app.id, shareId);
      await loadShares();
      if (onShareUpdated) onShareUpdated();
    } catch (err: any) {
      setError(err.message || 'Failed to revoke share');
    }
  };

  // Keyboard accessibility: Escape to close
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [onClose]);

  // Plain-language capability representations
  const hasIdentity = app.manifest?.capabilities?.identity !== false;
  const dbLimit = app.manifest?.capabilities?.db?.size_limit_mb || 500;
  const filesLimit = app.manifest?.capabilities?.files?.size_limit_mb || 200;
  const egressList = app.manifest?.capabilities?.network?.egress || [];
  // Parse connectors dynamically from manifest
  const rawConnectors = app.manifest?.capabilities?.connectors;
  const parsedConnectors: Array<{ name: string; channel?: string; acts_as: string }> = [];
  if (Array.isArray(rawConnectors)) {
    for (const c of rawConnectors) {
      if (typeof c === 'string') {
        parsedConnectors.push({ name: c, acts_as: 'viewer' });
      } else if (c && typeof c === 'object') {
        parsedConnectors.push({
          name: c.name || 'unnamed',
          channel: c.channel,
          acts_as: c.acts_as || c.identity || 'viewer',
        });
      }
    }
  } else if (rawConnectors && typeof rawConnectors === 'object') {
    for (const [name, val] of Object.entries(rawConnectors)) {
      const v: any = val;
      parsedConnectors.push({
        name,
        channel: v?.channel,
        acts_as: v?.as_service_identity || v?.acts_as === 'service' ? 'service' : 'viewer',
      });
    }
  }
  const hasConnectors = parsedConnectors.length > 0;
  const hasServiceIdentity = parsedConnectors.some((c) => c.acts_as === 'service');

  return (
    <div 
      className="fixed inset-0 z-50 bg-slate-900/60 backdrop-blur-sm flex items-center justify-center p-4 overflow-y-auto"
      role="dialog"
      aria-modal="true"
      aria-labelledby="share-dialog-title"
    >
      <div className="bg-white rounded-xl shadow-2xl max-w-2xl w-full border border-slate-200 overflow-hidden my-8">
        {/* Header matching wireframe */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-slate-200 bg-slate-50">
          <div>
            <h2 id="share-dialog-title" className="text-lg font-bold text-slate-900 flex items-center gap-2">
              <Share2 className="w-5 h-5 text-indigo-600" />
              Share — {app.name}
            </h2>
            <p className="text-xs text-slate-500 font-mono">ORG / Acme</p>
          </div>
          <button
            onClick={onClose}
            aria-label="Close dialog"
            className="text-slate-400 hover:text-slate-700 p-1.5 rounded-lg hover:bg-slate-200 transition-colors"
          >
            <X className="w-5 h-5" />
          </button>
        </div>

        <div className="p-6 space-y-6 max-h-[80vh] overflow-y-auto">
          {error && (
            <div className="p-3 bg-rose-50 border border-rose-200 text-rose-700 text-xs rounded-lg flex items-center gap-2">
              <AlertTriangle className="w-4 h-4 shrink-0" />
              <span>{error}</span>
            </div>
          )}

          {/* App URL with copy link */}
          <div>
            <label className="block text-xs font-semibold text-slate-700 uppercase tracking-wider mb-1.5">
              App URL
            </label>
            <div className="flex items-center gap-2">
              <input
                type="text"
                readOnly
                value={appUrl}
                className="flex-1 px-3 py-2 text-xs font-mono bg-slate-100 border border-slate-200 rounded-lg text-slate-700 focus:outline-none"
              />
              <button
                onClick={handleCopyLink}
                className="px-3 py-2 text-xs font-medium border border-slate-300 rounded-lg bg-white hover:bg-slate-50 text-slate-700 flex items-center gap-1.5 transition-colors"
              >
                {copied ? <Check className="w-3.5 h-3.5 text-emerald-600" /> : <Copy className="w-3.5 h-3.5" />}
                {copied ? 'Copied' : 'Copy link'}
              </button>
            </div>
          </div>

          {/* People or groups input + Application role selector */}
          <form onSubmit={handleAddShare} className="space-y-3 pt-2 border-t border-slate-100">
            <div>
              <label htmlFor="people-input" className="block text-xs font-semibold text-slate-700 uppercase tracking-wider mb-1.5">
                People or groups
              </label>
              <input
                id="people-input"
                type="text"
                disabled={!canManageShares}
                value={targetInput}
                onChange={(e) => setTargetInput(e.target.value)}
                placeholder="name@company.com or group"
                className="w-full px-3 py-2 text-sm border border-slate-300 rounded-lg focus:ring-2 focus:ring-indigo-500 focus:border-indigo-500 disabled:bg-slate-100 disabled:text-slate-400"
              />
            </div>

            <div className="flex items-center justify-between gap-4">
              <div className="flex-1">
                <label htmlFor="role-select" className="block text-xs font-semibold text-slate-700 uppercase tracking-wider mb-1.5">
                  Application role
                </label>
                <div className="flex items-center gap-3">
                  <select
                    id="role-select"
                    disabled={!canManageShares}
                    value={selectedRole}
                    onChange={(e) => setSelectedRole(e.target.value)}
                    className="flex-1 px-3 py-2 text-sm border border-slate-300 rounded-lg bg-white focus:ring-2 focus:ring-indigo-500 focus:border-indigo-500 capitalize disabled:bg-slate-100"
                  >
                    {declaredRoles.map((role) => (
                      <option key={role} value={role}>
                        {role}
                      </option>
                    ))}
                  </select>
                  <span className="text-xs text-slate-500 font-medium whitespace-nowrap">
                    Platform access: User
                  </span>
                </div>
              </div>

              <div className="pt-5">
                <button
                  type="submit"
                  disabled={!canManageShares || !targetInput.trim() || submitting}
                  className="px-4 py-2 text-sm font-semibold rounded-lg bg-indigo-600 text-white hover:bg-indigo-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
                >
                  {submitting ? 'Sharing...' : 'Share'}
                </button>
              </div>
            </div>
          </form>

          {/* Current access list */}
          <div className="pt-2 border-t border-slate-100">
            <h3 className="text-xs font-semibold text-slate-700 uppercase tracking-wider mb-2">
              Current access
            </h3>
            {loading ? (
              <div className="py-4 text-center text-xs text-slate-400">Loading access list...</div>
            ) : shares.length === 0 ? (
              <div className="py-3 px-4 bg-slate-50 border border-slate-200 rounded-lg text-xs text-slate-500">
                No explicit shares granted yet. App is accessible according to organization default policy.
              </div>
            ) : (
              <div className="border border-slate-200 rounded-lg divide-y divide-slate-100 overflow-hidden">
                {shares.map((share) => (
                  <div key={share.id} className="flex items-center justify-between px-4 py-2.5 hover:bg-slate-50 text-xs">
                    <div className="flex items-center gap-2">
                      <span className="font-medium text-slate-900">
                        {share.user_email || (share.group_name ? `Group: ${share.group_name}` : share.user_id)}
                      </span>
                      {share.status === 'revoked' && (
                        <span className="px-1.5 py-0.5 rounded text-[10px] font-semibold bg-slate-100 text-slate-500">
                          Revoked
                        </span>
                      )}
                    </div>
                    <div className="flex items-center gap-4">
                      <span className="font-medium text-slate-600 capitalize bg-slate-100 px-2 py-0.5 rounded text-[11px]">
                        {share.app_role}
                      </span>
                      {canManageShares && share.status === 'active' && (
                        <button
                          onClick={() => handleRevokeShare(share.id)}
                          title="Revoke access"
                          className="px-2.5 py-1 rounded text-xs font-medium text-rose-600 border border-rose-200 hover:bg-rose-50 transition-colors flex items-center gap-1"
                        >
                          <Trash2 className="w-3 h-3" />
                          Revoke
                        </button>
                      )}
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>

          {/* External / Guest Note */}
          <div className="p-3 bg-slate-100 border border-slate-200 rounded-lg text-xs text-slate-600 flex items-center gap-2">
            <Lock className="w-4 h-4 text-slate-500 shrink-0" />
            <span>
              External / guest access is disabled by default. Only Owner or Editor can change assignments.
            </span>
          </div>

          {/* PERMISSION PREVIEW IN PLAIN LANGUAGE (Prompt 11 & Wireframe) */}
          <div className="pt-4 border-t-2 border-slate-200">
            <div className="mb-3">
              <h3 className="text-sm font-bold text-slate-900 flex items-center gap-2">
                <ShieldAlert className="w-4 h-4 text-indigo-600" />
                Permission Preview
              </h3>
              <p className="text-xs text-slate-500">
                Review what this Capsule can access in plain language before sharing or publishing.
              </p>
            </div>

            <div className="grid grid-cols-2 gap-3">
              {/* Identity */}
              <div className="p-3 rounded-lg border border-slate-200 bg-slate-50">
                <div className="flex items-center gap-2 mb-1">
                  <UserCheck className="w-4 h-4 text-indigo-600" />
                  <span className="text-xs font-bold text-slate-900">Identity</span>
                </div>
                <p className="text-xs text-slate-600">
                  {hasIdentity
                    ? 'Uses signed platform identity; app receives user/org/role context.'
                    : 'No identity forwarding configured.'}
                </p>
              </div>

              {/* Network */}
              <div className="p-3 rounded-lg border border-slate-200 bg-slate-50">
                <div className="flex items-center gap-2 mb-1">
                  <Globe className="w-4 h-4 text-emerald-600" />
                  <span className="text-xs font-bold text-slate-900">Network</span>
                </div>
                <p className="text-xs text-slate-600">
                  {egressList.length === 0
                    ? 'No external network access configured (default deny).'
                    : `Outbound egress permitted to: ${egressList.join(', ')}.`}
                </p>
              </div>

              {/* Database */}
              <div className="p-3 rounded-lg border border-slate-200 bg-slate-50">
                <div className="flex items-center gap-2 mb-1">
                  <Database className="w-4 h-4 text-sky-600" />
                  <span className="text-xs font-bold text-slate-900">Database</span>
                </div>
                <p className="text-xs text-slate-600">
                  Private SQLite database for this Capsule • max {dbLimit} MB (single-writer WAL mode).
                </p>
              </div>

              {/* Connectors (with SERVICE IDENTITY PROMINENT HIGHLIGHT) */}
              <div className={`p-3 rounded-lg border transition-all ${
                hasServiceIdentity 
                  ? 'border-amber-400 bg-amber-50/70 ring-2 ring-amber-300' 
                  : 'border-slate-200 bg-slate-50'
              }`}>
                <div className="flex items-center justify-between mb-1">
                  <div className="flex items-center gap-2">
                    <Share2 className="w-4 h-4 text-violet-600" />
                    <span className="text-xs font-bold text-slate-900">Connectors</span>
                  </div>
                  {hasServiceIdentity && (
                    <span className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-[10px] font-bold bg-amber-200 text-amber-900 uppercase">
                      <AlertTriangle className="w-3 h-3 text-amber-700" />
                      Service Identity
                    </span>
                  )}
                </div>
                {hasConnectors ? (
                  <div className="space-y-1 my-1">
                    {parsedConnectors.map((c, idx) => (
                      <div key={idx} className="flex items-center justify-between text-xs">
                        <span className="font-medium text-slate-800">
                          {c.name}{c.channel ? ` (${c.channel})` : ''}
                        </span>
                        <span className={`px-1.5 py-0.5 rounded text-[10px] font-semibold ${
                          c.acts_as === 'service' 
                            ? 'bg-amber-100 text-amber-900 border border-amber-300' 
                            : 'bg-slate-100 text-slate-600'
                        }`}>
                          {c.acts_as === 'service' ? 'Service' : 'Viewer'}
                        </span>
                      </div>
                    ))}
                  </div>
                ) : (
                  <p className="text-xs text-slate-500">No external connectors configured.</p>
                )}
                {hasServiceIdentity && (
                  <p className="mt-1 text-[11px] text-amber-800 font-semibold">
                    ⚠️ Acts as a service identity (autonomous actions without human approval).
                  </p>
                )}
              </div>

              {/* Files */}
              <div className="p-3 rounded-lg border border-slate-200 bg-slate-50">
                <div className="flex items-center gap-2 mb-1">
                  <HardDrive className="w-4 h-4 text-teal-600" />
                  <span className="text-xs font-bold text-slate-900">Files</span>
                </div>
                <p className="text-xs text-slate-600">
                  File storage enabled • max {filesLimit} MB.
                </p>
              </div>

              {/* AI */}
              <div className="p-3 rounded-lg border border-slate-200 bg-slate-50">
                <div className="flex items-center gap-2 mb-1">
                  <Cpu className="w-4 h-4 text-purple-600" />
                  <span className="text-xs font-bold text-slate-900">AI</span>
                </div>
                <p className="text-xs text-slate-600">
                  AI capability enabled • monthly budget: $5.
                </p>
              </div>
            </div>

            {/* Approval Required Banner matching wireframe */}
            <div className="mt-4 p-3 rounded-lg bg-amber-50 border border-amber-300 text-amber-900 text-xs font-medium flex items-center gap-2.5">
              <AlertTriangle className="w-5 h-5 text-amber-600 shrink-0" />
              <span>
                <strong>APPROVAL REQUIRED</strong> if this release adds or broadens a capability, adds a service identity, or uses a newly restricted connector.
              </span>
            </div>
          </div>
        </div>

        {/* Footer */}
        <div className="px-6 py-4 border-t border-slate-200 bg-slate-50 flex items-center justify-end gap-3">
          <button
            onClick={onClose}
            className="px-4 py-2 text-xs font-semibold rounded-lg border border-slate-300 bg-white hover:bg-slate-100 text-slate-700 transition-colors"
          >
            Close
          </button>
        </div>
      </div>
    </div>
  );
};

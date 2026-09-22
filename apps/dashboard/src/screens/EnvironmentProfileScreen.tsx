import React, { useState, useEffect } from 'react';
import { UserProfile, EnvironmentProfileData, ProfileDiffResult, AuditEvent } from '../types';
import { api } from '../api';
import {
  Shield,
  Layers,
  Cpu,
  Globe,
  Share2,
  Bot,
  AlertTriangle,
  CheckCircle2,
  Eye,
  Save,
  RefreshCw,
  Clock,
  Lock,
  FileCode,
  Sliders,
  XCircle,
  ChevronRight,
  Info
} from 'lucide-react';

interface EnvironmentProfileScreenProps {
  currentUser: UserProfile;
}

export const EnvironmentProfileScreen: React.FC<EnvironmentProfileScreenProps> = ({ currentUser }) => {
  const [profileData, setProfileData] = useState<EnvironmentProfileData | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [previewing, setPreviewing] = useState(false);
  const [diffResult, setDiffResult] = useState<ProfileDiffResult | null>(null);
  const [showDiffModal, setShowDiffModal] = useState(false);
  const [jsonMode, setJsonMode] = useState(false);
  const [jsonText, setJsonText] = useState('');
  const [jsonError, setJsonError] = useState<string | null>(null);
  const [activeTab, setActiveTab] = useState<'runtimes' | 'capabilities' | 'egress' | 'quotas' | 'sharing' | 'compliance'>('runtimes');
  const [auditEvents, setAuditEvents] = useState<AuditEvent[]>([]);
  const [notification, setNotification] = useState<{ type: 'success' | 'error'; message: string } | null>(null);

  const isAdmin = currentUser.platform_role === 'owner' || currentUser.platform_role === 'editor';

  useEffect(() => {
    loadProfile();
  }, [currentUser.organization_id]);

  const loadProfile = async () => {
    try {
      setLoading(true);
      const [data, events] = await Promise.all([
        api.getEnvironmentProfile(currentUser.organization_id),
        api.listAuditEvents().catch(() => []),
      ]);
      setProfileData(data);
      setJsonText(JSON.stringify(data.raw_profile && Object.keys(data.raw_profile).length > 0 ? data.raw_profile : data.profile, null, 2));
      const profileAudit = events.filter((e) =>
        e.action.includes('profile') || e.action.includes('compliance')
      );
      setAuditEvents(profileAudit);
    } catch (err: any) {
      setNotification({ type: 'error', message: `Failed to load environment profile: ${err.message}` });
    } finally {
      setLoading(false);
    }
  };

  const handleJsonChange = (val: string) => {
    setJsonText(val);
    try {
      JSON.parse(val);
      setJsonError(null);
    } catch (e: any) {
      setJsonError(e.message);
    }
  };

  const getCurrentEditedProfile = (): Record<string, any> => {
    if (jsonMode) {
      return JSON.parse(jsonText);
    }
    return profileData?.profile || {};
  };

  const handlePreviewDiff = async () => {
    try {
      setPreviewing(true);
      setNotification(null);
      const payload = getCurrentEditedProfile();
      const diff = await api.previewProfileDiff(currentUser.organization_id, payload);
      setDiffResult(diff);
      setShowDiffModal(true);
    } catch (err: any) {
      setNotification({ type: 'error', message: `Diff preview failed: ${err.message}` });
    } finally {
      setPreviewing(false);
    }
  };

  const handleSaveProfile = async () => {
    if (!isAdmin) return;
    try {
      setSaving(true);
      setNotification(null);
      const payload = getCurrentEditedProfile();
      const res = await api.updateEnvironmentProfile(currentUser.organization_id, payload);
      setShowDiffModal(false);
      setNotification({
        type: 'success',
        message: `Profile updated successfully. Re-evaluated ${res.re_evaluation?.total_apps_evaluated || 0} apps (${res.re_evaluation?.non_compliant_apps_count || 0} non-compliant).`,
      });
      await loadProfile();
    } catch (err: any) {
      setNotification({ type: 'error', message: `Failed to update profile: ${err.message}` });
    } finally {
      setSaving(false);
    }
  };

  if (loading) {
    return (
      <div className="max-w-5xl mx-auto p-8 text-center text-slate-400 font-mono text-sm">
        <RefreshCw className="w-6 h-6 animate-spin mx-auto mb-2 text-indigo-600" />
        Loading Organization Environment Profile & Policy Ceiling...
      </div>
    );
  }

  const profile = profileData?.profile || {};

  return (
    <div className="max-w-5xl mx-auto space-y-6">
      {/* Header */}
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-4 bg-white p-6 rounded-2xl border border-slate-200 shadow-sm">
        <div>
          <div className="flex items-center gap-2 mb-1">
            <Shield className="w-6 h-6 text-indigo-600" />
            <h1 className="text-xl font-bold text-slate-900">Environment Profile & Policy Ceiling</h1>
            <span className="px-2 py-0.5 rounded-full text-xs font-mono bg-indigo-50 text-indigo-700 border border-indigo-200">
              {profileData?.version || 'capsule/v1alpha1'}
            </span>
          </div>
          <p className="text-xs text-slate-500">
            Defines the maximum permissible boundaries (FR-027, FR-028, FR-032). Manifests may narrow policy but never widen it.
          </p>
        </div>

        <div className="flex items-center gap-2">
          <button
            onClick={() => setJsonMode(!jsonMode)}
            className={`px-3 py-1.5 rounded-lg text-xs font-medium border flex items-center gap-1.5 transition-colors ${
              jsonMode
                ? 'bg-indigo-50 text-indigo-700 border-indigo-300'
                : 'bg-white text-slate-700 border-slate-200 hover:bg-slate-50'
            }`}
          >
            <FileCode className="w-3.5 h-3.5" />
            {jsonMode ? 'Visual Mode' : 'Raw JSON Mode'}
          </button>

          <button
            onClick={handlePreviewDiff}
            disabled={previewing || (jsonMode && Boolean(jsonError))}
            className="px-3 py-1.5 rounded-lg text-xs font-medium bg-white text-slate-700 border border-slate-200 hover:bg-slate-50 flex items-center gap-1.5 disabled:opacity-50"
          >
            <Eye className="w-3.5 h-3.5 text-slate-500" />
            Preview Diff
          </button>

          {isAdmin && (
            <button
              onClick={handleSaveProfile}
              disabled={saving || (jsonMode && Boolean(jsonError))}
              className="px-4 py-1.5 rounded-lg text-xs font-semibold bg-indigo-600 hover:bg-indigo-700 text-white flex items-center gap-1.5 shadow-sm disabled:opacity-50"
            >
              <Save className="w-3.5 h-3.5" />
              {saving ? 'Applying...' : 'Apply Ceiling'}
            </button>
          )}
        </div>
      </div>

      {/* Notifications */}
      {notification && (
        <div
          className={`p-4 rounded-xl border text-xs flex items-center gap-3 ${
            notification.type === 'success'
              ? 'bg-emerald-50 text-emerald-800 border-emerald-200'
              : 'bg-rose-50 text-rose-800 border-rose-200'
          }`}
        >
          {notification.type === 'success' ? (
            <CheckCircle2 className="w-4 h-4 text-emerald-600 flex-shrink-0" />
          ) : (
            <AlertTriangle className="w-4 h-4 text-rose-600 flex-shrink-0" />
          )}
          <span>{notification.message}</span>
        </div>
      )}

      {/* Main Content Area */}
      {jsonMode ? (
        <div className="bg-white p-6 rounded-2xl border border-slate-200 space-y-3">
          <div className="flex items-center justify-between">
            <span className="text-xs font-bold text-slate-700 flex items-center gap-1.5">
              <FileCode className="w-4 h-4 text-slate-400" />
              Environment Profile Specification (JSON)
            </span>
            {jsonError && (
              <span className="text-xs text-rose-600 font-mono flex items-center gap-1">
                <XCircle className="w-3.5 h-3.5" /> JSON Syntax Error: {jsonError}
              </span>
            )}
          </div>
          <textarea
            value={jsonText}
            onChange={(e) => handleJsonChange(e.target.value)}
            rows={22}
            className="w-full font-mono text-xs p-4 bg-slate-900 text-slate-100 rounded-xl border border-slate-800 focus:outline-none focus:ring-2 focus:ring-indigo-500"
          />
        </div>
      ) : (
        <div className="bg-white rounded-2xl border border-slate-200 overflow-hidden shadow-sm">
          {/* Navigation Tabs */}
          <div className="flex border-b border-slate-200 bg-slate-50/50 px-4">
            {[
              { id: 'runtimes', label: 'Runtimes & Shapes', icon: Layers },
              { id: 'capabilities', label: 'Capabilities & Connectors', icon: Sliders },
              { id: 'egress', label: 'Egress Ceiling', icon: Globe },
              { id: 'quotas', label: 'Resource Quotas', icon: Cpu },
              { id: 'sharing', label: 'Sharing & Approval', icon: Share2 },
              { id: 'compliance', label: 'Compliance & Audit', icon: Clock },
            ].map((tab) => {
              const Icon = tab.icon;
              const isActive = activeTab === tab.id;
              return (
                <button
                  key={tab.id}
                  onClick={() => setActiveTab(tab.id as any)}
                  className={`px-4 py-3 text-xs font-semibold flex items-center gap-2 border-b-2 transition-colors ${
                    isActive
                      ? 'border-indigo-600 text-indigo-600 bg-white'
                      : 'border-transparent text-slate-500 hover:text-slate-700 hover:bg-slate-100/50'
                  }`}
                >
                  <Icon className="w-3.5 h-3.5" />
                  {tab.label}
                </button>
              );
            })}
          </div>

          <div className="p-6 space-y-6 text-xs">
            {/* Tab 1: Runtimes & Shapes */}
            {activeTab === 'runtimes' && (
              <div className="space-y-6">
                <div>
                  <h3 className="font-bold text-slate-900 text-sm mb-1">Allowed Runtimes</h3>
                  <p className="text-slate-500 mb-3">Only runtimes listed here can be declared by apps published in this organization.</p>
                  <div className="flex flex-wrap gap-2">
                    {(profile.allowed_runtimes || []).map((rt: string) => (
                      <span key={rt} className="px-2.5 py-1 bg-indigo-50 border border-indigo-200 text-indigo-800 rounded-lg font-mono font-medium">
                        {rt}
                      </span>
                    ))}
                  </div>
                </div>

                <div className="border-t border-slate-100 pt-6">
                  <h3 className="font-bold text-slate-900 text-sm mb-1">Allowed Shapes</h3>
                  <p className="text-slate-500 mb-3">Execution topology restrictions for capsules.</p>
                  <div className="flex flex-wrap gap-2">
                    {(profile.allowed_shapes || []).map((sh: string) => (
                      <span key={sh} className="px-2.5 py-1 bg-emerald-50 border border-emerald-200 text-emerald-800 rounded-lg font-mono font-medium">
                        {sh}
                      </span>
                    ))}
                  </div>
                </div>
              </div>
            )}

            {/* Tab 2: Capabilities & Connectors */}
            {activeTab === 'capabilities' && (
              <div className="space-y-6">
                <div>
                  <h3 className="font-bold text-slate-900 text-sm mb-1">Permitted Capabilities</h3>
                  <p className="text-slate-500 mb-3">Core platform capability ceiling. Unlisted capabilities will be rejected at publish time.</p>
                  <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
                    {['db', 'blobs', 'identity', 'connectors', 'ai'].map((cap) => {
                      const isAllowed = (profile.allowed_capabilities || []).includes(cap);
                      return (
                        <div key={cap} className={`p-3 rounded-xl border flex items-center justify-between ${isAllowed ? 'bg-slate-50 border-slate-200' : 'bg-slate-100/50 border-slate-200 opacity-60'}`}>
                          <span className="font-mono font-semibold text-slate-800">{cap}</span>
                          <span className={`px-2 py-0.5 rounded text-[10px] font-bold ${isAllowed ? 'bg-emerald-100 text-emerald-800' : 'bg-slate-200 text-slate-600'}`}>
                            {isAllowed ? 'Allowed' : 'Blocked'}
                          </span>
                        </div>
                      );
                    })}
                  </div>
                </div>

                <div className="border-t border-slate-100 pt-6">
                  <h3 className="font-bold text-slate-900 text-sm mb-1">Connector Policies</h3>
                  <p className="text-slate-500 mb-3">Approved connectors and allowed identity scopes.</p>
                  <div className="space-y-3">
                    <div className="p-3 bg-slate-50 rounded-xl border border-slate-200 flex items-center justify-between">
                      <div>
                        <span className="font-bold text-slate-800 block">Service Identity Mode (`acts_as: service`)</span>
                        <span className="text-slate-500">Allows apps to use organizational credentials rather than user viewer credentials.</span>
                      </div>
                      <span className={`px-2.5 py-1 rounded-full text-xs font-bold ${profile.connectors?.allow_service_identity ? 'bg-amber-100 text-amber-800 border border-amber-200' : 'bg-rose-100 text-rose-800 border border-rose-200'}`}>
                        {profile.connectors?.allow_service_identity ? 'Allowed with Approval' : 'Strictly Forbidden'}
                      </span>
                    </div>

                    <div className="p-3 bg-slate-50 rounded-xl border border-slate-200 flex items-center justify-between">
                      <div>
                        <span className="font-bold text-slate-800 block">Google Sheets Connector (<code className="font-mono">sheets.read</code>)</span>
                        <span className="text-slate-500">Reads Google Spreadsheets on behalf of the signed-in viewer using per-user OAuth credentials.</span>
                      </div>
                      <span className={`px-2.5 py-1 rounded-full text-xs font-bold ${(profile.connectors?.disabled_connectors || []).includes('sheets.read') ? 'bg-rose-100 text-rose-800 border border-rose-200' : 'bg-emerald-100 text-emerald-800 border border-emerald-200'}`}>
                        {(profile.connectors?.disabled_connectors || []).includes('sheets.read') ? 'Disabled' : 'Enabled (Viewer Only)'}
                      </span>
                    </div>

                    <div className="p-3 bg-slate-50 rounded-xl border border-slate-200">
                      <span className="font-bold text-slate-800 block mb-1">Disabled Connectors (Organization-wide Kill Switch)</span>
                      <div className="flex flex-wrap gap-2 pt-1">
                        {(profile.connectors?.disabled_connectors || []).length > 0 ? (
                          (profile.connectors.disabled_connectors || []).map((dc: string) => (
                            <span key={dc} className="px-2 py-0.5 bg-rose-50 border border-rose-200 text-rose-700 rounded font-mono text-[11px]">
                              {dc} (blocked)
                            </span>
                          ))
                        ) : (
                          <span className="text-slate-400 italic">None. All registered connectors available.</span>
                        )}
                      </div>
                    </div>
                  </div>
                </div>
              </div>
            )}

            {/* Tab 3: Egress Ceiling */}
            {activeTab === 'egress' && (
              <div className="space-y-6">
                <div>
                  <h3 className="font-bold text-slate-900 text-sm mb-1">Egress Allowlist (Ceiling)</h3>
                  <p className="text-slate-500 mb-3">External hosts capsules are permitted to reach via the egress proxy.</p>
                  <div className="flex flex-wrap gap-2">
                    {(profile.egress?.allowlist || []).map((host: string) => (
                      <span key={host} className="px-2.5 py-1 bg-emerald-50 border border-emerald-200 text-emerald-800 rounded-lg font-mono font-medium">
                        {host}
                      </span>
                    ))}
                  </div>
                </div>

                <div className="border-t border-slate-100 pt-6">
                  <h3 className="font-bold text-slate-900 text-sm mb-1">Egress Denylist (SSRF & Metadata Protection)</h3>
                  <p className="text-slate-500 mb-3">Protected subnets and metadata addresses that can NEVER be declared in egress.</p>
                  <div className="flex flex-wrap gap-2">
                    {(profile.egress?.denylist || []).map((host: string) => (
                      <span key={host} className="px-2.5 py-1 bg-rose-50 border border-rose-200 text-rose-800 rounded-lg font-mono font-medium">
                        {host}
                      </span>
                    ))}
                  </div>
                </div>
              </div>
            )}

            {/* Tab 4: Resource Quotas */}
            {activeTab === 'quotas' && (
              <div className="space-y-6">
                <h3 className="font-bold text-slate-900 text-sm mb-1">Hardware & Resource Ceilings</h3>
                <p className="text-slate-500 mb-3">Maximum thresholds enforced during validation. Manifests requesting more are rejected with POLICY_VIOLATION.</p>

                <div className="grid grid-cols-2 md:grid-cols-3 gap-4">
                  <div className="p-4 bg-slate-50 border border-slate-200 rounded-xl space-y-1">
                    <span className="text-slate-500 text-[11px] block">Max Memory Ceiling</span>
                    <span className="text-base font-bold text-slate-900 font-mono">{profile.quotas?.max_memory_mb || 512} MB</span>
                  </div>

                  <div className="p-4 bg-slate-50 border border-slate-200 rounded-xl space-y-1">
                    <span className="text-slate-500 text-[11px] block">Max CPU Shape</span>
                    <span className="text-base font-bold text-slate-900 font-mono">{profile.quotas?.max_cpu || 'small'}</span>
                  </div>

                  <div className="p-4 bg-slate-50 border border-slate-200 rounded-xl space-y-1">
                    <span className="text-slate-500 text-[11px] block">Max Request Timeout</span>
                    <span className="text-base font-bold text-slate-900 font-mono">{profile.quotas?.max_request_timeout_s || 60}s</span>
                  </div>

                  <div className="p-4 bg-slate-50 border border-slate-200 rounded-xl space-y-1">
                    <span className="text-slate-500 text-[11px] block">Max SQLite Database Size</span>
                    <span className="text-base font-bold text-slate-900 font-mono">{profile.quotas?.max_db_mb || 100} MB</span>
                  </div>

                  <div className="p-4 bg-slate-50 border border-slate-200 rounded-xl space-y-1">
                    <span className="text-slate-500 text-[11px] block">Max Blob Storage Volume</span>
                    <span className="text-base font-bold text-slate-900 font-mono">{profile.quotas?.max_blob_mb || 500} MB</span>
                  </div>

                  <div className="p-4 bg-slate-50 border border-slate-200 rounded-xl space-y-1">
                    <span className="text-slate-500 text-[11px] block">Capsules Per User Quota</span>
                    <span className="text-base font-bold text-slate-900 font-mono">{profile.quotas?.apps_per_user || 200}</span>
                  </div>
                </div>
              </div>
            )}

            {/* Tab 5: Sharing & Approval */}
            {activeTab === 'sharing' && (
              <div className="space-y-6">
                <div>
                  <h3 className="font-bold text-slate-900 text-sm mb-1">Sharing Governance</h3>
                  <div className="grid grid-cols-2 gap-4 mt-3">
                    <div className="p-4 bg-slate-50 rounded-xl border border-slate-200">
                      <span className="font-bold text-slate-800 block mb-1">Default Sharing Scope</span>
                      <span className="font-mono text-indigo-700 bg-indigo-50 px-2 py-0.5 rounded border border-indigo-200">
                        {profile.sharing?.default_scope || 'org'}
                      </span>
                    </div>

                    <div className="p-4 bg-slate-50 rounded-xl border border-slate-200">
                      <span className="font-bold text-slate-800 block mb-1">External Users Allowed</span>
                      <span className={`px-2 py-0.5 rounded text-[11px] font-bold ${profile.sharing?.allow_external_users ? 'bg-amber-100 text-amber-800' : 'bg-slate-200 text-slate-700'}`}>
                        {profile.sharing?.allow_external_users ? 'Yes (Restricted)' : 'No (Strictly Off)'}
                      </span>
                    </div>
                  </div>
                </div>

                <div className="border-t border-slate-100 pt-6">
                  <h3 className="font-bold text-slate-900 text-sm mb-1">Conditional Approval Thresholds (FR-032)</h3>
                  <p className="text-slate-500 mb-3">Applications meeting these criteria bypass manual review; exceeding them requires owner approval.</p>

                  <div className="space-y-2">
                    <div className="p-3 bg-slate-50 rounded-xl border border-slate-200 flex justify-between items-center">
                      <div>
                        <span className="font-semibold text-slate-800 block">Audience Size Threshold</span>
                        <span className="text-slate-500">Apps shared with more users require administrator approval.</span>
                      </div>
                      <span className="font-mono font-bold text-slate-900">{profile.approvals?.audience_threshold || 50} users</span>
                    </div>

                    <div className="p-3 bg-slate-50 rounded-xl border border-slate-200 flex justify-between items-center">
                      <div>
                        <span className="font-semibold text-slate-800 block">Personal Apps Fast-Path</span>
                        <span className="text-slate-500">Personal apps (shared with self only, no sensitive capabilities) deploy instantly.</span>
                      </div>
                      <span className="px-2 py-0.5 rounded bg-emerald-100 text-emerald-800 font-bold">Enabled</span>
                    </div>
                  </div>
                </div>
              </div>
            )}

            {/* Tab 6: Compliance & Audit */}
            {activeTab === 'compliance' && (
              <div className="space-y-6">
                <div>
                  <h3 className="font-bold text-slate-900 text-sm mb-1">Profile Update Compliance & Grace Period</h3>
                  <p className="text-slate-500 mb-3">When policies are tightened, existing apps are evaluated against the new ceiling.</p>

                  <div className="grid grid-cols-2 gap-4">
                    <div className="p-4 bg-slate-50 rounded-xl border border-slate-200">
                      <span className="text-slate-500 block mb-1">Grace Period for Existing Apps</span>
                      <span className="text-base font-bold text-slate-900 font-mono">{profile.compliance?.grace_period_hours || 72} hours</span>
                    </div>

                    <div className="p-4 bg-slate-50 rounded-xl border border-slate-200">
                      <span className="text-slate-500 block mb-1">Enforcement Action After Grace Period</span>
                      <span className="text-base font-bold text-rose-700 font-mono uppercase">{profile.compliance?.enforcement_action || 'restrict'}</span>
                    </div>
                  </div>
                </div>

                <div className="border-t border-slate-100 pt-6">
                  <h3 className="font-bold text-slate-900 text-sm mb-2 flex items-center gap-2">
                    <Clock className="w-4 h-4 text-slate-500" />
                    Recent Profile Audit Events
                  </h3>
                  {auditEvents.length === 0 ? (
                    <p className="text-slate-400 italic">No recent profile update events recorded in the vault.</p>
                  ) : (
                    <div className="divide-y divide-slate-100 font-mono text-[11px]">
                      {auditEvents.map((evt) => (
                        <div key={evt.id} className="py-2.5 flex items-center justify-between">
                          <div>
                            <span className="font-semibold text-slate-800">[{evt.action}]</span>{' '}
                            <span className="text-slate-500">outcome: {evt.outcome}</span>
                          </div>
                          <span className="text-slate-400">{new Date(evt.occurred_at).toLocaleString()}</span>
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              </div>
            )}
          </div>
        </div>
      )}

      {/* Diff & Impact Modal */}
      {showDiffModal && diffResult && (
        <div className="fixed inset-0 bg-slate-900/40 backdrop-blur-sm flex items-center justify-center p-4 z-50">
          <div className="bg-white rounded-2xl border border-slate-200 shadow-xl max-w-2xl w-full max-h-[85vh] flex flex-col">
            <div className="p-6 border-b border-slate-100 flex items-center justify-between">
              <div>
                <h2 className="text-base font-bold text-slate-900">Policy Diff & Impact Analysis</h2>
                <p className="text-xs text-slate-500">Review planned changes and affected capsules before applying.</p>
              </div>
              <button
                onClick={() => setShowDiffModal(false)}
                className="p-1.5 rounded-lg text-slate-400 hover:text-slate-600 hover:bg-slate-100"
              >
                <XCircle className="w-5 h-5" />
              </button>
            </div>

            <div className="p-6 overflow-y-auto space-y-6 text-xs flex-1">
              {/* Diff summary */}
              <div>
                <span className="font-bold text-slate-800 block mb-2">Calculated Modifications</span>
                {!diffResult.diff.has_changes ? (
                  <div className="p-3 bg-slate-50 rounded-xl text-slate-500 italic">No structural changes detected.</div>
                ) : (
                  <pre className="p-4 bg-slate-900 text-slate-100 rounded-xl font-mono text-[11px] overflow-x-auto">
                    {JSON.stringify(diffResult.diff, null, 2)}
                  </pre>
                )}
              </div>

              {/* Impact analysis */}
              <div>
                <div className="flex items-center justify-between mb-2">
                  <span className="font-bold text-slate-800">Impacted Capsules in Organization</span>
                  <span className={`px-2 py-0.5 rounded-full font-bold ${diffResult.impacted_apps_count > 0 ? 'bg-amber-100 text-amber-800' : 'bg-emerald-100 text-emerald-800'}`}>
                    {diffResult.impacted_apps_count} of {diffResult.total_apps_evaluated} capsules affected
                  </span>
                </div>

                {diffResult.impacted_apps_count === 0 ? (
                  <div className="p-3 bg-emerald-50 border border-emerald-200 rounded-xl text-emerald-800 flex items-center gap-2">
                    <CheckCircle2 className="w-4 h-4 text-emerald-600" />
                    All existing capsules remain 100% compliant with the proposed policy ceiling.
                  </div>
                ) : (
                  <div className="space-y-3">
                    {diffResult.impacted_apps.map((app) => (
                      <div key={app.app_id} className="p-3 bg-amber-50 border border-amber-200 rounded-xl space-y-2">
                        <div className="flex items-center justify-between">
                          <span className="font-bold text-amber-900">{app.name} ({app.app_key})</span>
                          <span className="px-2 py-0.5 bg-amber-200 text-amber-900 rounded text-[10px] font-bold">
                            {app.violations_count} violation(s)
                          </span>
                        </div>
                        <div className="space-y-1">
                          {app.violations.map((v, i) => (
                            <div key={i} className="text-[11px] text-amber-800 flex items-start gap-1.5 font-mono">
                              <ChevronRight className="w-3.5 h-3.5 flex-shrink-0 mt-0.5 text-amber-600" />
                              <div>
                                <span className="font-semibold">[{v.error}]</span> {v.message}
                                {v.hint && <div className="text-amber-600 text-[10px]">Hint: {v.hint}</div>}
                              </div>
                            </div>
                          ))}
                        </div>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            </div>

            <div className="p-4 border-t border-slate-100 bg-slate-50 rounded-b-2xl flex items-center justify-between">
              <span className="text-[11px] text-slate-500">
                Applying updates triggers re-evaluation and starts a grace period.
              </span>
              <div className="flex items-center gap-2">
                <button
                  onClick={() => setShowDiffModal(false)}
                  className="px-3 py-1.5 rounded-lg font-medium text-slate-600 hover:bg-slate-200"
                >
                  Cancel
                </button>
                {isAdmin && (
                  <button
                    onClick={handleSaveProfile}
                    disabled={saving}
                    className="px-4 py-1.5 rounded-lg font-semibold bg-indigo-600 hover:bg-indigo-700 text-white shadow-sm"
                  >
                    {saving ? 'Applying...' : 'Confirm & Apply'}
                  </button>
                )}
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};

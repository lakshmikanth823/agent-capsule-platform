import React, { useState, useEffect } from 'react';
import { UserProfile } from '../types';
import { api } from '../api';
import { KeyRound, Shield, Users, RefreshCw, CheckCircle2, AlertCircle, Copy, Trash2, Plus, ExternalLink } from 'lucide-react';

interface Props {
  currentUser: UserProfile;
}

export const SSODirectorySyncScreen: React.FC<Props> = ({ currentUser }) => {
  const [activeTab, setActiveTab] = useState<'sso' | 'domains' | 'scim' | 'mappings'>('sso');
  const [loading, setLoading] = useState(false);
  const [message, setMessage] = useState<{ type: 'success' | 'error'; text: string } | null>(null);

  // SSO IdP State
  const [providerType, setProviderType] = useState<'oidc' | 'saml'>('oidc');
  const [isActive, setIsActive] = useState(true);
  const [enforceSso, setEnforceSso] = useState(false);
  const [sessionLifetime, setSessionLifetime] = useState(28800);
  const [oidcIssuer, setOidcIssuer] = useState('');
  const [oidcClientId, setOidcClientId] = useState('');
  const [oidcClientSecret, setOidcClientSecret] = useState('');
  const [samlEntityId, setSamlEntityId] = useState('');
  const [samlSsoUrl, setSamlSsoUrl] = useState('');
  const [samlCert, setSamlCert] = useState('');

  // Domains State
  const [domains, setDomains] = useState<any[]>([]);
  const [newDomain, setNewDomain] = useState('');

  // SCIM State
  const [scimTokenInfo, setScimTokenInfo] = useState<any>(null);
  const [rotatedTokenModal, setRotatedTokenModal] = useState<string | null>(null);

  // Group Mappings State
  const [mappings, setMappings] = useState<any[]>([]);
  const [apps, setApps] = useState<any[]>([]);
  const [newMappingGroup, setNewMappingGroup] = useState('');
  const [newMappingAppId, setNewMappingAppId] = useState('');
  const [newMappingRole, setNewMappingRole] = useState('editor');

  const orgId = currentUser.organization_id;

  useEffect(() => {
    loadAll();
  }, [orgId]);

  const loadAll = async () => {
    setLoading(true);
    try {
      // 1. Load IdP
      const idp = await api.getIdp(orgId);
      if (idp) {
        setProviderType(idp.provider_type);
        setIsActive(idp.is_active);
        setEnforceSso(idp.enforce_sso);
        setSessionLifetime(idp.session_lifetime_seconds || 28800);
        setOidcIssuer(idp.oidc_issuer_url || '');
        setOidcClientId(idp.oidc_client_id || '');
        setSamlEntityId(idp.saml_entity_id || '');
        setSamlSsoUrl(idp.saml_sso_url || '');
      }

      // 2. Load Domains
      const doms = await api.listDomains(orgId);
      setDomains(doms);

      // 3. Load SCIM token
      const scim = await api.getScimTokenInfo(orgId);
      setScimTokenInfo(scim);

      // 4. Load Group Mappings & Apps
      const maps = await api.listGroupRoleMappings(orgId);
      setMappings(maps);

      const appList = await api.listApps();
      setApps(appList);
      if (appList.length > 0) {
        setNewMappingAppId(appList[0].id);
      }
    } catch (err: any) {
      console.error('Failed to load SSO data', err);
    } finally {
      setLoading(false);
    }
  };

  const handleSaveIdp = async (e: React.FormEvent) => {
    e.preventDefault();
    setMessage(null);
    try {
      await api.configureIdp(orgId, {
        provider_type: providerType,
        is_active: isActive,
        enforce_sso: enforceSso,
        session_lifetime_seconds: Number(sessionLifetime),
        oidc_issuer_url: providerType === 'oidc' ? oidcIssuer : undefined,
        oidc_client_id: providerType === 'oidc' ? oidcClientId : undefined,
        oidc_client_secret: providerType === 'oidc' && oidcClientSecret ? oidcClientSecret : undefined,
        saml_entity_id: providerType === 'saml' ? samlEntityId : undefined,
        saml_sso_url: providerType === 'saml' ? samlSsoUrl : undefined,
        saml_x509_cert: providerType === 'saml' && samlCert ? samlCert : undefined,
      });
      setMessage({ type: 'success', text: 'SSO Identity Provider configuration saved.' });
    } catch (err: any) {
      setMessage({ type: 'error', text: err.message });
    }
  };

  const handleClaimDomain = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!newDomain) return;
    try {
      await api.claimDomain(orgId, newDomain);
      setNewDomain('');
      const doms = await api.listDomains(orgId);
      setDomains(doms);
      setMessage({ type: 'success', text: `Domain claim created for ${newDomain}. Add the TXT challenge record to your DNS.` });
    } catch (err: any) {
      setMessage({ type: 'error', text: err.message });
    }
  };

  const handleVerifyDomain = async (domain: string) => {
    try {
      await api.verifyDomain(orgId, domain);
      const doms = await api.listDomains(orgId);
      setDomains(doms);
      setMessage({ type: 'success', text: `Domain '${domain}' verified successfully! You can now enforce SSO for this domain.` });
    } catch (err: any) {
      setMessage({ type: 'error', text: err.message });
    }
  };

  const handleDeleteDomain = async (domain: string) => {
    if (!confirm(`Delete domain claim for '${domain}'?`)) return;
    try {
      await api.deleteDomain(orgId, domain);
      const doms = await api.listDomains(orgId);
      setDomains(doms);
    } catch (err: any) {
      setMessage({ type: 'error', text: err.message });
    }
  };

  const handleRotateScim = async () => {
    if (!confirm('Rotate SCIM bearer token? Any existing sync jobs using the previous token will immediately fail until updated.')) return;
    try {
      const res = await api.rotateScimToken(orgId);
      setRotatedTokenModal(res.token);
      const scim = await api.getScimTokenInfo(orgId);
      setScimTokenInfo(scim);
    } catch (err: any) {
      setMessage({ type: 'error', text: err.message });
    }
  };

  const handleCreateMapping = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!newMappingGroup || !newMappingAppId) return;
    try {
      await api.createGroupRoleMapping(orgId, {
        group_id: newMappingGroup,
        app_id: newMappingAppId,
        app_role: newMappingRole,
      });
      const maps = await api.listGroupRoleMappings(orgId);
      setMappings(maps);
      setMessage({ type: 'success', text: 'Group role mapping established and propagated.' });
    } catch (err: any) {
      setMessage({ type: 'error', text: err.message });
    }
  };

  const handleDeleteMapping = async (mappingId: string) => {
    try {
      await api.deleteGroupRoleMapping(orgId, mappingId);
      const maps = await api.listGroupRoleMappings(orgId);
      setMappings(maps);
    } catch (err: any) {
      setMessage({ type: 'error', text: err.message });
    }
  };

  const verifiedDomainsCount = domains.filter((d) => d.status === 'verified').length;

  return (
    <div className="max-w-5xl mx-auto space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between pb-4 border-b border-slate-200">
        <div>
          <h1 className="text-xl font-bold text-slate-900 flex items-center gap-2">
            <KeyRound className="w-5 h-5 text-indigo-600" />
            Company SSO & Directory Sync (SCIM)
          </h1>
          <p className="text-xs text-slate-500 mt-1">
            Configure OpenID Connect / SAML 2.0 authentication, verify corporate domains, and automate user lifecycle via SCIM 2.0.
          </p>
        </div>
      </div>

      {message && (
        <div
          className={`p-3.5 rounded-lg text-xs flex items-center gap-2 ${
            message.type === 'success' ? 'bg-emerald-50 text-emerald-800 border border-emerald-200' : 'bg-rose-50 text-rose-800 border border-rose-200'
          }`}
        >
          {message.type === 'success' ? <CheckCircle2 className="w-4 h-4 text-emerald-600 shrink-0" /> : <AlertCircle className="w-4 h-4 text-rose-600 shrink-0" />}
          <span>{message.text}</span>
        </div>
      )}

      {/* Tabs */}
      <div className="flex border-b border-slate-200 gap-6 text-xs font-semibold">
        <button
          onClick={() => setActiveTab('sso')}
          className={`pb-3 border-b-2 flex items-center gap-1.5 ${
            activeTab === 'sso' ? 'border-indigo-600 text-indigo-600' : 'border-transparent text-slate-500 hover:text-slate-800'
          }`}
        >
          <Shield className="w-4 h-4" /> Single Sign-On (IdP)
        </button>
        <button
          onClick={() => setActiveTab('domains')}
          className={`pb-3 border-b-2 flex items-center gap-1.5 ${
            activeTab === 'domains' ? 'border-indigo-600 text-indigo-600' : 'border-transparent text-slate-500 hover:text-slate-800'
          }`}
        >
          <KeyRound className="w-4 h-4" /> Domain Verification ({verifiedDomainsCount})
        </button>
        <button
          onClick={() => setActiveTab('scim')}
          className={`pb-3 border-b-2 flex items-center gap-1.5 ${
            activeTab === 'scim' ? 'border-indigo-600 text-indigo-600' : 'border-transparent text-slate-500 hover:text-slate-800'
          }`}
        >
          <RefreshCw className="w-4 h-4" /> SCIM 2.0 Directory Sync
        </button>
        <button
          onClick={() => setActiveTab('mappings')}
          className={`pb-3 border-b-2 flex items-center gap-1.5 ${
            activeTab === 'mappings' ? 'border-indigo-600 text-indigo-600' : 'border-transparent text-slate-500 hover:text-slate-800'
          }`}
        >
          <Users className="w-4 h-4" /> Group-to-Role Mappings
        </button>
      </div>

      {/* TAB 1: SSO Config */}
      {activeTab === 'sso' && (
        <form onSubmit={handleSaveIdp} className="bg-white border border-slate-200 rounded-xl p-6 space-y-6 shadow-sm">
          <div className="grid grid-cols-2 gap-4">
            <div>
              <label className="block text-xs font-bold text-slate-700 mb-1">Identity Provider Protocol</label>
              <select
                value={providerType}
                onChange={(e) => setProviderType(e.target.value as any)}
                className="w-full text-xs border border-slate-300 rounded-lg p-2.5 bg-slate-50 focus:bg-white"
              >
                <option value="oidc">OpenID Connect (OIDC with Discovery)</option>
                <option value="saml">SAML 2.0</option>
              </select>
            </div>
            <div>
              <label className="block text-xs font-bold text-slate-700 mb-1">Session Lifetime (Seconds)</label>
              <input
                type="number"
                value={sessionLifetime}
                onChange={(e) => setSessionLifetime(Number(e.target.value))}
                className="w-full text-xs border border-slate-300 rounded-lg p-2.5"
                min={300}
                max={604800}
              />
              <span className="text-[10px] text-slate-400">8 hours = 28,800s. Maximum 7 days.</span>
            </div>
          </div>

          <div className="flex items-center gap-3 p-3 bg-slate-50 border border-slate-200 rounded-lg">
            <input
              type="checkbox"
              id="enforceSso"
              checked={enforceSso}
              disabled={verifiedDomainsCount === 0}
              onChange={(e) => setEnforceSso(e.target.checked)}
              className="rounded text-indigo-600 focus:ring-indigo-500"
            />
            <label htmlFor="enforceSso" className="text-xs text-slate-700 cursor-pointer">
              <strong className="block text-slate-900">Enforce SSO-Only for Verified Domains</strong>
              Block local dev credentials and passwords for all users with verified corporate email domains.
              {verifiedDomainsCount === 0 && (
                <span className="text-rose-600 block text-[11px] font-semibold mt-0.5">
                  Requires at least one verified email domain (verify under the "Domain Verification" tab).
                </span>
              )}
            </label>
          </div>

          {providerType === 'oidc' ? (
            <div className="space-y-4 pt-2 border-t border-slate-100">
              <h3 className="text-xs font-bold text-slate-900 uppercase tracking-wider">OIDC Settings</h3>
              <div>
                <label className="block text-xs font-semibold text-slate-700 mb-1">OIDC Issuer / Discovery URL</label>
                <input
                  type="url"
                  placeholder="https://auth.company.com/realms/acme"
                  value={oidcIssuer}
                  onChange={(e) => setOidcIssuer(e.target.value)}
                  className="w-full text-xs border border-slate-300 rounded-lg p-2.5"
                  required={providerType === 'oidc'}
                />
                <span className="text-[10px] text-slate-400">Standard discovery document at /.well-known/openid-configuration will be fetched.</span>
              </div>
              <div className="grid grid-cols-2 gap-4">
                <div>
                  <label className="block text-xs font-semibold text-slate-700 mb-1">Client ID</label>
                  <input
                    type="text"
                    value={oidcClientId}
                    onChange={(e) => setOidcClientId(e.target.value)}
                    className="w-full text-xs border border-slate-300 rounded-lg p-2.5"
                    required={providerType === 'oidc'}
                  />
                </div>
                <div>
                  <label className="block text-xs font-semibold text-slate-700 mb-1">Client Secret (Encrypted at rest)</label>
                  <input
                    type="password"
                    placeholder="Leave blank to keep existing secret"
                    value={oidcClientSecret}
                    onChange={(e) => setOidcClientSecret(e.target.value)}
                    className="w-full text-xs border border-slate-300 rounded-lg p-2.5"
                  />
                </div>
              </div>
            </div>
          ) : (
            <div className="space-y-4 pt-2 border-t border-slate-100">
              <h3 className="text-xs font-bold text-slate-900 uppercase tracking-wider">SAML 2.0 Settings</h3>
              <div className="grid grid-cols-2 gap-4">
                <div>
                  <label className="block text-xs font-semibold text-slate-700 mb-1">IdP Entity ID (Issuer)</label>
                  <input
                    type="text"
                    placeholder="https://idp.company.com/saml/metadata"
                    value={samlEntityId}
                    onChange={(e) => setSamlEntityId(e.target.value)}
                    className="w-full text-xs border border-slate-300 rounded-lg p-2.5"
                    required={providerType === 'saml'}
                  />
                </div>
                <div>
                  <label className="block text-xs font-semibold text-slate-700 mb-1">IdP Single Sign-On (SSO) URL</label>
                  <input
                    type="url"
                    placeholder="https://idp.company.com/saml/sso"
                    value={samlSsoUrl}
                    onChange={(e) => setSamlSsoUrl(e.target.value)}
                    className="w-full text-xs border border-slate-300 rounded-lg p-2.5"
                    required={providerType === 'saml'}
                  />
                </div>
              </div>
              <div>
                <label className="block text-xs font-semibold text-slate-700 mb-1">IdP Public X.509 Certificate (PEM Format)</label>
                <textarea
                  rows={4}
                  placeholder="-----BEGIN CERTIFICATE-----&#10;MIIC...&#10;-----END CERTIFICATE-----"
                  value={samlCert}
                  onChange={(e) => setSamlCert(e.target.value)}
                  className="w-full text-xs font-mono border border-slate-300 rounded-lg p-2.5"
                />
              </div>
              <div className="p-3 bg-indigo-50 border border-indigo-100 rounded-lg text-[11px] text-indigo-900 space-y-1 font-mono">
                <p><strong>SP Entity ID:</strong> urn:capsule:sp</p>
                <p><strong>ACS URL:</strong> http://localhost:8000/v1/auth/sso/saml/callback</p>
                <p><a href="/v1/auth/sso/saml/metadata" target="_blank" className="text-indigo-600 underline font-sans flex items-center gap-1">Download SP Metadata XML <ExternalLink className="w-3 h-3" /></a></p>
              </div>
            </div>
          )}

          <div className="pt-4 border-t border-slate-100 flex justify-end">
            <button
              type="submit"
              disabled={loading}
              className="px-5 py-2.5 bg-indigo-600 hover:bg-indigo-700 text-white rounded-lg text-xs font-semibold shadow-sm"
            >
              Save SSO Configuration
            </button>
          </div>
        </form>
      )}

      {/* TAB 2: Domain Verification */}
      {activeTab === 'domains' && (
        <div className="bg-white border border-slate-200 rounded-xl p-6 space-y-6 shadow-sm">
          <form onSubmit={handleClaimDomain} className="flex gap-3">
            <input
              type="text"
              placeholder="e.g. acme.com"
              value={newDomain}
              onChange={(e) => setNewDomain(e.target.value)}
              className="flex-1 text-xs border border-slate-300 rounded-lg p-2.5"
              required
            />
            <button
              type="submit"
              className="px-4 py-2 bg-indigo-600 hover:bg-indigo-700 text-white rounded-lg text-xs font-semibold flex items-center gap-1"
            >
              <Plus className="w-4 h-4" /> Claim Domain
            </button>
          </form>

          <div className="divide-y divide-slate-100">
            {domains.length === 0 ? (
              <p className="text-xs text-slate-400 py-4 text-center">No domains claimed yet.</p>
            ) : (
              domains.map((dom) => (
                <div key={dom.id} className="py-4 flex items-center justify-between">
                  <div className="space-y-1">
                    <div className="flex items-center gap-2">
                      <span className="font-bold text-slate-900 text-sm">{dom.domain}</span>
                      <span
                        className={`text-[10px] font-semibold px-2 py-0.5 rounded-full ${
                          dom.status === 'verified'
                            ? 'bg-emerald-100 text-emerald-800'
                            : 'bg-amber-100 text-amber-800'
                        }`}
                      >
                        {dom.status.toUpperCase()}
                      </span>
                    </div>
                    <div className="text-[11px] font-mono text-slate-500">
                      DNS TXT Challenge: <code className="bg-slate-100 px-1.5 py-0.5 rounded">{dom.verification_token}</code> at <code className="bg-slate-100 px-1.5 py-0.5 rounded">_capsule-challenge.{dom.domain}</code>
                    </div>
                  </div>

                  <div className="flex items-center gap-2">
                    {dom.status !== 'verified' && (
                      <button
                        onClick={() => handleVerifyDomain(dom.domain)}
                        className="px-3 py-1.5 bg-emerald-600 hover:bg-emerald-700 text-white rounded-lg text-xs font-semibold flex items-center gap-1"
                      >
                        <CheckCircle2 className="w-3.5 h-3.5" /> Verify TXT
                      </button>
                    )}
                    <button
                      onClick={() => handleDeleteDomain(dom.domain)}
                      className="p-1.5 text-slate-400 hover:text-rose-600 rounded-lg hover:bg-slate-100"
                    >
                      <Trash2 className="w-4 h-4" />
                    </button>
                  </div>
                </div>
              ))
            )}
          </div>
        </div>
      )}

      {/* TAB 3: SCIM 2.0 */}
      {activeTab === 'scim' && (
        <div className="bg-white border border-slate-200 rounded-xl p-6 space-y-6 shadow-sm">
          <div className="space-y-3">
            <h3 className="text-sm font-bold text-slate-900">SCIM 2.0 Directory Sync Configuration</h3>
            <p className="text-xs text-slate-500">
              Automate user provisioning and deprovisioning via Okta, Entra ID, or Keycloak SCIM connectors.
            </p>
          </div>

          <div className="p-4 bg-slate-50 border border-slate-200 rounded-xl space-y-2 text-xs">
            <div>
              <span className="font-semibold text-slate-700">SCIM 2.0 Base URL:</span>
              <code className="block bg-white p-2 border border-slate-200 rounded font-mono text-xs mt-1">
                http://localhost:8000/scim/v2
              </code>
            </div>
            <div>
              <span className="font-semibold text-slate-700">Supported Endpoints:</span>
              <p className="font-mono text-[11px] text-slate-500 mt-0.5">/Users, /Groups, /ServiceProviderConfig, /Schemas</p>
            </div>
          </div>

          <div className="p-4 bg-white border border-slate-200 rounded-xl flex items-center justify-between">
            <div>
              <span className="text-xs font-bold text-slate-900 block">SCIM Bearer Token</span>
              <span className="text-xs text-slate-500">
                {scimTokenInfo?.configured
                  ? `Active token prefix: ${scimTokenInfo.token_prefix}•••••••• (Created ${new Date(scimTokenInfo.created_at).toLocaleDateString()})`
                  : 'No token generated yet.'}
              </span>
            </div>
            <button
              onClick={handleRotateScim}
              className="px-4 py-2 bg-indigo-600 hover:bg-indigo-700 text-white rounded-lg text-xs font-semibold flex items-center gap-1.5"
            >
              <RefreshCw className="w-3.5 h-3.5" /> Rotate SCIM Token
            </button>
          </div>

          {rotatedTokenModal && (
            <div className="p-4 bg-amber-50 border border-amber-200 rounded-xl space-y-3">
              <div className="flex items-center gap-2 text-amber-900 font-bold text-xs">
                <AlertCircle className="w-4 h-4 text-amber-600" />
                Copy Your New SCIM Bearer Token
              </div>
              <p className="text-[11px] text-amber-800">
                This token will never be displayed again. Enter it into your Identity Provider's SCIM configuration.
              </p>
              <div className="flex items-center gap-2">
                <input
                  type="text"
                  readOnly
                  value={rotatedTokenModal}
                  className="flex-1 font-mono text-xs bg-white border border-amber-300 rounded-lg p-2.5"
                />
                <button
                  onClick={() => {
                    navigator.clipboard.writeText(rotatedTokenModal);
                    alert('Copied to clipboard!');
                  }}
                  className="px-3 py-2.5 bg-amber-600 hover:bg-amber-700 text-white rounded-lg text-xs font-semibold flex items-center gap-1"
                >
                  <Copy className="w-4 h-4" /> Copy
                </button>
              </div>
            </div>
          )}
        </div>
      )}

      {/* TAB 4: Group Role Mappings */}
      {activeTab === 'mappings' && (
        <div className="bg-white border border-slate-200 rounded-xl p-6 space-y-6 shadow-sm">
          <div className="space-y-1">
            <h3 className="text-sm font-bold text-slate-900">Directory Group to Application Role Mappings</h3>
            <p className="text-xs text-slate-500">
              When users are added or removed from directory groups via SCIM, their application roles update automatically within seconds.
            </p>
          </div>

          <form onSubmit={handleCreateMapping} className="p-4 bg-slate-50 border border-slate-200 rounded-xl space-y-3">
            <h4 className="text-xs font-bold text-slate-800 uppercase tracking-wider">Map Synced Group to Capsule</h4>
            <div className="grid grid-cols-3 gap-3">
              <div>
                <label className="block text-[11px] font-semibold text-slate-600 mb-1">SCIM Group UUID or Name</label>
                <input
                  type="text"
                  placeholder="Group UUID or External ID"
                  value={newMappingGroup}
                  onChange={(e) => setNewMappingGroup(e.target.value)}
                  className="w-full text-xs border border-slate-300 rounded-lg p-2 bg-white"
                  required
                />
              </div>
              <div>
                <label className="block text-[11px] font-semibold text-slate-600 mb-1">Target Application</label>
                <select
                  value={newMappingAppId}
                  onChange={(e) => setNewMappingAppId(e.target.value)}
                  className="w-full text-xs border border-slate-300 rounded-lg p-2 bg-white"
                >
                  {apps.map((a) => (
                    <option key={a.id} value={a.id}>
                      {a.name} ({a.app_key})
                    </option>
                  ))}
                </select>
              </div>
              <div>
                <label className="block text-[11px] font-semibold text-slate-600 mb-1">Assigned App Role</label>
                <select
                  value={newMappingRole}
                  onChange={(e) => setNewMappingRole(e.target.value)}
                  className="w-full text-xs border border-slate-300 rounded-lg p-2 bg-white"
                >
                  <option value="editor">editor</option>
                  <option value="viewer">viewer</option>
                  <option value="manager">manager</option>
                  <option value="admin">admin</option>
                </select>
              </div>
            </div>
            <div className="flex justify-end">
              <button
                type="submit"
                className="px-4 py-2 bg-indigo-600 hover:bg-indigo-700 text-white rounded-lg text-xs font-semibold flex items-center gap-1"
              >
                <Plus className="w-4 h-4" /> Create Mapping
              </button>
            </div>
          </form>

          <table className="w-full text-xs border-collapse">
            <thead>
              <tr className="border-b border-slate-200 text-slate-400 font-medium text-left">
                <th className="py-2.5">Directory Group</th>
                <th className="py-2.5">Capsule App</th>
                <th className="py-2.5">Granted Role</th>
                <th className="py-2.5 text-right">Actions</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {mappings.length === 0 ? (
                <tr>
                  <td colSpan={4} className="py-6 text-center text-slate-400">
                    No group role mappings configured yet.
                  </td>
                </tr>
              ) : (
                mappings.map((m) => (
                  <tr key={m.id} className="hover:bg-slate-50">
                    <td className="py-3 font-semibold text-slate-900">{m.group_name}</td>
                    <td className="py-3 font-mono text-indigo-600">{m.app_key}</td>
                    <td className="py-3">
                      <span className="px-2 py-0.5 bg-slate-100 rounded text-slate-700 font-mono text-[11px]">{m.app_role}</span>
                    </td>
                    <td className="py-3 text-right">
                      <button
                        onClick={() => handleDeleteMapping(m.id)}
                        className="p-1 text-slate-400 hover:text-rose-600 rounded"
                      >
                        <Trash2 className="w-4 h-4" />
                      </button>
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
};

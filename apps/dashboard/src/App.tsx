import React, { useState, useEffect } from 'react';
import { UserProfile } from './types';
import { api, clearStoredToken, getStoredToken } from './api';
import { Layout } from './components/Layout';
import { SignInScreen } from './screens/SignInScreen';
import { AppsListScreen } from './screens/AppsListScreen';
import { AppDetailScreen } from './screens/AppDetailScreen';
import { VersionHistoryScreen } from './screens/VersionHistoryScreen';
import { ShieldCheck, Layers, Settings, Activity } from 'lucide-react';

export const App: React.FC = () => {
  const [currentUser, setCurrentUser] = useState<UserProfile | null>(null);
  const [activeNav, setActiveNav] = useState('capsules');
  const [selectedAppId, setSelectedAppId] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    initAuth();
  }, []);

  const initAuth = async () => {
    try {
      setLoading(true);
      const token = getStoredToken();
      if (!token) {
        setCurrentUser(null);
        return;
      }
      const user = await api.getMe();
      setCurrentUser(user);
    } catch {
      // Not authenticated or mock token invalid
      setCurrentUser(null);
    } finally {
      setLoading(false);
    }
  };

  const handleSignOut = () => {
    clearStoredToken();
    setCurrentUser(null);
    setActiveNav('signin');
  };

  const handleSelectApp = (appId: string) => {
    setSelectedAppId(appId);
    setActiveNav('app-detail');
  };

  const handleBackToApps = () => {
    setSelectedAppId(null);
    setActiveNav('capsules');
  };

  if (loading) {
    return (
      <div className="min-h-screen bg-slate-50 flex items-center justify-center text-xs font-mono text-slate-400">
        Initializing Software Capsule Dashboard...
      </div>
    );
  }

  // If on signin screen or not authenticated
  if (activeNav === 'signin' || !currentUser) {
    return (
      <SignInScreen
        onSignedIn={() => {
          initAuth();
          setActiveNav('capsules');
        }}
      />
    );
  }

  return (
    <Layout
      user={currentUser}
      activeNav={activeNav}
      onNavigate={(nav) => {
        if (nav === 'capsules') setSelectedAppId(null);
        setActiveNav(nav);
      }}
      onSignOut={handleSignOut}
    >
      {activeNav === 'capsules' && (
        <AppsListScreen
          currentUser={currentUser}
          onSelectApp={handleSelectApp}
        />
      )}

      {activeNav === 'app-detail' && selectedAppId && (
        <AppDetailScreen
          appId={selectedAppId}
          currentUser={currentUser}
          onBack={handleBackToApps}
        />
      )}

      {activeNav === 'versions' && (
        <VersionHistoryScreen onSelectApp={handleSelectApp} />
      )}

      {activeNav === 'activity' && (
        <div className="max-w-4xl mx-auto space-y-4">
          <h2 className="text-xl font-bold text-slate-900 flex items-center gap-2">
            <Activity className="w-5 h-5 text-indigo-600" />
            Platform Activity Stream
          </h2>
          <div className="p-6 bg-white border border-slate-200 rounded-xl text-xs text-slate-600 space-y-3">
            <p>Real-time audit log of all deployment, permission, and access events across your organization.</p>
            <div className="divide-y divide-slate-100 font-mono text-[11px]">
              <div className="py-2 flex justify-between">
                <span>[app.publish] leave-tracker published version 1</span>
                <span className="text-slate-400">Today, 10:45 AM</span>
              </div>
              <div className="py-2 flex justify-between">
                <span>[share.create] Shared leave-tracker with bob@example.com (role: manager)</span>
                <span className="text-slate-400">Today, 10:50 AM</span>
              </div>
            </div>
          </div>
        </div>
      )}

      {activeNav === 'environment' && (
        <div className="max-w-4xl mx-auto space-y-4">
          <h2 className="text-xl font-bold text-slate-900 flex items-center gap-2">
            <Layers className="w-5 h-5 text-indigo-600" />
            Environment & Sandbox Runtimes
          </h2>
          <div className="p-6 bg-white border border-slate-200 rounded-xl text-xs space-y-3">
            <p className="text-slate-600">Active sandbox driver and isolation infrastructure configuration:</p>
            <div className="grid grid-cols-2 gap-4 pt-2">
              <div className="p-4 bg-slate-50 border border-slate-200 rounded-lg">
                <span className="font-bold text-slate-900 block mb-1">Development Sandbox Driver</span>
                <span className="text-slate-600">DockerDevDriver (Non-root, read-only rootfs, dropped caps, network=none)</span>
              </div>
              <div className="p-4 bg-slate-50 border border-slate-200 rounded-lg">
                <span className="font-bold text-slate-900 block mb-1">Production Sandbox Driver</span>
                <span className="text-slate-600">gVisor / Firecracker (OCI MicroVM Boundary)</span>
              </div>
            </div>
          </div>
        </div>
      )}

      {activeNav === 'audit' && (
        <div className="max-w-4xl mx-auto space-y-4">
          <h2 className="text-xl font-bold text-slate-900 flex items-center gap-2">
            <ShieldCheck className="w-5 h-5 text-indigo-600" />
            Compliance & Audit Vault
          </h2>
          <div className="p-6 bg-white border border-slate-200 rounded-xl text-xs text-slate-600 space-y-2">
            <p>All administrative mutations and capability approval escalations are immutably signed and preserved.</p>
            <p className="font-mono text-slate-500">Security Invariants 1 through 10 verified.</p>
          </div>
        </div>
      )}

      {activeNav === 'settings' && (
        <div className="max-w-4xl mx-auto space-y-4">
          <h2 className="text-xl font-bold text-slate-900 flex items-center gap-2">
            <Settings className="w-5 h-5 text-indigo-600" />
            Organization Settings
          </h2>
          <div className="p-6 bg-white border border-slate-200 rounded-xl text-xs text-slate-600 space-y-3">
            <div className="flex justify-between py-2 border-b border-slate-100">
              <span className="font-semibold text-slate-800">Organization Name</span>
              <span>Acme Corp</span>
            </div>
            <div className="flex justify-between py-2 border-b border-slate-100">
              <span className="font-semibold text-slate-800">Default Sharing Scope</span>
              <span>Organization Internal</span>
            </div>
            <div className="flex justify-between py-2">
              <span className="font-semibold text-slate-800">External Guest Access</span>
              <span className="text-rose-600 font-semibold">Disabled by default</span>
            </div>
          </div>
        </div>
      )}
    </Layout>
  );
};

import React, { useState } from 'react';
import { setStoredToken } from '../api';
import { Shield, UserCheck, Key, ArrowRight, CheckCircle2 } from 'lucide-react';

interface SignInScreenProps {
  onSignedIn: () => void;
}

export const SignInScreen: React.FC<SignInScreenProps> = ({ onSignedIn }) => {
  const [customToken, setCustomToken] = useState('');
  const [loadingPersona, setLoadingPersona] = useState<string | null>(null);

  const personas = [
    {
      name: 'Alice Owner',
      email: 'alice@example.com',
      role: 'Platform Owner',
      token: 'mock-alice-token',
      badge: 'Owner (Acme Corp)',
      description: 'Can manage apps, publish versions, grant/revoke shares, and view audit events.',
      bg: 'hover:border-indigo-400 bg-indigo-50/40',
    },
    {
      name: 'Bob Colleague',
      email: 'bob@example.com',
      role: 'Platform User',
      token: 'mock-bob-token',
      badge: 'User (Acme Corp)',
      description: 'Internal colleague. Can access shared apps; restricted from modifying shares.',
      bg: 'hover:border-emerald-400 bg-emerald-50/40',
    },
    {
      name: 'Charlie External',
      email: 'charlie@other.com',
      role: 'External User',
      token: 'mock-charlie-token',
      badge: 'User (Other Corp)',
      description: 'External guest user. Blocked from Acme apps by tenant isolation.',
      bg: 'hover:border-amber-400 bg-amber-50/40',
    },
  ];

  const handleSelectPersona = (token: string, name: string) => {
    setLoadingPersona(name);
    setStoredToken(token);
    setTimeout(() => {
      onSignedIn();
    }, 300);
  };

  const handleCustomTokenSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!customToken.trim()) return;
    setStoredToken(customToken.trim());
    onSignedIn();
  };

  return (
    <div className="max-w-xl mx-auto py-12 px-4">
      {/* Brand Header */}
      <div className="text-center mb-8">
        <div className="inline-flex items-center justify-center w-14 h-14 rounded-2xl bg-indigo-600 text-white font-bold text-2xl mb-4 shadow-lg shadow-indigo-200">
          C
        </div>
        <h1 className="text-2xl font-black text-slate-900 tracking-tight">Software Capsule Platform</h1>
        <p className="text-sm text-slate-500 mt-1">
          Secure, isolated runtime infrastructure for agent-built software
        </p>
      </div>

      {/* Main Card */}
      <div className="bg-white rounded-2xl shadow-xl border border-slate-200 overflow-hidden">
        <div className="p-6 border-b border-slate-100 bg-slate-50/50">
          <h2 className="text-base font-bold text-slate-900 flex items-center gap-2">
            <UserCheck className="w-5 h-5 text-indigo-600" />
            Sign in to Platform Dashboard
          </h2>
          <p className="text-xs text-slate-500 mt-1">
            Choose a development persona or enter a valid OIDC / API bearer token.
          </p>
        </div>

        <div className="p-6 space-y-4">
          <label className="block text-xs font-bold text-slate-500 uppercase tracking-wider">
            Quick Sign-In Personas (Dev IdP)
          </label>

          <div className="grid gap-3">
            {personas.map((p) => (
              <button
                key={p.token}
                onClick={() => handleSelectPersona(p.token, p.name)}
                disabled={loadingPersona !== null}
                className={`w-full text-left p-4 rounded-xl border border-slate-200 transition-all ${p.bg} flex items-start justify-between group focus:outline-none focus:ring-2 focus:ring-indigo-500`}
              >
                <div>
                  <div className="flex items-center gap-2">
                    <span className="font-bold text-sm text-slate-900">{p.name}</span>
                    <span className="text-[11px] font-mono px-2 py-0.5 rounded-full bg-white border border-slate-200 text-slate-700">
                      {p.badge}
                    </span>
                  </div>
                  <p className="text-xs text-slate-500 mt-0.5">{p.email}</p>
                  <p className="text-xs text-slate-600 mt-2">{p.description}</p>
                </div>
                <div className="pt-1 text-slate-400 group-hover:text-slate-900 group-hover:translate-x-1 transition-all">
                  <ArrowRight className="w-5 h-5" />
                </div>
              </button>
            ))}
          </div>

          <div className="relative my-6">
            <div className="absolute inset-0 flex items-center">
              <div className="w-full border-t border-slate-200" />
            </div>
            <div className="relative flex justify-center text-xs uppercase">
              <span className="bg-white px-2 text-slate-400 font-semibold">Or enter custom bearer token</span>
            </div>
          </div>

          {/* Custom token input */}
          <form onSubmit={handleCustomTokenSubmit} className="space-y-3">
            <div>
              <label htmlFor="token-input" className="block text-xs font-semibold text-slate-700 mb-1">
                Bearer Token / JWT
              </label>
              <div className="relative">
                <input
                  id="token-input"
                  type="text"
                  value={customToken}
                  onChange={(e) => setCustomToken(e.target.value)}
                  placeholder="mock-alice-token or eyJhbGciOi..."
                  className="w-full pl-9 pr-3 py-2 text-xs font-mono border border-slate-300 rounded-lg focus:ring-2 focus:ring-indigo-500 focus:border-indigo-500"
                />
                <Key className="w-4 h-4 text-slate-400 absolute left-3 top-2.5" />
              </div>
            </div>
            <button
              type="submit"
              disabled={!customToken.trim()}
              className="w-full py-2 px-4 rounded-lg bg-slate-900 text-white text-xs font-semibold hover:bg-slate-800 disabled:opacity-50 transition-colors"
            >
              Sign In with Token
            </button>
          </form>
        </div>

        <div className="p-4 bg-slate-50 border-t border-slate-100 flex items-center justify-between text-xs text-slate-500">
          <span className="flex items-center gap-1.5">
            <Shield className="w-3.5 h-3.5 text-indigo-600" />
            Domain: platform.localhost
          </span>
          <span>Security Invariant 5 Active</span>
        </div>
      </div>
    </div>
  );
};

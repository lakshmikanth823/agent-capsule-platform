import React from 'react';
import { UserProfile } from '../types';
import { 
  Box, 
  Activity, 
  Layers, 
  ShieldCheck, 
  Settings, 
  LogOut, 
  User as UserIcon,
  ExternalLink
} from 'lucide-react';

interface LayoutProps {
  user: UserProfile | null;
  activeNav: string;
  onNavigate: (nav: string) => void;
  onSignOut: () => void;
  children: React.ReactNode;
}

export const Layout: React.FC<LayoutProps> = ({
  user,
  activeNav,
  onNavigate,
  onSignOut,
  children,
}) => {
  const navItems = [
    { id: 'capsules', label: 'Capsules', icon: Box },
    { id: 'activity', label: 'Activity', icon: Activity },
    { id: 'environment', label: 'Environment', icon: Layers },
    { id: 'audit', label: 'Audit', icon: ShieldCheck },
    { id: 'settings', label: 'Settings', icon: Settings },
  ];

  return (
    <div className="flex min-h-screen bg-slate-50 text-slate-800">
      {/* Sidebar matching wireframe */}
      <aside className="w-64 border-r border-slate-200 bg-white flex flex-col justify-between p-4 shrink-0">
        <div>
          {/* Logo & Brand */}
          <div className="pb-6 border-b border-slate-100">
            <div className="flex items-center gap-2">
              <div className="w-8 h-8 rounded bg-indigo-600 text-white flex items-center justify-center font-bold text-lg">
                C
              </div>
              <div>
                <h1 className="font-bold text-sm tracking-wider uppercase text-slate-900">Software Capsule</h1>
                <p className="text-xs text-slate-500 font-mono">v0.2 / alpha</p>
              </div>
            </div>
          </div>

          {/* Navigation */}
          <nav className="mt-6 space-y-1">
            {navItems.map((item) => {
              const Icon = item.icon;
              const isActive = activeNav === item.id;
              return (
                <button
                  key={item.id}
                  onClick={() => onNavigate(item.id)}
                  className={`w-full flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm font-medium transition-colors ${
                    isActive
                      ? 'bg-indigo-50 text-indigo-700 border border-indigo-200 font-semibold'
                      : 'text-slate-600 hover:bg-slate-100 hover:text-slate-900'
                  }`}
                >
                  <Icon className={`w-4 h-4 ${isActive ? 'text-indigo-600' : 'text-slate-400'}`} />
                  {item.label}
                </button>
              );
            })}
          </nav>
        </div>

        {/* User Info & Sign Out */}
        <div className="pt-4 border-t border-slate-200">
          {user ? (
            <div className="flex flex-col gap-2">
              <div className="flex items-center gap-3 px-2 py-1">
                <div className="w-8 h-8 rounded-full bg-slate-200 flex items-center justify-center text-slate-600 font-medium text-xs">
                  {user.name.slice(0, 2).toUpperCase()}
                </div>
                <div className="overflow-hidden">
                  <p className="text-xs font-semibold text-slate-900 truncate">{user.name}</p>
                  <p className="text-xs text-slate-500 truncate">{user.email}</p>
                </div>
              </div>
              <div className="flex items-center justify-between px-2 pt-1">
                <span className="inline-flex items-center px-2 py-0.5 rounded text-[10px] font-semibold bg-indigo-100 text-indigo-800 uppercase tracking-wide">
                  {user.platform_role}
                </span>
                <button
                  onClick={onSignOut}
                  title="Sign out"
                  className="text-xs text-slate-500 hover:text-rose-600 flex items-center gap-1 font-medium transition-colors"
                >
                  <LogOut className="w-3.5 h-3.5" />
                  Sign out
                </button>
              </div>
            </div>
          ) : (
            <button
              onClick={() => onNavigate('signin')}
              className="w-full flex items-center justify-center gap-2 py-2 px-3 text-xs font-semibold rounded-md bg-indigo-600 text-white hover:bg-indigo-700 transition-colors"
            >
              <UserIcon className="w-3.5 h-3.5" />
              Sign in
            </button>
          )}
        </div>
      </aside>

      {/* Main Content Area */}
      <div className="flex-1 flex flex-col min-w-0">
        {/* Top Header */}
        <header className="h-14 border-b border-slate-200 bg-white px-8 flex items-center justify-between">
          <div className="flex items-center gap-4">
            <span className="text-xs font-semibold uppercase tracking-wider text-slate-500">
              ORG / Acme
            </span>
          </div>
          <div className="flex items-center gap-3">
            <span className="text-xs text-slate-400">Dashboard Domain</span>
            <span className="inline-flex items-center px-2 py-0.5 rounded text-xs font-mono bg-slate-100 text-slate-700 border border-slate-200">
              platform.localhost:8080
            </span>
          </div>
        </header>

        {/* Content Body */}
        <main className="flex-1 p-8 overflow-y-auto">
          {children}
        </main>
      </div>
    </div>
  );
};

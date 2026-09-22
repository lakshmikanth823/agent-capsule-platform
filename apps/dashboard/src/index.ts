/**
 * @capsule/dashboard
 * Web dashboard for inspecting Capsules, managing sharing, and previewing permissions.
 */

export * from './types.js';
export { api } from './api.js';
export { EnvironmentProfileScreen } from './screens/EnvironmentProfileScreen.js';

export interface DashboardAppSummary {
  id: string;
  name: string;
  version: number;
  status: 'active' | 'suspended';
  ownerEmail: string;
  updatedAt: string;
}

export const dashboardAppVersion = '0.1.0';


/**
 * Edge Proxy Configuration
 *
 * NOTE FOR PRODUCTION:
 * APP_DOMAIN and DASHBOARD_DOMAIN MUST be two distinct registrable domains
 * (e.g. `capsule-apps.com` and `capsule-platform.com`) to satisfy Security Invariant 5
 * ("Applications are served from a different origin than the dashboard") and prevent
 * cookie sharing across eTLD+1 boundaries.
 */

export interface ProxyConfig {
  appDomain: string;
  dashboardDomain: string;
  port: number;
  controlPlaneUrl: string;
  sessionSecret: string;
  activeKeyId: string;
  signingKeys: Record<string, string>;
  isProduction: boolean;
}

export function loadConfig(): ProxyConfig {
  const isProduction =
    process.env.NODE_ENV === "production" ||
    process.env.PLATFORM_ENV === "production";
  const appDomain =
    process.env.APP_DOMAIN ||
    process.env.APP_BASE_DOMAIN ||
    (isProduction ? "" : "apps.localhost");
  const dashboardDomain =
    process.env.DASHBOARD_DOMAIN ||
    process.env.PLATFORM_DOMAIN ||
    (isProduction ? "" : "platform.localhost");

  if (isProduction) {
    if (!appDomain) {
      throw new Error(
        "SECURITY VIOLATION: APP_DOMAIN (or APP_BASE_DOMAIN) must be set in production.",
      );
    }
    if (!dashboardDomain) {
      throw new Error(
        "SECURITY VIOLATION: DASHBOARD_DOMAIN (or PLATFORM_DOMAIN) must be set in production.",
      );
    }
    if (appDomain === dashboardDomain) {
      throw new Error(
        "SECURITY VIOLATION: APP_DOMAIN and DASHBOARD_DOMAIN must be different in production to ensure origin and cookie isolation.",
      );
    }
    if (!process.env.IDENTITY_SIGNING_KEY) {
      throw new Error(
        "SECURITY VIOLATION: IDENTITY_SIGNING_KEY must be set in production.",
      );
    }
    if (!process.env.SESSION_SECRET) {
      throw new Error(
        "SECURITY VIOLATION: SESSION_SECRET must be set in production.",
      );
    }
    if (!process.env.CONTROL_PLANE_SERVICE_TOKEN) {
      throw new Error(
        "SECURITY VIOLATION: CONTROL_PLANE_SERVICE_TOKEN must be set in production.",
      );
    }
  }

  const activeKeyId = process.env.ACTIVE_KEY_ID || "key-2026-09";
  const signingKeys: Record<string, string> = {
    "key-2026-09":
      process.env.IDENTITY_SIGNING_KEY ||
      "dev-identity-secret-key-must-be-32-bytes-long!",
    "key-2026-08": "older-identity-secret-key-for-rotation-testing!",
  };

  return {
    appDomain,
    dashboardDomain,
    port: Number(process.env.PORT) || 8080,
    controlPlaneUrl: process.env.CONTROL_PLANE_URL || "http://127.0.0.1:8000",
    sessionSecret:
      process.env.SESSION_SECRET ||
      "dev-session-secret-change-in-production-32-chars!",
    activeKeyId,
    signingKeys,
    isProduction,
  };
}

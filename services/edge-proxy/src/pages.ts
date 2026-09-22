/**
 * Edge Proxy User-Facing HTML Pages
 *
 * Clean, accessible HTML pages for:
 * - 404 App Not Found
 * - 403 Not Authorized
 * - Platform Login (Mock IdP in development)
 */

export function renderAppNotFoundPage(
  appKey: string,
  hostname: string,
): string {
  return `<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>404 - Capsule Not Found</title>
  <style>
    body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background: #f9fafb; color: #111827; display: flex; align-items: center; justify-content: center; min-height: 100vh; margin: 0; }
    .card { background: #ffffff; border: 1px solid #e5e7eb; border-radius: 12px; padding: 32px; max-width: 480px; width: 100%; box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.05); }
    h1 { font-size: 20px; font-weight: 600; margin: 0 0 12px 0; color: #111827; }
    p { font-size: 14px; color: #4b5563; line-height: 1.5; margin: 0 0 16px 0; }
    .badge { display: inline-block; background: #f3f4f6; color: #374151; padding: 4px 8px; border-radius: 6px; font-family: monospace; font-size: 13px; margin-bottom: 16px; }
    .footer { font-size: 12px; color: #9ca3af; margin-top: 24px; border-top: 1px solid #f3f4f6; padding-top: 12px; }
  </style>
</head>
<body>
  <div class="card">
    <h1>Capsule Not Found</h1>
    <p>The application you requested does not exist or has not been published yet.</p>
    <div><span class="badge">${appKey}</span> on <code>${hostname}</code></div>
    <p>Please check the URL or publish a version using the Capsule CLI.</p>
    <div class="footer">Software Capsule Platform • Edge Proxy</div>
  </div>
</body>
</html>`;
}

export function renderNotAuthorizedPage(
  appKey: string,
  userEmail: string,
  orgId: string,
  reason = "You do not have permission to access this capsule.",
): string {
  return `<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>403 - Not Authorized</title>
  <style>
    body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background: #f9fafb; color: #111827; display: flex; align-items: center; justify-content: center; min-height: 100vh; margin: 0; }
    .card { background: #ffffff; border: 1px solid #fee2e2; border-radius: 12px; padding: 32px; max-width: 480px; width: 100%; box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.05); }
    h1 { font-size: 20px; font-weight: 600; margin: 0 0 12px 0; color: #991b1b; }
    p { font-size: 14px; color: #4b5563; line-height: 1.5; margin: 0 0 16px 0; }
    .info { background: #fef2f2; border: 1px solid #fecaca; border-radius: 6px; padding: 12px; margin-bottom: 16px; font-size: 13px; }
    .info p { margin: 4px 0; color: #7f1d1d; }
    .footer { font-size: 12px; color: #9ca3af; margin-top: 24px; border-top: 1px solid #f3f4f6; padding-top: 12px; }
  </style>
</head>
<body>
  <div class="card">
    <h1>Access Denied</h1>
    <p>${reason}</p>
    <div class="info">
      <p><strong>App:</strong> ${appKey}</p>
      <p><strong>User:</strong> ${userEmail}</p>
      <p><strong>Org ID:</strong> ${orgId}</p>
    </div>
    <p>Contact the capsule owner or your organization administrator to request access.</p>
    <div class="footer">Software Capsule Platform • Edge Proxy</div>
  </div>
</body>
</html>`;
}

export function renderPlatformLoginPage(
  targetApp: string,
  returnTo: string,
): string {
  return `<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Platform Login - Software Capsule</title>
  <style>
    body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background: #f9fafb; color: #111827; display: flex; align-items: center; justify-content: center; min-height: 100vh; margin: 0; }
    .card { background: #ffffff; border: 1px solid #e5e7eb; border-radius: 12px; padding: 32px; max-width: 440px; width: 100%; box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.05); }
    h1 { font-size: 20px; font-weight: 600; margin: 0 0 8px 0; color: #111827; }
    p { font-size: 14px; color: #4b5563; margin: 0 0 20px 0; }
    .btn { display: block; width: 100%; box-sizing: border-box; padding: 10px 16px; margin-bottom: 12px; border: 1px solid #d1d5db; border-radius: 6px; background: #ffffff; color: #374151; font-weight: 500; font-size: 14px; text-align: left; cursor: pointer; text-decoration: none; }
    .btn:hover { background: #f3f4f6; }
    .btn strong { display: block; color: #111827; }
    .btn span { font-size: 12px; color: #6b7280; }
    .footer { font-size: 12px; color: #9ca3af; margin-top: 24px; border-top: 1px solid #f3f4f6; padding-top: 12px; }
  </style>
</head>
<body>
  <div class="card">
    <h1>Sign In to Platform</h1>
    <p>Sign in to access <strong>${targetApp}</strong></p>

    <a class="btn" style="background: #eff6ff; border-color: #bfdbfe;" href="http://127.0.0.1:8000/v1/auth/sso/login?org_slug=acme&target_app=${encodeURIComponent(targetApp)}&return_to=${encodeURIComponent(returnTo)}">
      <strong style="color: #1d4ed8;">Corporate Single Sign-On (SSO)</strong>
      <span style="color: #3b82f6;">Log in with company OIDC or SAML 2.0 IdP</span>
    </a>

    <div style="margin: 16px 0; text-align: center; font-size: 11px; color: #9ca3af; text-transform: uppercase; letter-spacing: 0.05em;">or continue with local account</div>

    <a class="btn" href="/auth/ticket?user=alice&target_app=${encodeURIComponent(targetApp)}&return_to=${encodeURIComponent(returnTo)}">
      <strong>Alice (Owner)</strong>
      <span>alice@example.com • Acme Corp</span>
    </a>

    <a class="btn" href="/auth/ticket?user=bob&target_app=${encodeURIComponent(targetApp)}&return_to=${encodeURIComponent(returnTo)}">
      <strong>Bob (Member)</strong>
      <span>bob@example.com • Acme Corp</span>
    </a>

    <a class="btn" href="/auth/ticket?user=charlie&target_app=${encodeURIComponent(targetApp)}&return_to=${encodeURIComponent(returnTo)}">
      <strong>Charlie (External User)</strong>
      <span>charlie@other.com • Other Corp (Unauthorized)</span>
    </a>

    <div class="footer">Software Capsule Platform • Development Identity Provider</div>
  </div>
</body>
</html>`;
}

export function renderAppSuspendedPage(
  appKey: string,
  reason?: string,
): string {
  return `<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>503 - Capsule Suspended</title>
  <style>
    body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background: #fefce8; color: #713f12; display: flex; align-items: center; justify-content: center; min-height: 100vh; margin: 0; }
    .card { background: #ffffff; border: 1px solid #fef08a; border-radius: 12px; padding: 32px; max-width: 480px; width: 100%; box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.05); }
    h1 { font-size: 20px; font-weight: 600; margin: 0 0 12px 0; color: #854d0e; }
    p { font-size: 14px; color: #4b5563; line-height: 1.5; margin: 0 0 16px 0; }
    .badge { display: inline-block; background: #fef9c3; color: #854d0e; padding: 4px 8px; border-radius: 6px; font-family: monospace; font-size: 13px; margin-bottom: 16px; border: 1px solid #fef08a; }
    .reason { background: #fffbeb; border: 1px solid #fde68a; border-radius: 6px; padding: 12px; margin-bottom: 16px; font-size: 13px; color: #92400e; }
    .footer { font-size: 12px; color: #9ca3af; margin-top: 24px; border-top: 1px solid #f3f4f6; padding-top: 12px; }
  </style>
</head>
<body>
  <div class="card">
    <h1>Capsule Suspended</h1>
    <p>This application has been suspended by an administrator or emergency kill switch.</p>
    <div><span class="badge">${appKey}</span></div>
    ${reason ? `<div class="reason"><strong>Reason:</strong> ${reason}</div>` : ""}
    <p>Please contact your capsule owner or organization administrator to resume this service.</p>
    <div class="footer">Software Capsule Platform • Edge Proxy Kill Switch</div>
  </div>
</body>
</html>`;
}

export function renderOrgSuspendedPage(orgId: string, reason?: string): string {
  return `<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>503 - Organization Suspended</title>
  <style>
    body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background: #fef2f2; color: #7f1d1d; display: flex; align-items: center; justify-content: center; min-height: 100vh; margin: 0; }
    .card { background: #ffffff; border: 1px solid #fecaca; border-radius: 12px; padding: 32px; max-width: 480px; width: 100%; box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.05); }
    h1 { font-size: 20px; font-weight: 600; margin: 0 0 12px 0; color: #991b1b; }
    p { font-size: 14px; color: #4b5563; line-height: 1.5; margin: 0 0 16px 0; }
    .badge { display: inline-block; background: #fee2e2; color: #991b1b; padding: 4px 8px; border-radius: 6px; font-family: monospace; font-size: 13px; margin-bottom: 16px; border: 1px solid #fecaca; }
    .reason { background: #fef2f2; border: 1px solid #fecaca; border-radius: 6px; padding: 12px; margin-bottom: 16px; font-size: 13px; color: #991b1b; }
    .footer { font-size: 12px; color: #9ca3af; margin-top: 24px; border-top: 1px solid #f3f4f6; padding-top: 12px; }
  </style>
</head>
<body>
  <div class="card">
    <h1>Organization Frozen</h1>
    <p>All applications in this organization have been frozen by an emergency organization kill switch.</p>
    <div><span class="badge">Org: ${orgId}</span></div>
    ${reason ? `<div class="reason"><strong>Reason:</strong> ${reason}</div>` : ""}
    <p>All sandboxes are suspended and egress is disabled. Contact your organization administrator.</p>
    <div class="footer">Software Capsule Platform • Edge Proxy Kill Switch</div>
  </div>
</body>
</html>`;
}

export function renderConsentScreen(params: {
  appKey: string;
  userEmail: string;
  connectorName: string;
  scopes: string[];
  spreadsheetIds?: string[];
  returnTo: string;
}): string {
  const scopeList = params.scopes
    .map((s) => `<li><code>${s}</code></li>`)
    .join("");
  const sheetList =
    params.spreadsheetIds && params.spreadsheetIds.length > 0
      ? `<div style="margin-top: 10px;"><strong>Allowed Spreadsheets:</strong><ul style="margin: 4px 0 0 0; padding-left: 20px;">${params.spreadsheetIds.map((id) => `<li><code>${id}</code></li>`).join("")}</ul></div>`
      : `<p style="margin-top: 8px; font-style: italic; color: #4b5563;">Access to spreadsheets permitted by your Google account.</p>`;

  return `<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Authorize Google Sheets - Software Capsule</title>
  <style>
    body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background: #f9fafb; color: #111827; display: flex; align-items: center; justify-content: center; min-height: 100vh; margin: 0; }
    .card { background: #ffffff; border: 1px solid #e5e7eb; border-radius: 12px; padding: 32px; max-width: 480px; width: 100%; box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.05); }
    h1 { font-size: 20px; font-weight: 600; margin: 0 0 12px 0; color: #111827; }
    p { font-size: 14px; color: #4b5563; line-height: 1.5; margin: 0 0 16px 0; }
    .badge { display: inline-block; background: #e0f2fe; color: #0369a1; padding: 4px 8px; border-radius: 6px; font-family: monospace; font-size: 13px; margin-bottom: 16px; border: 1px solid #bae6fd; }
    .permission-box { background: #f8fafc; border: 1px solid #e2e8f0; border-radius: 8px; padding: 16px; margin: 16px 0; font-size: 13px; }
    .permission-box ul { margin: 8px 0 0 0; padding-left: 20px; }
    .permission-box li { margin-bottom: 4px; }
    .btn-group { display: flex; gap: 12px; margin-top: 24px; }
    .btn-primary { flex: 1; padding: 10px 16px; background: #2563eb; color: #ffffff; border: none; border-radius: 6px; font-weight: 500; font-size: 14px; cursor: pointer; text-align: center; text-decoration: none; display: inline-block; }
    .btn-primary:hover { background: #1d4ed8; }
    .btn-secondary { padding: 10px 16px; background: #f3f4f6; color: #374151; border: 1px solid #d1d5db; border-radius: 6px; font-weight: 500; font-size: 14px; cursor: pointer; text-align: center; text-decoration: none; display: inline-block; }
    .btn-secondary:hover { background: #e5e7eb; }
    .footer { font-size: 12px; color: #9ca3af; margin-top: 24px; border-top: 1px solid #f3f4f6; padding-top: 12px; }
  </style>
</head>
<body>
  <div class="card">
    <div class="badge">${params.appKey}</div>
    <h1>Connect Google Sheets</h1>
    <p><strong>${params.appKey}</strong> requests permission to view spreadsheets on your behalf (as <strong>${params.userEmail}</strong>).</p>
    
    <div class="permission-box">
      <strong>Requested Scope:</strong>
      <ul>${scopeList}</ul>
      ${sheetList}
    </div>

    <p style="font-size: 12px; color: #6b7280;">Your credentials are encrypted and stored per-user. The application never sees your raw OAuth token and only receives the data returned.</p>

    <div class="btn-group">
      <a class="btn-secondary" href="/auth/cancel?return_to=${encodeURIComponent(params.returnTo)}">Cancel</a>
      <a class="btn-primary" href="/auth/connectors/google/authorize?app=${encodeURIComponent(params.appKey)}&return_to=${encodeURIComponent(params.returnTo)}">Allow Access</a>
    </div>

    <div class="footer">Software Capsule Platform • Viewer Identity Consent</div>
  </div>
</body>
</html>`;
}

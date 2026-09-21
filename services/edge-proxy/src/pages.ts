/**
 * Edge Proxy User-Facing HTML Pages
 *
 * Clean, accessible HTML pages for:
 * - 404 App Not Found
 * - 403 Not Authorized
 * - Platform Login (Mock IdP in development)
 */

export function renderAppNotFoundPage(appKey: string, hostname: string): string {
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
  reason = 'You do not have permission to access this capsule.'
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

export function renderPlatformLoginPage(targetApp: string, returnTo: string): string {
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

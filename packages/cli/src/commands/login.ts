/**
 * capsule login
 * Authenticates user and saves session token.
 * Does not require users or agents to paste long-lived secrets into terminal arguments.
 */
import { saveConfig, loadConfig } from "../config.js";
import { ApiClient } from "../client.js";
import { outputResult, outputError, CliError } from "../errors.js";

export interface LoginOptions {
  user?: string;
  url?: string;
  json?: boolean;
}

export async function loginCommand(options: LoginOptions = {}): Promise<void> {
  const currentConfig = loadConfig();
  const apiUrl = options.url || currentConfig.apiUrl || "http://localhost:8000";

  let token: string;
  let userEmail: string;

  if (options.user) {
    userEmail = options.user;
    if (userEmail === "alice@example.com" || userEmail === "alice") {
      token = "mock-alice-token";
    } else if (userEmail === "bob@example.com" || userEmail === "bob") {
      token = "mock-bob-token";
    } else if (userEmail === "charlie@other.com" || userEmail === "charlie") {
      token = "mock-charlie-token";
    } else {
      token = `mock:${userEmail}`;
    }
  } else {
    // Default to alice for local development if no user specified
    userEmail = "alice@example.com";
    token = "mock-alice-token";
  }

  // Verify token against control-plane
  const client = new ApiClient({
    apiUrl,
    token,
  });

  try {
    const authStatus = await client.verifyAuth(token);

    // Save session configuration
    const saved = saveConfig({
      apiUrl,
      token,
      user: {
        id: authStatus.user_id,
        email: authStatus.email,
        displayName: authStatus.display_name,
      },
      org: {
        id: authStatus.organization_id,
        slug: authStatus.org_slug || "acme-corp",
      },
    });

    outputResult(
      {
        authenticated: true,
        user: saved.user,
        org: saved.org,
        apiUrl,
      },
      options,
      () => {
        console.log(`\x1b[32m✔ Logged in successfully!\x1b[0m`);
        console.log(
          `  User: ${saved.user?.displayName || saved.user?.email} (${saved.user?.email})`,
        );
        console.log(`  Org:  ${saved.org?.slug}`);
        console.log(`  API:  ${apiUrl}`);
      },
    );
  } catch (err: any) {
    // If local development / mock token and network is unavailable, save mock user directly
    if (token.startsWith("mock") && err.code === "PLATFORM_NETWORK_ERROR") {
      const saved = saveConfig({
        apiUrl,
        token,
        user: {
          id: `mock-user-${userEmail.split("@")[0]}`,
          email: userEmail,
          displayName: userEmail.split("@")[0],
        },
        org: {
          id: "mock-org-acme",
          slug: "acme-corp",
        },
      });
      outputResult(
        {
          authenticated: true,
          user: saved.user,
          org: saved.org,
          apiUrl,
          offline_mock: true,
        },
        options,
        () => {
          console.log(
            `\x1b[33m✔ Saved development mock session for ${userEmail}\x1b[0m`,
          );
        },
      );
      return;
    }

    outputError(
      new CliError({
        code: "LOGIN_FAILED",
        message: `Failed to authenticate: ${err.message || err}`,
        exitCode: 5,
        hint: "Ensure control-plane service is running and configured correctly.",
      }),
      options,
      5,
    );
  }
}

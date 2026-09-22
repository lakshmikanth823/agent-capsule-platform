/**
 * Automated script to run servers, execute browser verification with Edge,
 * and capture high-resolution screenshots for all 5 screens in Prompt 11.
 */
import { spawn } from "node:child_process";
import path from "node:path";
import fs from "node:fs";
import puppeteer from "puppeteer-core";
import { createEdgeProxyServer } from "../services/edge-proxy/dist/index.js";

const ARTIFACT_DIR =
  "C:/Users/dell/.gemini/antigravity/brain/5e7a2a9c-243c-47e4-844c-fba9a2306259";
const EDGE_PATH =
  "C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe";

async function wait(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

async function checkPort(url, timeout = 15000) {
  const start = Date.now();
  while (Date.now() - start < timeout) {
    try {
      const res = await fetch(url);
      if (res.ok || res.status === 404 || res.status === 200) return true;
    } catch {
      // ignore
    }
    await wait(500);
  }
  return false;
}

async function main() {
  console.log("[*] Starting Control Plane API...");
  const pythonCmd = fs.existsSync(".venv/Scripts/python.exe")
    ? ".venv/Scripts/python.exe"
    : "python";

  const controlPlane = spawn(
    pythonCmd,
    [
      "-m",
      "uvicorn",
      "--app-dir",
      "services/control-plane/src",
      "main:app",
      "--port",
      "8000",
    ],
    { stdio: "inherit", env: { ...process.env, AUTH_PROVIDER: "mock" } },
  );

  console.log("[*] Starting Edge Proxy in-process...");
  process.env.CONTROL_PLANE_URL = "http://127.0.0.1:8000";
  const edgeProxyServer = createEdgeProxyServer({ config: { port: 8080 } });
  await new Promise((resolve) => edgeProxyServer.listen(8080, resolve));
  console.log("[*] Edge Proxy listening on port 8080");

  const cleanup = () => {
    console.log("[*] Shutting down servers...");
    try {
      controlPlane.kill();
      edgeProxyServer.close();
    } catch {
      // ignore
    }
  };

  process.on("SIGINT", cleanup);
  process.on("exit", cleanup);

  console.log("[*] Waiting for Control Plane to be healthy...");
  const cpReady = await checkPort("http://127.0.0.1:8000/health", 15000);
  if (!cpReady) {
    console.error("Control Plane failed to start");
    cleanup();
    process.exit(1);
  }
  console.log("[*] Control Plane is healthy and ready!");

  console.log("[*] Launching headless Microsoft Edge via puppeteer-core...");
  const browser = await puppeteer.launch({
    executablePath: EDGE_PATH,
    headless: "shell",
    defaultViewport: { width: 1440, height: 900 },
    args: [
      "--no-sandbox",
      "--disable-setuid-sandbox",
      "--disable-gpu",
      "--disable-dev-shm-usage",
      "--window-size=1440,900",
    ],
  });

  const page = await browser.newPage();

  const takeScreenshot = async (filename, label) => {
    const filePath = path.join(ARTIFACT_DIR, filename);
    await page.screenshot({ path: filePath, fullPage: false });
    console.log(`[+] Captured: ${label} -> ${filePath}`);
  };

  try {
    // -------------------------------------------------------------
    // Screen 1: Sign-In Screen
    // -------------------------------------------------------------
    console.log(
      "[*] Navigating to http://platform.localhost:8080/ for Screen 1 (Sign-in)...",
    );
    await page.goto("http://platform.localhost:8080/", {
      waitUntil: "networkidle0",
    });

    // Clear token to show sign-in screen
    await page.evaluate(() => {
      localStorage.removeItem("capsule_token");
    });
    await page.reload({ waitUntil: "networkidle0" });
    await wait(800);

    await takeScreenshot("screenshot_01_signin.png", "Screen 1: Sign-in");

    // -------------------------------------------------------------
    // Screen 2: Apps List Screen (Dashboard)
    // -------------------------------------------------------------
    console.log("[*] Signing in as Alice Owner for Screen 2 (Apps List)...");
    await page.evaluate(() => {
      const buttons = Array.from(document.querySelectorAll("button"));
      const alice = buttons.find((b) => b.textContent?.includes("Alice Owner"));
      if (alice) alice.click();
    });

    // Wait for capsules table to appear
    await page.waitForFunction(
      () => document.body.innerText.includes("Leave Tracker"),
      { timeout: 8000 },
    );
    await wait(800);

    await takeScreenshot(
      "screenshot_02_dashboard_apps.png",
      "Screen 2: Dashboard Apps List",
    );

    // -------------------------------------------------------------
    // Screen 3: App Detail Screen (with Logs)
    // -------------------------------------------------------------
    console.log("[*] Navigating to App Detail for Screen 3...");
    await page.evaluate(() => {
      const manageBtns = Array.from(document.querySelectorAll("button"));
      const manage = manageBtns.find((b) => b.textContent?.includes("Manage"));
      if (manage) manage.click();
    });

    await page.waitForFunction(
      () => document.body.innerText.includes("Overview"),
      { timeout: 5000 },
    );
    await wait(500);

    // Switch to Logs tab
    await page.evaluate(() => {
      const tabs = Array.from(document.querySelectorAll("button"));
      const logsTab = tabs.find((b) => b.textContent?.includes("Logs"));
      if (logsTab) logsTab.click();
    });
    await wait(800);

    await takeScreenshot(
      "screenshot_03_app_detail.png",
      "Screen 3: App Detail & Logs",
    );

    // -------------------------------------------------------------
    // Screen 4: Share Dialog with Plain-Language Permission Preview
    // -------------------------------------------------------------
    console.log("[*] Opening Share Dialog for Screen 4...");
    await page.evaluate(() => {
      const shareBtns = Array.from(document.querySelectorAll("button"));
      const share = shareBtns.find((b) => b.textContent?.includes("Share"));
      if (share) share.click();
    });

    await page.waitForFunction(
      () => document.body.innerText.includes("Permission Preview"),
      { timeout: 5000 },
    );
    await wait(1000);

    await takeScreenshot(
      "screenshot_04_share_permission_preview.png",
      "Screen 4: Share & Permission Preview",
    );

    // Close share dialog
    await page.keyboard.press("Escape");
    await wait(500);

    // -------------------------------------------------------------
    // Screen 5: Version History Screen
    // -------------------------------------------------------------
    console.log("[*] Navigating to Version History for Screen 5...");
    await page.evaluate(() => {
      const buttons = Array.from(document.querySelectorAll("button"));
      const historyTab = buttons.find((b) =>
        b.textContent?.includes("Version History"),
      );
      if (historyTab) historyTab.click();
    });
    await wait(800);

    await takeScreenshot(
      "screenshot_05_version_history.png",
      "Screen 5: Version History",
    );

    console.log("[✓] All 5 screenshots successfully captured!");
  } catch (err) {
    console.error("[-] Error during screenshot capture:", err);
  } finally {
    await browser.close();
    cleanup();
  }
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});

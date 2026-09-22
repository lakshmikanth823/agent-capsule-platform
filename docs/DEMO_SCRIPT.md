# 2-Minute Demo: The 1-Click Shareable Agent Tool

> **The Pitch**: _"An AI agent builds an internal tool. The owner clicks 'Share'. A colleague uses the link instantly with enterprise identity, a dedicated database, and zero security risk to the company."_

---

## ⏱️ Timeline (120 Seconds)

```
 0:00 ──────────────── 0:30 ──────────────── 1:00 ──────────────── 1:30 ────────────── 2:00
┌────────────────────────┬────────────────────────┬────────────────────────┬──────────────────┐
│  1. Agent Creates App  │  2. Owner Shares Link  │  3. Colleague Uses App │ 4. Behind Scenes │
│  capsule init & publish│  1-click invite by mail│  instant SSO & data add│ gVisor & audit   │
└────────────────────────┴────────────────────────┴────────────────────────┴──────────────────┘
```

---

## 🎬 Act 1: The AI Agent Builds the Tool (0:00 – 0:30)

**Narrative**:

> _"Meet Alice. She needs a team leave-tracking app for her department. Instead of waiting weeks for internal IT or building a fragile spreadsheet, Alice asks her AI agent to create one."_

1. **Agent command**:
   ```bash
   # Agent initializes the Leave Tracker template
   capsule init --template leave-tracker
   cd leave-tracker

   # Agent validates manifest capabilities (sqlite DB, enterprise identity, zero external egress)
   capsule validate

   # Agent publishes the capsule to the organization
   capsule publish --message "v1.0.0 Leave Tracker"
   ```
2. **Result**:
   - The capsule is packaged into an immutable bundle.
   - It is registered with the platform control plane with subdomain: `https://leave-tracker.apps.company.com`.

---

## 🎬 Act 2: One-Click Sharing (0:30 – 1:00)

**Narrative**:

> _"The app is live immediately. Alice visits `https://leave-tracker.apps.company.com`, tests it, and wants her teammate Bob to start using it."_

1. **Alice shares via CLI or Dashboard**:
   ```bash
   capsule share --app leave-tracker --email bob@company.com --role employee
   ```
   _Or in the Dashboard UI_:
   - Alice navigates to **Capsules** → **Leave Tracker** → **Access & Sharing**.
   - Types `bob@company.com`, selects role **Employee**, and clicks **Grant Access**.
2. **Instant Link**:
   - Alice copies the link: `https://leave-tracker.apps.company.com` and sends it to Bob in Slack.

---

## 🎬 Act 3: Colleague Opens the Link & Uses the App (1:00 – 1:30)

**Narrative**:

> _"Bob clicks the link. No installation, no AWS permissions, no manual database setup. It just works."_

1. **Bob's Experience**:
   - Bob visits `https://leave-tracker.apps.company.com`.
   - Single Sign-On authenticates Bob seamlessly.
   - The platform edge proxy injects signed corporate identity:
     ```json
     {
       "sub": "usr_bob_456",
       "email": "bob@company.com",
       "org_id": "org_acme",
       "roles": ["employee"]
     }
     ```
   - Bob submits a PTO request: `"Family Vacation: Dec 1 – Dec 7"`.
   - The request is saved into the capsule's **dedicated SQLite database**.
2. **Data Isolation Guaranteed**:
   - Bob only sees his own leave requests.
   - Alice (the manager/owner) sees both her own and Bob's requests.
   - Teammates from other departments or external users receive `403 Forbidden`.

---

## 🎬 Act 4: The Enterprise Safety Net (1:30 – 2:00)

**Narrative**:

> _"Why can IT allow this? Because the platform guarantees mathematical security isolation."_

1. **gVisor User-Space Kernel**:
   - Untrusted AI-generated code never executes host system calls directly.
   - Filesystem is read-only except for the capsule's isolated data directory.
2. **Default-Deny Egress Proxy**:
   - The capsule cannot talk to the internet, call internal RFC 1918 subnets, or touch `169.254.169.254` (AWS metadata).
3. **Tamper-Evident Audit Chain**:
   - Every share, deployment, and access event is appended to a SHA-256 hash chain:
     ```bash
     capsule audit verify
     # [OK] All 48 audit chain blocks cryptographically verified (0 tampered)
     ```

---

## 💡 Key Takeaway for YC

> **"Traditional software takes a sprint to build and two weeks of IT approvals to host. With Agent Capsule Platform, an AI agent builds it in 30 seconds, and you share it safely in one click."**

# Software Capsule Platform: Audit System Architecture & Specification (FR-037)

## Overview

The Software Capsule Platform implements a tamper-evident, append-only audit logging system meeting the requirements of **FR-037** and enterprise compliance standards (SOC 2 Type II, ISO 27001). Every security-relevant action, configuration mutation, capability escalation, and access grant across the platform is immutably recorded, cryptographically linked into a per-organization SHA-256 hash chain, and verified against sequence gaps or data tampering.

---

## 1. Cryptographic Hash Chain Architecture

Each audit event within an organization is linked to the previous event through a cryptographic hash chain:

```
+---------------------------+       +---------------------------+       +---------------------------+
| Event #1 (Genesis)        |       | Event #2                  |       | Event #3                  |
| seq: 1                    |       | seq: 2                    |       | seq: 3                    |
| prev_hash: 000...000      | ----> | prev_hash: hash(Event #1) | ----> | prev_hash: hash(Event #2) |
| event_hash: 7a8b...       |       | event_hash: 9c2d...       |       | event_hash: 4e1f...       |
+---------------------------+       +---------------------------+       +---------------------------+
```

### Deterministic Hash Calculation

To ensure that verification produces identical digests across time, systems, and languages, the payload is normalized using canonical JSON serialization (`sort_keys=True, separators=(',', ':')`):

```python
canonical_payload = {
    "action": action,
    "actor_agent": actor_agent,
    "actor_tool": actor_tool,
    "actor_user_id": str(actor_user_id) if actor_user_id else None,
    "app_id": str(app_id) if app_id else None,
    "ip_address": ip_address,
    "metadata": redacted_metadata,
    "occurred_at": format_audit_timestamp(occurred_at),
    "organization_id": str(organization_id) if organization_id else None,
    "outcome": outcome,
    "prev_hash": prev_hash,
    "sequence_number": sequence_number,
    "target_id": str(target_id) if target_id else None,
    "target_type": target_type,
    "user_agent": user_agent,
}
event_hash = sha256(canonical_json(canonical_payload))
```

### Genesis and Sequence Continuity

- **Genesis Event**: The first event recorded for any organization has `sequence_number = 1` and `prev_hash = "0" * 64`.
- **Monotonic Sequencing**: Each subsequent event receives `sequence_number = prev_seq + 1` and `prev_hash = prev_event.event_hash`.
- **Gap Detection**: If an event is deleted from the middle of the chain, the sequence gap is immediately identified during verification.
- **Tamper Detection**: If any field (e.g., action, metadata, timestamp, outcome) is modified in a stored record, the recomputed SHA-256 hash fails to match `event_hash`, pinpointing the exact sequence number that was altered.

---

## 2. Database Immutability & Append-Only Trigger

At the storage layer, the database enforces append-only immutability via a PostgreSQL PL/pgSQL trigger (`trg_prevent_audit_mutation`):

1. **UPDATE Operations**:
   - Strictly prohibited for application users and services. Any attempt to modify an existing audit record raises a database exception:
     `audit_events is append-only: UPDATE operations are strictly prohibited.`
   - Foreign key cascading `ON DELETE SET NULL` operations are checked to ensure core event identifiers and hashes remain unmodified.
2. **DELETE Operations**:
   - Directly executing `DELETE FROM audit_events` is blocked.
   - Deletions are permitted **only** during scheduled retention maintenance when `SET LOCAL capsule.allow_retention_purge = 'on'` has been set in the active transaction by the authorized `AuditRetentionService`.

---

## 3. Retention Enforcement & Checkpoint Anchoring

Organizations can configure their retention policy via `Organization.audit_retention_days` (default: 90 days).

When the scheduled retention service runs:

1. Prunes records where `occurred_at < (now - retention_days)`.
2. Before deleting the records, records an `OrganizationAuditCheckpoint`:
   - `checkpoint_sequence`: The sequence number of the latest deleted event.
   - `checkpoint_hash`: The SHA-256 hash of the latest deleted event.
   - `purged_count`: The number of records pruned.
   - `purged_before`: The retention cutoff timestamp.
3. **Chain Verification Across Retention**:
   When verifying the remaining chain, verification begins with the checkpoint anchor as the expected previous hash, ensuring that pruning does **not** invalidate the integrity of the remaining audit trail.

---

## 4. Multi-Layer Credential Redaction

Before any audit record is persisted, its `metadata` passes through recursive redaction (`redact_audit_metadata`):

- **Key Pattern Redaction**: Keys matching `token`, `secret`, `password`, `key`, `session`, `ticket`, `credential`, `auth`, `jwt`, `cookie`, `bearer`, or `private` are masked with `"[REDACTED]"`. Safe manifest and routing keys (`app_key`, `capability_key`, `key_id`, `idempotency_key`) are allowlisted.
- **Value Pattern Redaction**: String values matching JWT patterns (`eyJ...`), Bearer headers, UUID session tokens (`sess_...`), or API keys (`sk-...`, `ghp_...`, `cap_...`) are detected and replaced with `"[REDACTED]"`.
- **Validation**: Verified by an automated 1,000-event redaction scanner test confirming 0 credential leaks across all scenarios.

---

## 5. Streaming SIEM Webhooks

For organizations utilizing external log aggregators (Datadog, Splunk, Sumo Logic, Elastic):

- **Configuration**: `PUT /v1/organizations/{org_id}/audit/webhook` sets the destination URL and secret token.
- **HMAC-SHA256 Signatures**: Each webhook payload is signed with header `X-Capsule-Signature: sha256=<hex_digest>`.
- **Headers**:
  - `Content-Type: application/json`
  - `X-Capsule-Event: <action>`
  - `X-Capsule-Delivery: <uuid>`
  - `X-Capsule-Signature: sha256=<signature>`

---

## 6. Role-Based Access Matrix

| Role                    | Scope                              | Verify Chain | Enforce Retention | Manage Webhooks |     Export Logs      |
| :---------------------- | :--------------------------------- | :----------: | :---------------: | :-------------: | :------------------: |
| **Organization Owner**  | All events in organization         |     Yes      |        Yes        |       Yes       |         Yes          |
| **Organization Editor** | All events in organization         |     Yes      |        Yes        |       Yes       |         Yes          |
| **App Owner**           | Events for owned applications only |   No (403)   |     No (403)      |    No (403)     | Scoped to owned apps |
| **Non-Owner Member**    | None (403 Forbidden)               |   No (403)   |     No (403)      |    No (403)     |       No (403)       |
| **External Org**        | None (403 Forbidden)               |   No (403)   |     No (403)      |    No (403)     |       No (403)       |

---

## 7. CLI Usage Reference

```bash
# List audit events with filters
capsule audit list --app <appId> --action app.publish --outcome success

# Cryptographically verify the hash chain
capsule audit verify

# Export audit trail to CSV or JSON
capsule audit export --format csv --output ./audit_log.csv
capsule audit export --format json --output ./audit_log.json

# Enforce retention policy
capsule audit retention --enforce
```

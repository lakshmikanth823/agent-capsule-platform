# PROJECT RULES: Software Capsule Platform

## Source of Truth (Highest Priority First)

1. `docs/TRD.md`
2. `docs/api-cli-spec`, `docs/manifest-spec`, `docs/backend-database-schema`
3. `docs/PRD.md`
4. `docs/FRONTEND_DESIGN.md` and `docs/Frontend_Wireframes.*`

> [!IMPORTANT]
> If documents conflict, or something needed is missing, **STOP and ask the user**. Do not invent requirements. Record every answer in `docs/DECISIONS.md` with the date.

---

## Scope

- Build only the phase and task assigned by the user. Do not add features from later phases.
- Respect the non-goals in the PRD.

---

## Security Invariants (NEVER violate, even to make a test pass)

1. **Hostile Code**: Treat all application code as hostile.
2. **Process Isolation**: Application code never runs inside the control-plane process.
3. **No Raw Secrets**: Applications never receive raw secrets, API keys, or long-lived credentials.
4. **Deny Network by Default**: Outbound network access from applications is denied by default.
5. **Origin Separation**: Applications are served from a different origin than the dashboard.
6. **Audit Privileged Actions**: Every privileged action writes an audit event.
7. **No Sensitive Logging**: Never log secrets, tokens, or session identifiers.
8. **Boundary Validation**: Validate all external input at the boundary.
9. **Sandbox Abstraction**: The sandbox is behind a `SandboxDriver` interface. Any development-only driver must be clearly named and documented as **NOT a security boundary**.

---

## Workflow for Every Task

1. Produce an implementation plan first and wait for user approval.
2. Write tests alongside the code. Run them and show results.
3. Keep commits small with clear messages.
4. At the end, give a short summary: what was built, what was skipped, any deviation from the docs, and how to run it.

---

## Code Quality

- Use the language and tooling that `docs/TRD.md` specifies.
- Typed code, linting, no dead code, configuration via environment variables.
- Provide `.env.example`. Never commit secrets.
- Return structured errors exactly as defined in the API spec.

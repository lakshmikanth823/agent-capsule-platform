# Review Protocols Between Prompts and Phases

## After Every Prompt (New Review Task)

Review the last changes against `docs/TRD.md`, the API/CLI spec (`docs/api-cli-spec/`), and the PRD (`docs/PRD.md`).
List:

1. **Deviations**: Any deviation from the docs
2. **Security Violations**: Any violation of the security invariants in the project rules
3. **Missing Tests**: Missing unit, integration, or contract tests
4. **Hard-coded Values**: Anything hard-coded that should be configuration

> [!IMPORTANT]
> **Do not change code during this review. Only report findings.**

---

## After Each Phase (New Review Task)

Act as a senior security engineer doing a pre-release review of this repository.
Inspect for:

- Authentication and authorization bypasses
- Injection vulnerabilities (SQL, command, template, etc.)
- Unsafe deserialization
- Secrets in code or logs
- Missing input validation
- Race conditions in sharing and rollback
- Any place where application code could influence the control plane

> [!IMPORTANT]
> **Write findings to `docs/SECURITY_REVIEW_<phase>.md` with severity and suggested fixes. Do not change code.**

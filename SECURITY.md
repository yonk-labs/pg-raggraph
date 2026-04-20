# Security Policy

## Supported versions

pg-raggraph is pre-1.0. Only the latest released version on `main` receives security fixes. Pinned older versions may be updated on a case-by-case basis if a CVE is severe and widely deployed.

## Reporting a vulnerability

**Please do not file public GitHub issues for security vulnerabilities.**

Instead, report privately by:

1. Emailing **matt@theyonk.com** with subject `[security] pg-raggraph` and a description of the issue, steps to reproduce, and the affected version or commit SHA.
2. Or using GitHub's [private vulnerability reporting](https://docs.github.com/en/code-security/security-advisories/guidance-on-reporting-and-writing-information-about-vulnerabilities/privately-reporting-a-security-vulnerability) on this repository.

You should receive an acknowledgment within 3 business days. If you don't, please follow up.

## What to include

- Affected version / commit SHA
- Reproduction steps or a proof-of-concept
- Impact assessment — what can an attacker do?
- Any suggested mitigation

## What happens next

- We triage within 7 days and confirm whether the report is in scope.
- A fix is prepared on a private branch. Timeline depends on severity — critical bugs get same-week attention; lower-severity ones are bundled with the next release.
- A security advisory is published alongside the fix, crediting the reporter unless anonymity is requested.

## Scope

**In scope:**
- SQL injection, authentication bypass, authorization issues in the library or example server.
- Remote code execution via crafted documents, configs, or LLM responses.
- Leaked credentials in shipped code or defaults.
- Dependency vulnerabilities where the vulnerable code path is reachable from pg-raggraph APIs.

**Out of scope:**
- Vulnerabilities in dependencies where the affected path is not reachable from pg-raggraph.
- Self-hosted deployments that expose the example FastAPI server publicly without adding their own auth layer — that's a deployment issue, not a library bug.
- Issues in the benchmarks/ subtree that only affect test runs.

## Safe harbor

Good-faith security research on your own deployments or local installations is welcome. Please do not attempt to access data you don't own, degrade service for others, or exfiltrate credentials from accounts that aren't yours.

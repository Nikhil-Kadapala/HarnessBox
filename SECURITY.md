# Security Policy

## Reporting a Vulnerability

If you discover a security vulnerability in HarnessBox, please report it responsibly.

**Do NOT open a public GitHub issue for security vulnerabilities.**

Instead, email: nikhil@resalign.com

Include:
- Description of the vulnerability
- Steps to reproduce
- Potential impact
- Suggested fix (if you have one)

We will respond within 48 hours and work with you to understand and fix the issue before any public disclosure.

## Scope

HarnessBox is a security-focused SDK. The following are in scope:

- Credential exfiltration from sandboxes (env vars, git tokens, API keys)
- Bypass of SecurityPolicy deny rules
- Bypass of PreToolUse hook guard
- Agent escape from sandbox isolation
- Token leakage via git config, logs, or error messages

## Supported Versions

| Version | Supported |
|---------|-----------|
| 0.1.x   | Yes       |

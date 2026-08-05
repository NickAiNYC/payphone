# Security Policy

## Supported Versions

Only the latest release version on the `main` branch is actively supported with security updates.

| Version | Supported |
| ------- | --------- |
| 0.1.x   | Yes       |
| < 0.1   | No        |

---

## Reporting a Vulnerability

**DO NOT open a public issue on GitHub for security vulnerabilities.**

If you discover a vulnerability, especially regarding:
* Host filesystem leakage via WebRTC streams
* Bypasses in the `ConsentManager` check loops
* Flaws in private key custody (NIP-44 or local storage origins)
* Decryption exploits on local call recordings

Please email your report to **security@hermes-buzz-agent.example**.

### Report Elements
Please include:
1. Steps to reproduce the issue.
2. A proof-of-concept payload or execution script.
3. The potential impact of the exploit.

We will review your submission and respond within 48 hours.

---

## Key Custody Rules
1. **Never** write keys to log streams or console logs.
2. **Never** include private keys in docker images or commit them to source control.
3. Keep IndexedDB origins isolated and restrict external script imports to prevent XSS-based key extraction.

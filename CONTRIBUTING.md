# Contributing to Hermes × Buzz

We welcome contributions to the Hermes × Buzz ecosystem! Follow this guide to configure your workspace, run checks, and submit code changes.

---

## 1. Setting Up Your Development Environment

1. Clone the repository.
2. Initialize and configure local settings:
   ```bash
   cp .env.example .env
   ```
3. Boot the complete developer stack:
   ```bash
   make dev
   ```

---

## 2. Running Automated Tests

We require all checks to pass locally prior to submittal:
* **Run Unit & Integration Tests**:
  ```bash
  make test
  ```
* **Verify Latency Budgets & Performance Suite**:
  ```bash
  make test-perf
  ```

---

## 3. Code Standards & Style

* **Python Backend**: Code must follow PEP 8 styling conventions. We enforce auto-formatting via `black`:
  ```bash
  black hermes-agent/
  ```
* **TypeScript Frontend**: Ensure components compile with no static typing warnings:
  ```bash
  cd buzz && npm run build
  ```

---

## 4. Development & Pull Request (PR) Workflow

1. Fork the repository and create your feature branch: `git checkout -b feature/amazing-feature`.
2. Commit your modifications with structured prefixes:
   * `feat: ...` for additions.
   * `fix: ...` for bug corrections.
   * `docs: ...` for documentation updates.
3. Verify that your tests pass.
4. Open a Pull Request targeting the `main` branch.

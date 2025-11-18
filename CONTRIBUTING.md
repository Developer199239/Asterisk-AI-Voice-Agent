# Contributing Guide

Thanks for your interest in contributing to the Asterisk AI Voice Agent!

## New to the project? Start here

If you’re setting up the project for the first time, read the Developer Onboarding guide before diving into branches and PRs:

- `docs/DEVELOPER_ONBOARDING.md`

It walks you through:
- Choosing an AI-powered IDE (for example Windsurf via the referral link in that doc, or any IDE of your choice).
- Cloning the repo, running `./install.sh`, and wiring the project to your Asterisk/FreePBX server.
- Using the `agent` CLI and AVA (the project manager persona) to plan and test your first changes.

## Branches and workflow

- Active branches:
  - `develop`: feature work and ongoing development
  - `staging`: release prep and GA readiness (PRs typically target here)
  - `main`: stable releases

Recommended flow:

- Fork the repository and create a feature branch from `develop`.
- Make your changes in small, focused commits.
- Open a Pull Request (PR) against `staging` (preferred) or `develop` with a clear description and testing notes.
- A maintainer will review, run CI/manual checks, and merge. Releases are promoted from `staging` to `main`.

## Development setup

- Docker and Docker Compose are recommended for a consistent dev environment.
- Quick start:

  ```bash
  git clone https://github.com/hkjarral/Asterisk-AI-Voice-Agent.git
  cd Asterisk-AI-Voice-Agent
  ./install.sh   # guided setup; or follow README for manual steps
  ```

- For Local/Hybrid profiles, run `make model-setup` when prompted to download models.

## Code style & quality

- Python: target 3.10+. Keep code readable and well-logged.
- Prefer small, composable functions and clear error handling.
- Add or update documentation where behavior changes (README, docs/).

## Tests & verification

- Start services:

  ```bash
  docker-compose up --build -d
  docker-compose logs -f ai-engine
  ```

- Verify health:

  ```bash
  curl http://127.0.0.1:15000/health
  ```

- Optional checks are available via the Makefile (e.g., `make test-health`).

## Commit messages

- Use clear, descriptive messages (Conventional Commits encouraged but not required).
- Reference related issues where applicable.

## Reporting issues

- Use GitHub Issues with steps to reproduce, logs (if possible), and environment details.

Thanks again for helping improve the project!

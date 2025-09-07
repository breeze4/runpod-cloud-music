# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

MusicGen batch processing system for RunPod L40S GPU pods. Processes text prompts to generate audio files using Meta's MusicGen model and uploads results to S3.

**Development Environment**: Windows machine with Python deployment scripts for cross-platform compatibility.

## Architecture

- **Input**: `prompts.txt` with format: `PROMPT ; DURATION ; FILENAME`
- **Processing**: Worker validates AWS environment, downloads model, generates audio
- **Output**: WAV files uploaded to S3 with completion report

## Essential Commands

### Environment Variables

**Local `.env` file** (copy from `.env.template`):
```bash
# RunPod connection
RUNPOD_HOST=your-pod-hostname
RUNPOD_USER=root

# AWS S3 configuration (automatically deployed to pod)
MUSICGEN_S3_BUCKET=your-bucket-name
AWS_DEFAULT_REGION=us-east-1
AWS_ACCESS_KEY_ID=your-access-key
AWS_SECRET_ACCESS_KEY=your-secret-key
```

**Automated Deployment:**
- Deployment script reads local `.env` file
- Automatically configures pod environment variables via SSH
- Worker uses boto3 automatic credential detection

### 4-Phase Deployment
```cmd
# Phase 1: Deploy source code
uv run deploy/deploy_code.py

# Phase 2: Install dependencies and configure environment
uv run deploy/install_dependencies.py

# Phase 3: Validate environment (AWS, GPU, dependencies)
uv run deploy/validate_environment.py

# Phase 4: Run worker with monitoring
uv run deploy/run_worker.py
```

### Worker Management
```cmd
# Start worker and monitor startup
uv run deploy/run_worker.py

# Monitor worker logs in real-time
uv run deploy/run_worker.py logs

# Check worker status
uv run deploy/run_worker.py status

# Stop worker
uv run deploy/run_worker.py stop
```

### Complete Deployment (All Phases)
```cmd
# Full deployment and environment setup (run once or after major changes)
uv run deploy/deploy_to_pod.py

# Quick worker code sync and restart (for development iteration)
uv run deploy/sync_and_run_worker.py
```

## Dependencies
```bash
uv add boto3 torch transformers soundfile numpy python-dotenv
```

## Technical Details

### MusicGen Model
- **facebook/musicgen-large** (12GB, cached after first run)
- 32kHz WAV output
- ≤30s single pass, >30s chunked generation

### File Handling
- Deterministic naming: `{base_name}_{hash8}.wav`
- Idempotent: skips if file exists in S3
- Per-job error isolation

## RunPod Deployment

### Hardware Requirements
- **RunPod L40S Pod**: NVIDIA L40S (48GB VRAM)
- **RAM**: 32GB+
- **Storage**: 150GB+ for model cache (large model is 12GB)

### Workflow
1. Create `.env` file with RUNPOD_HOST and AWS credentials
2. Phase-based deployment:
   - `uv run deploy/deploy_code.py` (upload source code)
   - `uv run deploy/install_dependencies.py` (setup environment)
   - `uv run deploy/validate_environment.py` (verify setup)
   - `uv run deploy/run_worker.py` (run and monitor worker)
3. Or full deployment: `uv run deploy/deploy_to_pod.py` (all phases combined)
4. Quick iteration: `uv run deploy/sync_and_run_worker.py` (code sync and restart)

## Important Restrictions

**NEVER execute these commands:**
- `git` commands (git add, git commit, git push, etc.) - User handles all git operations
- `runpod` CLI commands - User manages RunPod deployments
- Deployment scripts (`uv run deploy/*.py`) - User runs scripts manually
- `ssh` or remote execution commands - User handles all RunPod pod connections

Claude should only read, edit, and analyze code. All deployment, version control, and script execution is handled by the user on Windows.

Do NOT use Emojis in any code, scripts, docs, etc. Just do not use emojis they are trouble for character encoding.
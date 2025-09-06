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

### Deployment
```cmd
python deploy/deploy_to_pod.py
```

### Monitoring
```cmd
# Monitor worker logs from Windows machine
python deploy/monitor_logs.py

# Monitor system logs from Windows machine
python deploy/monitor_system.py

# Check GPU utilization
python deploy/check_gpu.py
```

## Dependencies
```bash
uv add boto3 torch transformers soundfile numpy python-dotenv
```

## Technical Details

### MusicGen Model
- **facebook/musicgen-medium** (6GB, cached after first run)
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
- **Storage**: 100GB+ for model cache

### Workflow
1. Create `.env` file with RUNPOD_HOST and AWS credentials
2. Deploy and monitor: `python deploy/deploy_and_monitor.py` (configures pod automatically)
3. Or deploy separately: `python deploy/deploy_to_pod.py` (uploads code + sets environment)
4. Monitor logs: `python deploy/monitor_logs.py`

## Important Restrictions

**NEVER execute these commands:**
- `git` commands (git add, git commit, git push, etc.) - User handles all git operations
- `runpod` CLI commands - User manages RunPod deployments
- Deployment Python scripts (`python deploy/*.py`) - User runs scripts manually
- `ssh` or remote execution commands - User handles all RunPod pod connections

Claude should only read, edit, and analyze code. All deployment, version control, and script execution is handled by the user on Windows.
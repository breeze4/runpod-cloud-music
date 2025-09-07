# MusicGen RunPod Deployment

Batch music generation using Meta's MusicGen model on RunPod L40S GPU pods.

## Quick Start

1. **Setup Environment**
   ```cmd
   copy .env.template .env
   # Edit .env with your credentials
   ```

2. **Deploy and Monitor**
   ```cmd
   python deploy/deploy_and_monitor.py
   ```

## Setup Requirements

### Local Development Setup

1. **Install UV (Python Package Manager)**
   
   **Windows:**
   ```powershell
   powershell -c "irm https://astral.sh/uv/install.ps1 | iex"
   ```
   
   **Linux/macOS:**
   ```bash
   curl -LsSf https://astral.sh/uv/install.sh | sh
   ```

2. **Install Dependencies**
   ```bash
   uv sync
   ```


### Environment Variables

Create a `.env` file in the project root with these variables:

```bash
# RunPod Connection
RUNPOD_HOST=your-pod-hostname
RUNPOD_USER=root

# AWS S3 Configuration  
MUSICGEN_S3_BUCKET=your-bucket-name
AWS_DEFAULT_REGION=us-east-1
AWS_ACCESS_KEY_ID=your-access-key
AWS_SECRET_ACCESS_KEY=your-secret-key
```

### Where to Get Credentials

**RunPod Connection:**
- `RUNPOD_HOST`: Get from RunPod console → Your Pod → Connect → SSH
- `RUNPOD_USER`: Usually `root` for RunPod pods

**AWS S3:**
- `MUSICGEN_S3_BUCKET`: Your S3 bucket name for storing generated audio
- `AWS_DEFAULT_REGION`: AWS region where your bucket is located
- `AWS_ACCESS_KEY_ID` & `AWS_SECRET_ACCESS_KEY`: From AWS IAM console

**Automated Pod Setup:**
The deployment script automatically configures the pod environment:
- Reads credentials from your local `.env` file
- SSHs to the pod and sets environment variables  
- No manual RunPod console configuration required
- Environment variables persist for the pod session

### Dependencies

```cmd
uv add boto3 torch transformers soundfile numpy python-dotenv
```

## Main Workflows

### 1. Phase-by-Phase Deployment (Recommended for First Time)

Run each phase individually for better control and debugging:

```cmd
# Phase 1: Deploy source code to pod
uv run deploy/deploy_code.py

# Phase 2: Install dependencies and configure environment  
uv run deploy/install_dependencies.py

# Phase 3: Validate environment (AWS, GPU, dependencies)
uv run deploy/validate_environment.py

# Phase 4: Run worker with monitoring
uv run deploy/run_worker.py
```

**Use this workflow when:**
- Setting up for the first time
- Need to debug specific deployment issues
- Want to verify each step independently

### 2. Complete Deployment (All Phases)

Single command that runs all phases automatically:

```cmd
uv run deploy/deploy_to_pod.py
```

**Use this workflow when:**
- Environment is working and you want full reset
- Major changes that require complete redeployment

### 3. Worker Development Iteration (Fastest)

For iterating on worker code without reinstalling environment:

```cmd
uv run deploy/sync_and_run_worker.py
```

**Use this workflow when:**
- Only worker code (`src/worker.py`) has changed
- Pod environment is already set up correctly
- Want fastest deployment cycle

This syncs only source code and restarts the worker - no environment reinstall.

### 4. Worker Management

Control and monitor running workers:

```cmd
# Start worker and monitor startup
uv run deploy/run_worker.py

# View real-time logs
uv run deploy/run_worker.py logs

# Check worker status
uv run deploy/run_worker.py status  

# Stop worker
uv run deploy/run_worker.py stop
```

### 5. Environment Validation Only

Verify environment without running worker:

```cmd
uv run deploy/validate_environment.py
```

**Use this to check:**
- AWS credentials and S3 access
- GPU and PyTorch integration  
- All Python dependencies

## Input Format

Edit `prompts.txt` with your music generation requests:

```
# Format: PROMPT_TEXT ; DURATION_IN_SECONDS ; FILE_NAME
upbeat electronic dance music with heavy bass ; 30 ; dance_test
cinematic orchestral music with epic drums ; 45 ; cinematic_short
relaxing acoustic guitar melody ; 60 ; acoustic_relax
```

## Output

Generated audio files are uploaded to your S3 bucket with:
- Deterministic filenames: `{base_name}_{hash8}.wav`
- 32kHz WAV format
- Completion report showing all files created and generation times

## Troubleshooting

**Connection Issues:**
- Verify RUNPOD_HOST is correct (check RunPod console)
- Ensure pod is running and SSH is enabled
- Test SSH manually: `ssh root@your-pod-hostname`

**S3 Issues:**
- Verify AWS credentials have S3 write permissions for your bucket
- Check bucket exists and is in the correct region
- Deployment script automatically sets AWS environment variables on pod
- Worker uses boto3 environment variable detection
- Test S3 access: worker validates S3 connectivity at startup

**Generation Issues:**
- Monitor logs with `uv run deploy/run_worker.py logs`
- Validate environment with `uv run deploy/validate_environment.py`
- Verify model downloads successfully (12GB for musicgen-large)

## Development Workflow Summary

**First-time setup (complete):**
1. `uv run deploy/deploy_code.py`
2. `uv run deploy/install_dependencies.py` 
3. `uv run deploy/validate_environment.py`
4. `uv run deploy/run_worker.py`

**Worker code iteration (fast):**
1. Edit `src/worker.py` locally
2. `uv run deploy/sync_and_run_worker.py`

**Environment changes (medium):**
1. `uv run deploy/install_dependencies.py`
2. `uv run deploy/validate_environment.py`
3. `uv run deploy/run_worker.py`

**Nuclear option (slow):**
1. `uv run deploy/deploy_to_pod.py` (all phases)
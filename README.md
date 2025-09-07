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

### 1. Deploy + Run + Monitor (Recommended)

Single command that deploys code, starts the worker, and shows live logs:

```cmd
uv run python deploy/deploy_and_monitor.py
```

This will:
- Deploy your code to the RunPod pod
- Start the MusicGen worker
- Stream worker logs to your terminal
- Show completion report when done

### 2. Deploy Only

Deploy code without running or monitoring:

```cmd
uv run python deploy/deploy_to_pod.py
```

Then manually SSH to pod and run:
```bash
ssh root@your-pod-hostname -p YOUR_PORT
cd /workspace && uv run src/worker.py
```

### 3. Quick Development Iteration

For development iteration when the pod environment is already set up:

```cmd
uv run python deploy/sync_and_run_worker.py
```

This syncs code changes to the pod and restarts the worker without full environment setup.

### 4. Monitor Only

Monitor logs from a worker that's already running:

```cmd
# Worker logs (recommended)
uv run python deploy/monitor_logs.py

# System logs
uv run python deploy/monitor_system.py

# Pod environment check
uv run python deploy/check_pod.py

# Validate deployment (AWS, GPU, dependencies)
uv run python deploy/validate_deployment.py
```

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
- Monitor logs with `python deploy/monitor_logs.py`
- Validate deployment with `python deploy/validate_deployment.py`
- Verify model downloads successfully (12GB for musicgen-large)
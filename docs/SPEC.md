# MusicGen RunPod Deployment Specification

MusicGen batch processing system for RunPod L40S GPU pods.

## Workflow

1. Deployment script uploads code and configures AWS environment on RunPod pod
2. Worker validates AWS environment variables and S3 connectivity
3. Worker downloads MusicGen model (6GB, cached after first run)
4. Worker processes prompts.txt sequentially
5. Generated audio uploaded to S3 using boto3 environment variables
6. Summary report with files created and generation times

## Requirements

### Environment Variables

**Local `.env` file** (deployment script configuration):
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

**Automated Pod Configuration:**
- Deployment script reads local `.env` file
- SSHs to pod and sets AWS environment variables
- Worker uses boto3's automatic environment variable detection
- No manual RunPod console configuration required

### Dependencies
```bash
uv add boto3 torch transformers soundfile numpy python-dotenv
```

### Input Format (`prompts.txt`)
```
# Format: PROMPT_TEXT ; DURATION_IN_SECONDS ; FILE_NAME
upbeat electronic dance music with heavy bass ; 30 ; dance_test
cinematic orchestral music with epic drums ; 45 ; cinematic_short
```

## Technical Details

### Model
- **facebook/musicgen-medium** (6GB download, cached after first run)
- Audio generation: ≤30s single pass, >30s chunked in 30s segments
- Output: 32kHz WAV files

### File Naming
- Deterministic: `{base_name}_{hash8}.wav`
- Hash from: prompt + duration + filename
- Idempotent: skips if file exists in S3

### Monitoring
```cmd
# Monitor worker logs from Windows machine
python deploy/monitor_logs.py

# Monitor system logs from Windows machine  
python deploy/monitor_system.py

# Check GPU utilization
python deploy/check_gpu.py
```

## RunPod Deployment

### Pod Configuration
- **GPU**: NVIDIA L40S (48GB VRAM)
- **RAM**: 32GB+ 
- **Storage**: 100GB+ for model cache
- **Base**: Python 3.8+ container

### Deployment Steps
1. Create `.env` file with RUNPOD_HOST and AWS credentials
2. Deploy: `python deploy/deploy_to_pod.py` (uploads code + configures environment)
3. Monitor: `python deploy/monitor_logs.py`
4. Execute: SSH to pod and run `cd /workspace && uv run src/worker.py`

### Monitoring Commands
```cmd
# Deploy and monitor in one command
python deploy/deploy_and_monitor.py

# Monitor worker logs live
python deploy/monitor_logs.py

# Monitor system logs live
python deploy/monitor_system.py
```
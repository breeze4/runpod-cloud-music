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

### 4-Phase Deployment Workflow

#### Phase 1: Deploy Code
```cmd
uv run deploy/deploy_code.py
```
- Upload source code, prompts.txt, and pyproject.toml to pod
- Basic connectivity verification
- No dependency installation or environment setup

#### Phase 2: Install Dependencies
```cmd
uv run deploy/install_dependencies.py
```
- Install uv package manager
- Set up Python environment with required packages
- Configure AWS environment variables
- Create S3 bucket if needed

#### Phase 3: Validate Environment
```cmd
uv run deploy/validate_environment.py
```
- Check AWS environment variables and S3 connectivity
- Verify GPU/PyTorch integration
- Test all dependencies
- Comprehensive environment validation

#### Phase 4: Run Worker
```cmd
# Start worker
uv run deploy/run_worker.py

# Monitor worker
uv run deploy/run_worker.py logs

# Check status
uv run deploy/run_worker.py status

# Stop worker
uv run deploy/run_worker.py stop
```

### Complete Deployment (All Phases)
```cmd
# Original monolithic script (still available)
uv run deploy/deploy_to_pod.py

# Quick code sync and restart (for development)
uv run deploy/sync_and_run_worker.py
```

### Prerequisites
1. Create `.env` file with RUNPOD_HOST and AWS credentials
2. Ensure SSH keys are configured for RunPod access
3. Have prompts.txt ready for worker processing
# RunPod L40S Deployment Guide

Complete step-by-step guide for deploying MusicGen on RunPod L40S GPU pods.

## Prerequisites

### Hardware Requirements
- **RunPod L40S Pod**: NVIDIA L40S GPU (48GB VRAM)
- **RAM**: 32GB+ recommended
- **Storage**: 100GB+ for model cache and generated files
- **Network**: Stable internet connection for model download

### Software Requirements
- **Local Machine**: Windows/Linux/macOS with Python 3.8+
- **SSH Client**: OpenSSH or compatible
- **Git**: For cloning the repository
- **UV Package Manager**: For dependency management (recommended)

### Account Setup
- **RunPod Account**: With sufficient credits for L40S pod
- **AWS Account**: With S3 bucket and IAM credentials
- **SSH Key**: Added to RunPod account

## Step 1: Pod Setup

### 1.1 Create RunPod L40S Pod

1. **Log into RunPod Console**
   - Go to [runpod.io](https://runpod.io) and sign in
   - Navigate to "Pods" section

2. **Select GPU Configuration**
   - Click "Deploy" or "New Pod"
   - Filter by GPU type: **L40S** (48GB VRAM)
   - Select a pod with 32GB+ RAM

3. **Configure Pod Template**
   - **Container Image**: `runpod/pytorch:2.0.1-py3.10-cuda11.8.0-devel-ubuntu22.04`
   - **Container Disk**: 100GB minimum
   - **Volume**: Optional persistent storage
   - **Expose Ports**: Enable SSH (port 22)

4. **Deploy Pod**
   - Click "Deploy" and wait for pod to start
   - Status should show "Running"
   - Note the pod hostname (e.g., `abc123-xyz.ssh.runpod.io`)

### 1.2 Test SSH Connection

1. **Get SSH Connection Details**
   - In RunPod console, click on your pod
   - Go to "Connect" → "SSH"
   - Copy the SSH command (e.g., `ssh root@abc123-xyz.ssh.runpod.io`)

2. **Test Connection**
   ```bash
   ssh root@your-pod-hostname
   ```
   - Should connect without password (using SSH key)
   - If prompted for password, check SSH key setup

## Step 2: Local Environment Setup

### 2.1 Clone Repository

```bash
git clone https://github.com/your-repo/runpod-cloud-music.git
cd runpod-cloud-music
```

### 2.2 Install Dependencies

**Install UV (Recommended):**

Windows:
```powershell
powershell -c "irm https://astral.sh/uv/install.ps1 | iex"
```

Linux/macOS:
```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

**Install Project Dependencies:**
```bash
uv sync
```

**Alternative (using pip):**
```bash
pip install python-dotenv boto3 torch transformers soundfile numpy
```

### 2.3 Create Environment File

1. **Copy Template**
   ```bash
   cp .env.template .env
   ```

2. **Edit .env File**
   ```bash
   # RunPod Connection
   RUNPOD_HOST=your-pod-hostname-here        # e.g., abc123-xyz.ssh.runpod.io
   RUNPOD_USER=root

   # AWS S3 Configuration  
   MUSICGEN_S3_BUCKET=your-s3-bucket-name   # Your S3 bucket
   AWS_DEFAULT_REGION=us-east-1             # Your bucket region
   AWS_ACCESS_KEY_ID=your-access-key        # AWS access key
   AWS_SECRET_ACCESS_KEY=your-secret-key    # AWS secret key
   ```

### 2.4 Verify Configuration

1. **Test SSH Connection**
   ```bash
   uv run python deploy/check_gpu.py
   ```
   - Should show GPU information and PyTorch compatibility

2. **Test AWS Credentials**
   - Use AWS CLI or console to verify S3 bucket access
   - Ensure IAM user has S3 read/write permissions

## Step 3: Create Music Prompts

### 3.1 Edit prompts.txt

Create or edit `prompts.txt` with your music generation requests:

```
# Format: PROMPT_TEXT ; DURATION_IN_SECONDS ; FILE_NAME
upbeat electronic dance music with heavy bass ; 30 ; dance_track
cinematic orchestral music with epic drums ; 45 ; orchestral_epic  
relaxing acoustic guitar melody ; 60 ; acoustic_chill
jazz piano solo with smooth saxophone ; 30 ; jazz_smooth
```

### 3.2 Prompt Guidelines

- **Duration**: 10-120 seconds (longer durations use chunked generation)
- **Prompts**: Descriptive text describing the desired music style
- **Filenames**: Unique names without spaces or special characters
- **Format**: Each line follows exact format with semicolon separators

## Step 4: Deployment Options

### Option A: One-Command Deploy and Monitor (Recommended)

**Single command that deploys, starts worker, and shows live logs:**

```bash
uv run python deploy/deploy_and_monitor.py
```

This will:
- Deploy code to RunPod pod
- Configure AWS environment automatically  
- Start MusicGen worker
- Stream logs in real-time
- Show completion summary

### Option B: Step-by-Step Deployment

1. **Deploy Code Only**
   ```bash
   python deploy/deploy_to_pod.py
   ```

2. **Monitor Logs** (in separate terminal)
   ```bash
   python deploy/monitor_logs.py
   ```

3. **Start Worker** (SSH to pod)
   ```bash
   ssh root@your-pod-hostname
   cd /workspace
   source setup_env.sh
   uv run src/worker.py
   ```

### Option C: Manual SSH Deployment

1. **SSH to Pod**
   ```bash
   ssh root@your-pod-hostname
   ```

2. **Install UV**
   ```bash
   curl -LsSf https://astral.sh/uv/install.sh | sh
   export PATH="$HOME/.cargo/bin:$PATH"
   ```

3. **Clone Repository**
   ```bash
   git clone https://github.com/your-repo/runpod-cloud-music.git
   cd runpod-cloud-music
   ```

4. **Set Environment Variables**
   ```bash
   export AWS_ACCESS_KEY_ID="your-access-key"
   export AWS_SECRET_ACCESS_KEY="your-secret-key"  
   export AWS_DEFAULT_REGION="us-east-1"
   export MUSICGEN_S3_BUCKET="your-bucket-name"
   ```

5. **Install Dependencies and Run**
   ```bash
   uv sync
   uv run src/worker.py
   ```

## Step 5: Monitoring and Management

### 5.1 Real-Time Monitoring

**Worker Logs:**
```bash
python deploy/monitor_logs.py
```

**System Resources:**
```bash
python deploy/monitor_system.py
```

**GPU Status:**
```bash
python deploy/check_gpu.py
```

### 5.2 Check Progress

**SSH to Pod and Check Status:**
```bash
ssh root@your-pod-hostname
cd /workspace

# Check worker logs
tail -f musicgen-worker.log

# Check generated files
ls -la *.wav

# Check cost reports  
ls -la *.csv
```

## Step 6: Results and Output

### 6.1 Generated Files

**S3 Bucket Contents:**
- `filename_hash.wav` - Generated audio files
- `cost_report_latest.csv` - Cost and timing report
- `cost_report_YYYYMMDD_HHMMSS.csv` - Timestamped reports

**File Naming:**
- Format: `{base_name}_{hash8}.wav`
- Hash ensures idempotency (same prompt = same filename)
- Example: `dance_track_a1b2c3d4.wav`

### 6.2 Completion Report

The worker generates a detailed completion report showing:
- All S3 files created with generation times
- Performance metrics and efficiency ratios
- Cost breakdown per file
- Success/failure summary
- Total processing statistics

### 6.3 Cost Tracking

**CSV Report Fields:**
- `s3_filename` - Output filename
- `prompt` - Generation prompt  
- `requested_duration_s` - Target duration
- `generation_time_s` - Actual processing time
- `estimated_cost_usd` - Cost estimate based on instance pricing

## Step 7: Cleanup

### 7.1 Stop Worker

**If running via deploy_and_monitor.py:**
- Press `Ctrl+C` to stop monitoring
- Worker process will complete current job and exit

**If running manually:**
```bash
ssh root@your-pod-hostname
pkill -f worker.py
```

### 7.2 Pod Management

**Pause Pod:** In RunPod console, click "Stop" to pause billing
**Terminate Pod:** Click "Terminate" to permanently delete pod
**Save Data:** Download any files before termination

## Step 8: Verification and Testing

### 8.1 Test Small Batch

1. **Create Test Prompts**
   ```
   simple piano melody ; 15 ; test_piano
   electronic beat ; 10 ; test_electronic
   ```

2. **Deploy and Run**
   ```bash
   python deploy/deploy_and_monitor.py
   ```

3. **Verify Results**
   - Check S3 bucket for generated files
   - Download and play audio files
   - Review cost report

### 8.2 Performance Benchmarks

**Expected Performance (L40S):**
- **Model Loading**: 30-60 seconds (cached) / 5-15 minutes (first run)
- **Generation Speed**: 0.3-0.5x real-time for short clips
- **Memory Usage**: ~15-25GB GPU VRAM during generation
- **Cost**: ~$0.50-1.00 per hour depending on region

## Summary

This deployment guide provides multiple pathways for getting MusicGen running on RunPod L40S:

1. **Quick Start**: Use `deploy_and_monitor.py` for automated deployment
2. **Manual Control**: Use individual scripts for step-by-step deployment  
3. **SSH Manual**: Direct SSH access for advanced users

The system includes comprehensive validation, monitoring, and reporting to ensure successful music generation with full cost tracking and S3 storage integration.

## Next Steps

- Review troubleshooting section for common issues
- Customize prompts for your specific music generation needs
- Scale up with larger prompt batches
- Set up automated workflows for regular generation jobs
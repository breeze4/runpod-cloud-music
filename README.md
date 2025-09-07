# MusicGen RunPod Deployment

Batch music generation using Meta's MusicGen model on RunPod L40S GPU pods.

## Quick Start

1. **Setup Environment**
   ```cmd
   copy .env.template .env
   # Edit .env with your credentials
   ```

## Setup 

Requires `uv` to run the `deploy/` code

Install: `uv sync`

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

## Main Workflows

**First-time setup (complete):**
1. `uv run deploy/deploy_code.py`
2. `uv run deploy/install_dependencies.py` 
3. `uv run deploy/validate_environment.py`
4. `uv run deploy/run_worker.py`

**Worker code iteration (fast):**
1. Edit `src/worker.py` locally
2. `uv run deploy/deploy_code.py && uv run deploy/run_worker.py`

## Technical Details

### Model
- **facebook/musicgen-large** (8GB download, cached after first run)
- Audio generation: ≤30s single pass, >30s chunked in 30s segments
- Output: 32kHz WAV files

### Input Format

Edit `prompts.txt` with your music generation requests:

```
# Format: PROMPT_TEXT ; DURATION_IN_SECONDS ; FILE_NAME
upbeat electronic dance music with heavy bass ; 30 ; dance_test
cinematic orchestral music with epic drums ; 45 ; cinematic_short
relaxing acoustic guitar melody ; 60 ; acoustic_relax
```

## Output
- Uploaded to S3 bucket, with a directory for this run of the prompt
- Deterministic: `{base_name}_{hash8}.wav`
- 32kHz WAV format

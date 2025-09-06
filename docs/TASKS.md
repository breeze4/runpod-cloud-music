# RunPod L40S Deployment Tasks

Implementation tasks for MusicGen RunPod deployment.

## Workflow
1. Set environment variables in RunPod pod configuration
2. Deploy code to running pod with uv dependency management
3. Worker validates environment and S3 access
4. Worker downloads MusicGen model (cached after first run)
5. Worker processes prompts.txt sequentially
6. Worker uploads audio files to S3
7. Worker reports completion metrics

## Task 1: Add comprehensive startup validation

### 1.1 Add AWS environment variable validation
- **File**: `src/worker.py`
- **Purpose**: Validate AWS credentials are available via environment variables
- **Requirements**: Check AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY, MUSICGEN_S3_BUCKET, AWS_DEFAULT_REGION
- **Success Criteria**: Worker uses boto3 environment detection and fails fast if credentials missing

### 1.2 Add S3 connectivity and bucket validation  
- **File**: `src/worker.py`
- **Purpose**: Verify S3 access using boto3 automatic credential detection
- **Requirements**: Test S3 connection with environment credentials, verify bucket exists and is writable
- **Success Criteria**: Worker confirms S3 authentication works or fails with specific AWS error

### 1.3 Add model availability check
- **File**: `src/worker.py` 
- **Purpose**: Verify model can be downloaded or is cached
- **Requirements**: Check Hugging Face access, verify disk space for model
- **Success Criteria**: Worker confirms model is ready or fails with clear error

## Task 2: Create automated deployment to running pod

### 2.1 Create deployment script for running pods
- **File**: `deploy/deploy_to_pod.py`
- **Purpose**: Deploy code and configure environment on RunPod pod
- **Requirements**: Read .env, SCP files to pod, SSH to set AWS environment variables, run uv init/add
- **Success Criteria**: Code deployed with AWS environment automatically configured on pod

### 2.2 Create log monitoring scripts
- **Files**: `deploy/monitor_logs.py`, `deploy/monitor_system.py`, `deploy/check_gpu.py`
- **Purpose**: SSH into pod and tail logs using .env configuration
- **Requirements**: Read RUNPOD_HOST from .env, SSH to pod and stream logs
- **Success Criteria**: Real-time log monitoring using environment variables

### 2.3 Create combined deploy and monitor script
- **File**: `deploy/deploy_and_monitor.py`
- **Purpose**: Deploy code and immediately start monitoring using .env
- **Requirements**: Use .env configuration for deployment then log monitoring
- **Success Criteria**: Seamless workflow using environment variables

## Task 3: Create uv project setup

### 3.1 Create uv project configuration
- **File**: `pyproject.toml`
- **Purpose**: Define uv project with required dependencies
- **Requirements**: boto3, torch, transformers, soundfile, numpy, python-dotenv
- **Success Criteria**: uv project initializes and installs dependencies

### 3.2 Create environment template
- **File**: `.env.template`
- **Purpose**: Template for local .env file with RunPod and AWS configuration
- **Requirements**: Include RUNPOD_HOST, RUNPOD_USER, AWS credentials, with setup instructions
- **Success Criteria**: Template covers all variables and explains dual environment setup (local + pod)

## Task 4: Add enhanced batch reporting

### 4.1 Add detailed completion reporting
- **File**: `src/worker.py`
- **Purpose**: Report detailed metrics after batch completion
- **Requirements**: List all S3 files created, generation time per song, total processing time
- **Success Criteria**: Clear summary of what was generated and stored

### 4.2 Add model download verification and progress
- **File**: `src/worker.py`
- **Purpose**: Verify model download and show progress
- **Requirements**: Confirm model cache, show download progress if needed
- **Success Criteria**: User knows model status during initialization

## Task 5: Create deployment documentation

### 5.1 Create step-by-step deployment guide
- **File**: `docs/RUNPOD_DEPLOYMENT.md`
- **Purpose**: Complete guide for deploying to RunPod L40S
- **Requirements**: Cover pod setup, environment variables, deployment script usage
- **Success Criteria**: User can follow guide to deploy successfully

### 5.2 Add troubleshooting section
- **File**: `docs/RUNPOD_DEPLOYMENT.md`
- **Purpose**: Common issues and solutions for RunPod deployment
- **Requirements**: Environment validation failures, S3 connectivity, model download issues
- **Success Criteria**: Common deployment issues have documented solutions

## Task 6: Test and validate deployment

### 6.1 Add sample prompts for testing
- **File**: `deploy/test_prompts.txt`
- **Purpose**: Small batch for testing RunPod deployment
- **Requirements**: 2-3 short prompts (10-15 seconds each) for quick validation
- **Success Criteria**: Test batch completes successfully on L40S

## Success Metrics

After completing all tasks:
- Worker validates environment and S3 access before starting
- MusicGen deploys seamlessly to running RunPod L40S pods  
- User can deploy via single script execution
- Application processes all prompts sequentially and reports completion
- Clear summary of S3 files created and generation times
- Comprehensive validation prevents common deployment issues
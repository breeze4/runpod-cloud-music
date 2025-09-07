#!/usr/bin/env python3
"""
RunPod Deployment Script

Deploys MusicGen code to running RunPod pod and configures environment.
Reads configuration from .env file and automatically sets up AWS environment on pod.
"""

import os
import sys
import subprocess
import tempfile
from pathlib import Path
from dotenv import load_dotenv

def load_environment():
    """Load environment variables from .env file"""
    env_file = Path.cwd() / '.env'
    
    if not env_file.exists():
        print("ERROR: .env file not found")
        print("Create .env file from .env.template with your credentials")
        sys.exit(1)
    
    load_dotenv(env_file)
    
    # Check required variables
    required_vars = ['RUNPOD_HOST', 'RUNPOD_USER']
    missing = []
    
    for var in required_vars:
        if not os.getenv(var):
            missing.append(var)
    
    if missing:
        print(f"ERROR: Missing required variables in .env: {', '.join(missing)}")
        sys.exit(1)
    
    print("SUCCESS: Environment loaded from .env file")

def check_ssh_connection():
    """Test SSH connection to RunPod"""
    host = os.getenv('RUNPOD_HOST')
    user = os.getenv('RUNPOD_USER', 'root')
    port = os.getenv('RUNPOD_PORT', '22')
    
    print(f"Testing SSH connection to {user}@{host}:{port}...")
    
    try:
        result = subprocess.run([
            'ssh', '-o', 'ConnectTimeout=10', 
            '-o', 'StrictHostKeyChecking=no',
            '-p', port,
            f'{user}@{host}', 
            'echo "SSH connection successful"'
        ], capture_output=True, text=True, timeout=15)
        
        if result.returncode == 0:
            print("SUCCESS: SSH connection successful")
            return True
        else:
            print(f"ERROR: SSH connection failed: {result.stderr}")
            return False
            
    except subprocess.TimeoutExpired:
        print("ERROR: SSH connection timed out")
        return False
    except Exception as e:
        print(f"ERROR: SSH connection error: {e}")
        return False

def sync_code():
    """Sync code files to RunPod using rsync"""
    host = os.getenv('RUNPOD_HOST')
    user = os.getenv('RUNPOD_USER', 'root')
    port = os.getenv('RUNPOD_PORT', '22')
    
    print("Syncing code to RunPod...")
    
    # Files and directories to sync
    sync_items = [
        'src/',
        'prompts.txt',
        'pyproject.toml'
    ]
    
    # Check if items exist before syncing
    existing_items = []
    for item in sync_items:
        if Path(item).exists():
            existing_items.append(item)
        else:
            print(f"WARNING: {item} not found, skipping")
    
    if not existing_items:
        print("ERROR: No files to sync")
        return False
    
    try:
        # Use SCP with explicit directory creation for Windows compatibility
        print("Using SCP for file transfer (Windows compatible)...")
        
        # First, clean up any existing files and ensure proper directory structure
        print("Preparing workspace directory...")
        subprocess.run([
            'ssh', '-p', port, f'{user}@{host}',
            'rm -rf /workspace/src /workspace/prompts.txt /workspace/pyproject.toml 2>/dev/null || true'
        ], check=True)
        
        for item in existing_items:
            print(f"Uploading {item}...")
            if os.path.isdir(item):
                # For directories, create the target directory first, then upload contents
                target_dir = f"/workspace/{os.path.basename(item)}"
                print(f"  Creating target directory: {target_dir}")
                subprocess.run([
                    'ssh', '-p', port, f'{user}@{host}',
                    f'mkdir -p {target_dir}'
                ], check=True)
                
                # Upload directory contents using wildcard (works better on Windows)
                import glob
                item_path = item.rstrip('/\\')  # Remove trailing slashes
                
                # Upload all files in the directory
                for subitem in glob.glob(f"{item_path}/*"):
                    if os.path.isfile(subitem):
                        cmd = [
                            'scp', '-P', port, '-o', 'StrictHostKeyChecking=no',
                            subitem, f'{user}@{host}:{target_dir}/'
                        ]
                        result = subprocess.run(cmd, check=True)
                    elif os.path.isdir(subitem):
                        # Recursively upload subdirectories
                        subdir_name = os.path.basename(subitem)
                        cmd = [
                            'scp', '-r', '-P', port, '-o', 'StrictHostKeyChecking=no',
                            subitem, f'{user}@{host}:{target_dir}/'
                        ]
                        result = subprocess.run(cmd, check=True)
            else:
                # For files, upload directly to workspace
                cmd = [
                    'scp', '-P', port, '-o', 'StrictHostKeyChecking=no',
                    item, f'{user}@{host}:/workspace/'
                ]
                result = subprocess.run(cmd, check=True)
        
        # Verify the upload
        print("Verifying uploaded files...")
        result = subprocess.run([
            'ssh', '-p', port, f'{user}@{host}',
            'ls -la /workspace/'
        ], capture_output=True, text=True)
        print("Workspace contents:")
        print(result.stdout)
        
        print("SUCCESS: Code sync completed")
        return True
        
    except subprocess.CalledProcessError as e:
        print(f"ERROR: Code sync failed: {e}")
        return False

def setup_environment():
    """Set up Python environment and dependencies on pod"""
    host = os.getenv('RUNPOD_HOST')
    user = os.getenv('RUNPOD_USER', 'root')
    port = os.getenv('RUNPOD_PORT', '22')
    
    print("Setting up Python environment on pod...")
    
    # Create a single command that installs uv and sets up environment
    setup_command = '''
    cd /workspace &&
    export PATH="$HOME/.local/bin:$HOME/.cargo/bin:$PATH" &&
    if ! command -v uv &> /dev/null; then
        echo "Installing uv..." &&
        curl -LsSf https://astral.sh/uv/install.sh | sh &&
        export PATH="$HOME/.local/bin:$HOME/.cargo/bin:$PATH"
    fi &&
    echo "PATH=$HOME/.local/bin:$HOME/.cargo/bin:$PATH" >> ~/.bashrc &&
    echo "Verifying uv installation..." &&
    which uv &&
    uv --version &&
    echo "Setting up Python environment with dependencies..." &&
    if [ -f pyproject.toml ]; then
        echo "Found pyproject.toml, using uv sync..." &&
        uv sync --verbose
    else
        echo "No pyproject.toml found, creating new project..." &&
        uv init --no-readme &&
        echo "Adding required dependencies..." &&
        uv add boto3 torch transformers soundfile numpy python-dotenv
    fi &&
    echo "Verifying installed packages..." &&
    uv run python -c "import boto3, torch, transformers, soundfile, numpy; print('All packages imported successfully')" &&
    echo "Testing Python environment..." &&
    uv run python --version
    '''
    
    try:
        print("Running comprehensive environment setup...")
        print("This may take several minutes for downloading and installing dependencies...")
        
        # Run without capturing output so we can see real-time progress
        result = subprocess.run([
            'ssh', '-p', port, f'{user}@{host}', 
            setup_command
        ], timeout=300)  # 5 minute timeout for dependencies
        
        if result.returncode != 0:
            print(f"WARNING: Environment setup had issues (exit code: {result.returncode})")
            # Run a quick verification to see what worked
            print("Running verification check...")
            verify_result = subprocess.run([
                'ssh', '-p', port, f'{user}@{host}',
                'cd /workspace && export PATH="$HOME/.local/bin:$HOME/.cargo/bin:$PATH" && which uv && ls -la'
            ], capture_output=True, text=True)
            print(f"Verification output: {verify_result.stdout}")
            if verify_result.stderr:
                print(f"Verification errors: {verify_result.stderr}")
        else:
            print("SUCCESS: Environment setup completed successfully")
        
        print("SUCCESS: Python environment setup completed")
        return True
        
    except Exception as e:
        print(f"ERROR: Environment setup failed: {e}")
        return False

def configure_aws_environment():
    """Configure AWS environment variables on pod"""
    host = os.getenv('RUNPOD_HOST')
    user = os.getenv('RUNPOD_USER', 'root')
    port = os.getenv('RUNPOD_PORT', '22')
    
    print("Configuring AWS environment on pod...")
    
    # AWS variables to transfer
    aws_vars = [
        'AWS_ACCESS_KEY_ID',
        'AWS_SECRET_ACCESS_KEY',
        'AWS_DEFAULT_REGION',
        'MUSICGEN_S3_BUCKET'
    ]
    
    # Collect environment variables
    env_commands = []
    missing_vars = []
    
    for var in aws_vars:
        value = os.getenv(var)
        if value:
            # Strip all whitespace including Windows line endings and escape special characters for shell
            cleaned_value = value.strip().strip('\r\n').strip()
            escaped_value = cleaned_value.replace('"', '\\"').replace('$', '\\$')
            env_commands.append(f'export {var}="{escaped_value}"')
        else:
            if var != 'AWS_DEFAULT_REGION':  # AWS_DEFAULT_REGION is optional
                missing_vars.append(var)
    
    if missing_vars:
        print(f"WARNING: Missing AWS variables (set in .env): {', '.join(missing_vars)}")
    
    if not env_commands:
        print("ERROR: No AWS environment variables to configure")
        return False
    
    try:
        # Create environment setup script
        setup_script = "#!/bin/bash\n" + "\n".join(env_commands)
        
        # Write to temporary file and copy to pod
        with tempfile.NamedTemporaryFile(mode='w', suffix='.sh', delete=False) as f:
            f.write(setup_script)
            temp_path = f.name
        
        # Copy script to pod
        subprocess.run([
            'scp', '-P', port, '-o', 'StrictHostKeyChecking=no',
            temp_path, f'{user}@{host}:/workspace/setup_env.sh'
        ], check=True)
        
        # Make script executable, remove old bashrc entry, and add new one
        subprocess.run([
            'ssh', '-p', port, f'{user}@{host}',
            'chmod +x /workspace/setup_env.sh && grep -v "source /workspace/setup_env.sh" ~/.bashrc > ~/.bashrc.tmp && mv ~/.bashrc.tmp ~/.bashrc && echo "source /workspace/setup_env.sh" >> ~/.bashrc'
        ], check=True)
        
        # Clean up temp file
        os.unlink(temp_path)
        
        print("SUCCESS: AWS environment configured")
        print("Variables set:")
        for var in aws_vars:
            if os.getenv(var):
                print(f"  - {var}")
        
        return True
        
    except Exception as e:
        print(f"ERROR: AWS environment configuration failed: {e}")
        return False

def create_s3_bucket():
    """Create S3 bucket if it doesn't exist"""
    print("Creating S3 bucket if needed...")
    
    bucket_name = os.getenv('MUSICGEN_S3_BUCKET')
    region = os.getenv('AWS_DEFAULT_REGION', 'us-east-1')
    
    if not bucket_name:
        print("WARNING: No S3 bucket name specified, skipping bucket creation")
        return True
    
    try:
        import boto3
        from botocore.exceptions import ClientError
        
        # Clean environment variables
        bucket_name = bucket_name.strip().strip('\r\n').strip()
        region = region.strip().strip('\r\n').strip()
        
        s3 = boto3.client('s3', region_name=region)
        
        # Check if bucket already exists
        try:
            s3.head_bucket(Bucket=bucket_name)
            print(f"SUCCESS: S3 bucket '{bucket_name}' already exists")
            return True
        except ClientError as e:
            error_code = e.response['Error']['Code']
            if error_code == '404':
                # Bucket doesn't exist, create it
                print(f"Creating S3 bucket '{bucket_name}' in region '{region}'...")
                
                if region == 'us-east-1':
                    # us-east-1 doesn't need LocationConstraint
                    s3.create_bucket(Bucket=bucket_name)
                else:
                    # Other regions need LocationConstraint
                    s3.create_bucket(
                        Bucket=bucket_name,
                        CreateBucketConfiguration={'LocationConstraint': region}
                    )
                
                # Wait for bucket to be available
                print("Waiting for bucket to be available...")
                waiter = s3.get_waiter('bucket_exists')
                waiter.wait(Bucket=bucket_name, WaiterConfig={'Delay': 2, 'MaxAttempts': 30})
                
                print(f"SUCCESS: S3 bucket '{bucket_name}' created successfully")
                return True
            else:
                print(f"ERROR: Error checking bucket: {error_code}")
                return False
                
    except ImportError:
        print("ERROR: boto3 not available for bucket creation")
        return False
    except Exception as e:
        print(f"ERROR: S3 bucket creation failed: {e}")
        return False

def verify_deployment():
    """Verify deployment was successful with basic checks"""
    host = os.getenv('RUNPOD_HOST')
    user = os.getenv('RUNPOD_USER', 'root')
    port = os.getenv('RUNPOD_PORT', '22')
    
    print("Verifying basic deployment...")
    
    checks = [
        ('Workspace directory', 'ls -la /workspace'),
        ('Python environment', 'cd /workspace && export PATH="$HOME/.local/bin:$HOME/.cargo/bin:$PATH" && uv run python --version'),
        ('Worker script', 'ls -la /workspace/worker.py'),
        ('AWS variables', 'cd /workspace && source setup_env.sh && echo "S3 bucket: $MUSICGEN_S3_BUCKET"')
    ]
    
    all_passed = True
    
    for check_name, command in checks:
        try:
            result = subprocess.run([
                'ssh', '-p', port, f'{user}@{host}', command
            ], capture_output=True, text=True, timeout=10)
            
            if result.returncode == 0:
                print(f"SUCCESS: {check_name}: OK")
            else:
                print(f"ERROR: {check_name}: FAILED")
                print(f"   Error: {result.stderr}")
                all_passed = False
                
        except Exception as e:
            print(f"ERROR: {check_name}: ERROR - {e}")
            all_passed = False
    
    return all_passed

def run_comprehensive_validation():
    """Run comprehensive post-deployment validation using separate validation script"""
    host = os.getenv('RUNPOD_HOST')
    user = os.getenv('RUNPOD_USER', 'root')
    port = os.getenv('RUNPOD_PORT', '22')
    
    print("\nRUNNING COMPREHENSIVE POST-DEPLOYMENT VALIDATION")
    print("="*60)
    
    try:
        # Upload validation script to pod
        validation_script_path = Path(__file__).parent / 'validate_deployment.py'
        
        if not validation_script_path.exists():
            print("ERROR: Validation script not found at deploy/validate_deployment.py")
            return False
        
        subprocess.run([
            'scp', '-P', port, '-o', 'StrictHostKeyChecking=no',
            str(validation_script_path), f'{user}@{host}:/workspace/validate_deployment.py'
        ], check=True)
        
        # Run validation script on pod with environment
        validation_command = '''
cd /workspace &&
export PATH="$HOME/.local/bin:$HOME/.cargo/bin:$PATH" &&
source setup_env.sh &&
uv run python validate_deployment.py
'''
        
        result = subprocess.run([
            'ssh', '-p', port, f'{user}@{host}', validation_command
        ], capture_output=True, text=True, timeout=30)
        
        print("Validation Results:")
        print("-" * 30)
        print(result.stdout)
        
        if result.stderr:
            print("Validation Errors:")
            print("-" * 30)
            print(result.stderr)
        
        # Clean up validation script
        subprocess.run([
            'ssh', '-p', port, f'{user}@{host}', 'rm -f /workspace/validate_deployment.py'
        ], capture_output=True)
        
        return result.returncode == 0
        
    except subprocess.TimeoutExpired:
        print("ERROR: Validation timed out after 30 seconds")
        # Clean up validation script even on timeout
        subprocess.run([
            'ssh', '-p', port, f'{user}@{host}', 'rm -f /workspace/validate_deployment.py'
        ], capture_output=True)
        return False
    except Exception as e:
        print(f"ERROR: Comprehensive validation failed: {e}")
        return False

def main():
    """Main deployment function"""
    print("RunPod MusicGen Deployment")
    print("="*50)
    
    try:
        # Load environment
        load_environment()
        
        # Check SSH connection
        if not check_ssh_connection():
            print("ERROR: Cannot connect to RunPod. Check RUNPOD_HOST and SSH keys")
            sys.exit(1)
        
        # Sync code
        if not sync_code():
            print("ERROR: Code sync failed")
            sys.exit(1)
        
        # Setup environment
        if not setup_environment():
            print("ERROR: Environment setup failed")
            sys.exit(1)
        
        # Configure AWS
        if not configure_aws_environment():
            print("WARNING: AWS environment configuration had issues")
        
        # Create S3 bucket if needed
        if not create_s3_bucket():
            print("WARNING: S3 bucket creation had issues")
        
        # Verify basic deployment first
        basic_deployment_ok = verify_deployment()
        if not basic_deployment_ok:
            print("ERROR: Basic deployment verification failed")
            sys.exit(1)
        
        # Run comprehensive post-deployment validation
        validation_passed = run_comprehensive_validation()
        
        print("\n" + "="*50)
        if validation_passed:
            print("DEPLOYMENT AND VALIDATION SUCCESSFUL!")
            print("="*50)
            print("SUCCESS: All systems verified and ready for MusicGen processing")
            print("\nTo run the worker:")
            print(f"ssh {os.getenv('RUNPOD_USER', 'root')}@{os.getenv('RUNPOD_HOST')} -p {os.getenv('RUNPOD_PORT', '22')}")
            print("cd /workspace")
            print("source setup_env.sh  # Load AWS environment")
            print("uv run worker.py")
            print("\nFor quick iteration (sync code and restart worker):")
            print("uv run deploy/sync_and_run_worker.py")
            print("\nFor monitoring:")
            print("uv run deploy/monitor_logs.py")
        else:
            print("WARNING: DEPLOYMENT COMPLETED BUT VALIDATION FAILED")
            print("="*50)
            print("ERROR: Some components are not working correctly")
            print("Check the validation errors above before proceeding")
            sys.exit(1)
            
    except KeyboardInterrupt:
        print("\nWARNING: Deployment interrupted by user")
        sys.exit(1)
    except Exception as e:
        print(f"ERROR: Deployment failed: {e}")
        sys.exit(1)

if __name__ == '__main__':
    main()
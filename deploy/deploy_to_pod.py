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
        print("❌ .env file not found")
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
        print(f"❌ Missing required variables in .env: {', '.join(missing)}")
        sys.exit(1)
    
    print("✅ Environment loaded from .env file")

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
            print("✅ SSH connection successful")
            return True
        else:
            print(f"❌ SSH connection failed: {result.stderr}")
            return False
            
    except subprocess.TimeoutExpired:
        print("❌ SSH connection timed out")
        return False
    except Exception as e:
        print(f"❌ SSH connection error: {e}")
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
            print(f"⚠️  {item} not found, skipping")
    
    if not existing_items:
        print("❌ No files to sync")
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
        
        print("✅ Code sync completed")
        return True
        
    except subprocess.CalledProcessError as e:
        print(f"❌ Code sync failed: {e}")
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
    if [ -f pyproject.toml ]; then
        echo "Setting up project with uv sync..." &&
        uv sync
    else
        echo "Creating new uv project..." &&
        uv init --no-readme &&
        uv add boto3 torch transformers soundfile numpy python-dotenv
    fi &&
    echo "Testing Python environment..." &&
    uv run python --version
    '''
    
    try:
        print("Running comprehensive environment setup...")
        result = subprocess.run([
            'ssh', '-p', port, f'{user}@{host}', 
            setup_command
        ], capture_output=True, text=True, timeout=300)  # 5 minute timeout for dependencies
        
        if result.returncode != 0:
            print(f"⚠️  Environment setup had issues:")
            print(f"STDOUT: {result.stdout}")
            print(f"STDERR: {result.stderr}")
            # Don't fail completely, continue with verification
        else:
            print("✅ Environment setup completed successfully")
        
        print("Environment setup output:")
        print(result.stdout)
        
        print("✅ Python environment setup completed")
        return True
        
    except Exception as e:
        print(f"❌ Environment setup failed: {e}")
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
            # Escape special characters for shell
            escaped_value = value.replace('"', '\\"').replace('$', '\\$')
            env_commands.append(f'export {var}="{escaped_value}"')
        else:
            if var != 'AWS_DEFAULT_REGION':  # AWS_DEFAULT_REGION is optional
                missing_vars.append(var)
    
    if missing_vars:
        print(f"⚠️  Missing AWS variables (set in .env): {', '.join(missing_vars)}")
    
    if not env_commands:
        print("❌ No AWS environment variables to configure")
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
        
        # Make script executable and source it
        subprocess.run([
            'ssh', '-p', port, f'{user}@{host}',
            'chmod +x /workspace/setup_env.sh && echo "source /workspace/setup_env.sh" >> ~/.bashrc'
        ], check=True)
        
        # Clean up temp file
        os.unlink(temp_path)
        
        print("✅ AWS environment configured")
        print("Variables set:")
        for var in aws_vars:
            if os.getenv(var):
                print(f"  - {var}")
        
        return True
        
    except Exception as e:
        print(f"❌ AWS environment configuration failed: {e}")
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
                print(f"✅ {check_name}: OK")
            else:
                print(f"❌ {check_name}: FAILED")
                print(f"   Error: {result.stderr}")
                all_passed = False
                
        except Exception as e:
            print(f"❌ {check_name}: ERROR - {e}")
            all_passed = False
    
    return all_passed

def run_comprehensive_validation():
    """Run comprehensive post-deployment validation using check_pod.py functionality"""
    host = os.getenv('RUNPOD_HOST')
    user = os.getenv('RUNPOD_USER', 'root')
    port = os.getenv('RUNPOD_PORT', '22')
    
    print("\n🔍 RUNNING COMPREHENSIVE POST-DEPLOYMENT VALIDATION")
    print("="*60)
    
    # Create a comprehensive validation script that mimics check_pod.py functionality
    validation_script = '''
import os
import sys

def check_aws_environment():
    """Check AWS environment variables"""
    print("☁️ Checking AWS Environment...")
    required_vars = ['AWS_ACCESS_KEY_ID', 'AWS_SECRET_ACCESS_KEY', 'MUSICGEN_S3_BUCKET', 'AWS_DEFAULT_REGION']
    
    missing = []
    for var in required_vars:
        if not os.getenv(var):
            missing.append(var)
    
    if missing:
        print(f"❌ Missing AWS variables: {', '.join(missing)}")
        return False
    else:
        print("✅ AWS environment variables present")
        return True

def check_s3_connectivity():
    """Test S3 connectivity and bucket access"""
    print("📦 Testing S3 Connectivity...")
    
    try:
        import boto3
        from botocore.exceptions import ClientError
        
        bucket_name = os.getenv('MUSICGEN_S3_BUCKET')
        region = os.getenv('AWS_DEFAULT_REGION', 'us-east-1')
        
        # Test basic S3 connectivity
        s3 = boto3.client('s3', region_name=region)
        response = s3.list_buckets()
        print(f"✅ S3 connection successful - Found {len(response['Buckets'])} buckets")
        
        # Test specific bucket access
        s3.head_bucket(Bucket=bucket_name)
        print(f"✅ Bucket {bucket_name} exists and is accessible")
        
        # Test write permissions
        test_key = 'musicgen_deployment_test.txt'
        s3.put_object(Bucket=bucket_name, Key=test_key, Body='deployment validation test')
        print("✅ Write permissions confirmed")
        
        # Clean up test object
        s3.delete_object(Bucket=bucket_name, Key=test_key)
        print("✅ S3 connectivity test completed successfully")
        
        return True
        
    except ImportError:
        print("❌ boto3 not available")
        return False
    except ClientError as e:
        error_code = e.response['Error']['Code']
        print(f"❌ S3 error: {error_code}")
        return False
    except Exception as e:
        print(f"❌ S3 test failed: {e}")
        return False

def check_dependencies():
    """Check that all required dependencies are installed"""
    print("📦 Checking Dependencies...")
    
    required_modules = ['torch', 'transformers', 'soundfile', 'numpy', 'boto3']
    missing = []
    
    for module in required_modules:
        try:
            __import__(module)
            print(f"✅ {module}")
        except ImportError:
            print(f"❌ {module}")
            missing.append(module)
    
    if missing:
        print(f"❌ Missing dependencies: {', '.join(missing)}")
        return False
    else:
        print("✅ All dependencies available")
        return True

def check_gpu_torch():
    """Check GPU and PyTorch integration"""
    print("🎮 Checking GPU and PyTorch...")
    
    try:
        import torch
        
        if torch.cuda.is_available():
            gpu_count = torch.cuda.device_count()
            gpu_name = torch.cuda.get_device_name(0)
            print(f"✅ CUDA available - {gpu_count} GPU(s)")
            print(f"✅ Primary GPU: {gpu_name}")
            
            # Test memory allocation
            x = torch.randn(100, 100, device='cuda')
            print("✅ GPU memory allocation successful")
            del x
            torch.cuda.empty_cache()
            
            return True
        else:
            print("❌ CUDA not available")
            return False
            
    except Exception as e:
        print(f"❌ GPU/PyTorch test failed: {e}")
        return False

# Run all validation checks
print("🚀 POST-DEPLOYMENT VALIDATION")
print("="*50)

# Source environment variables first
print("Loading environment variables...")

aws_ok = check_aws_environment()
deps_ok = check_dependencies()
gpu_ok = check_gpu_torch()
s3_ok = check_s3_connectivity() if aws_ok and deps_ok else False

print("\\n📋 VALIDATION SUMMARY")
print("="*30)
print(f"AWS Environment: {'✅' if aws_ok else '❌'}")
print(f"Dependencies: {'✅' if deps_ok else '❌'}")
print(f"GPU/PyTorch: {'✅' if gpu_ok else '❌'}")
print(f"S3 Connectivity: {'✅' if s3_ok else '❌'}")

all_good = aws_ok and deps_ok and gpu_ok and s3_ok

print("\\n" + "="*50)
if all_good:
    print("🎉 DEPLOYMENT VALIDATION SUCCESSFUL!")
    print("Environment is ready for MusicGen processing")
else:
    print("⚠️ DEPLOYMENT VALIDATION FAILED!")
    print("Check the errors above before proceeding")
    
print("="*50)
sys.exit(0 if all_good else 1)
'''
    
    # Write validation script to temporary file and upload to pod
    try:
        import tempfile
        with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False) as f:
            f.write(validation_script)
            temp_script = f.name
        
        # Upload validation script to pod
        subprocess.run([
            'scp', '-P', port, '-o', 'StrictHostKeyChecking=no',
            temp_script, f'{user}@{host}:/workspace/validate_deployment.py'
        ], check=True)
        
        # Clean up local temp file
        os.unlink(temp_script)
        
        # Run validation script on pod with environment
        validation_command = '''
cd /workspace &&
export PATH="$HOME/.local/bin:$HOME/.cargo/bin:$PATH" &&
source setup_env.sh &&
uv run python validate_deployment.py
'''
        
        result = subprocess.run([
            'ssh', '-p', port, f'{user}@{host}', validation_command
        ], capture_output=True, text=True, timeout=60)
        
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
        
    except Exception as e:
        print(f"❌ Comprehensive validation failed: {e}")
        return False

def main():
    """Main deployment function"""
    print("🚀 RunPod MusicGen Deployment")
    print("="*50)
    
    try:
        # Load environment
        load_environment()
        
        # Check SSH connection
        if not check_ssh_connection():
            print("❌ Cannot connect to RunPod. Check RUNPOD_HOST and SSH keys")
            sys.exit(1)
        
        # Sync code
        if not sync_code():
            print("❌ Code sync failed")
            sys.exit(1)
        
        # Setup environment
        if not setup_environment():
            print("❌ Environment setup failed")
            sys.exit(1)
        
        # Configure AWS
        if not configure_aws_environment():
            print("⚠️  AWS environment configuration had issues")
        
        # Verify basic deployment first
        basic_deployment_ok = verify_deployment()
        if not basic_deployment_ok:
            print("❌ Basic deployment verification failed")
            sys.exit(1)
        
        # Run comprehensive post-deployment validation
        validation_passed = run_comprehensive_validation()
        
        print("\n" + "="*50)
        if validation_passed:
            print("🎉 DEPLOYMENT AND VALIDATION SUCCESSFUL!")
            print("="*50)
            print("✅ All systems verified and ready for MusicGen processing")
            print("\nTo run the worker:")
            print(f"ssh {os.getenv('RUNPOD_USER', 'root')}@{os.getenv('RUNPOD_HOST')} -p {os.getenv('RUNPOD_PORT', '22')}")
            print("cd /workspace")
            print("source setup_env.sh  # Load AWS environment")
            print("uv run worker.py")
            print("\nOr use the all-in-one monitoring script:")
            print("uv run python deploy/deploy_and_monitor.py")
        else:
            print("⚠️  DEPLOYMENT COMPLETED BUT VALIDATION FAILED")
            print("="*50)
            print("❌ Some components are not working correctly")
            print("Check the validation errors above before proceeding")
            sys.exit(1)
            
    except KeyboardInterrupt:
        print("\n⚠️  Deployment interrupted by user")
        sys.exit(1)
    except Exception as e:
        print(f"❌ Deployment failed: {e}")
        sys.exit(1)

if __name__ == '__main__':
    main()
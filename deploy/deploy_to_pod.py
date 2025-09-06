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
        # Create workspace directory on pod
        subprocess.run([
            'ssh', '-p', port, f'{user}@{host}', 
            'mkdir -p /workspace'
        ], check=True)
        
        # Sync files
        cmd = [
            'rsync', '-avz', '--progress',
            '-e', f'ssh -p {port} -o StrictHostKeyChecking=no'
        ] + existing_items + [f'{user}@{host}:/workspace/']
        
        result = subprocess.run(cmd, check=True)
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
    
    commands = [
        # Change to workspace
        'cd /workspace',
        
        # Check if uv is installed, install if not
        'which uv || curl -LsSf https://astral.sh/uv/install.sh | sh',
        
        # Add uv to PATH for current session
        'export PATH="$HOME/.cargo/bin:$PATH"',
        
        # Initialize uv project if pyproject.toml exists
        'if [ -f pyproject.toml ]; then uv sync; else uv init --no-readme && uv add boto3 torch transformers soundfile numpy python-dotenv; fi',
        
        # Test Python environment
        'uv run python --version'
    ]
    
    try:
        for cmd in commands:
            print(f"Running: {cmd}")
            result = subprocess.run([
                'ssh', '-p', port, f'{user}@{host}', 
                f'cd /workspace && {cmd}'
            ], capture_output=True, text=True)
            
            if result.returncode != 0:
                print(f"⚠️  Command warning: {result.stderr}")
            else:
                print(f"✅ {cmd}")
        
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
    """Verify deployment was successful"""
    host = os.getenv('RUNPOD_HOST')
    user = os.getenv('RUNPOD_USER', 'root')
    port = os.getenv('RUNPOD_PORT', '22')
    
    print("Verifying deployment...")
    
    checks = [
        ('Workspace directory', 'ls -la /workspace'),
        ('Python environment', 'cd /workspace && uv run python --version'),
        ('Worker script', 'ls -la /workspace/src/worker.py'),
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
        
        # Verify deployment
        if verify_deployment():
            print("\n" + "="*50)
            print("🎵 DEPLOYMENT SUCCESSFUL!")
            print("="*50)
            print("\nTo run the worker:")
            print(f"ssh {os.getenv('RUNPOD_USER', 'root')}@{os.getenv('RUNPOD_HOST')}")
            print("cd /workspace")
            print("source setup_env.sh  # Load AWS environment")
            print("uv run src/worker.py")
            print("\nOr use the monitoring script:")
            print("python deploy/monitor_logs.py")
        else:
            print("⚠️  Deployment completed with some issues")
            sys.exit(1)
            
    except KeyboardInterrupt:
        print("\n⚠️  Deployment interrupted by user")
        sys.exit(1)
    except Exception as e:
        print(f"❌ Deployment failed: {e}")
        sys.exit(1)

if __name__ == '__main__':
    main()
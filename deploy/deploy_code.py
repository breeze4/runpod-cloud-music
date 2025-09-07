#!/usr/bin/env python3
"""
RunPod Code Deployment Script

Phase 1: Deploy source code to RunPod pod.
Only handles file upload and basic connectivity - no dependency installation or environment setup.
"""

import os
import sys
import subprocess
import glob
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
    """Sync code files to RunPod using SCP"""
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
        print("Using SCP for file transfer...")
        
        # Clean up any existing files and ensure proper directory structure
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
                
                # Upload directory contents
                item_path = item.rstrip('/\\')
                
                for subitem in glob.glob(f"{item_path}/*"):
                    if os.path.isfile(subitem):
                        cmd = [
                            'scp', '-P', port, '-o', 'StrictHostKeyChecking=no',
                            subitem, f'{user}@{host}:{target_dir}/'
                        ]
                        subprocess.run(cmd, check=True)
                    elif os.path.isdir(subitem):
                        cmd = [
                            'scp', '-r', '-P', port, '-o', 'StrictHostKeyChecking=no',
                            subitem, f'{user}@{host}:{target_dir}/'
                        ]
                        subprocess.run(cmd, check=True)
            else:
                # For files, upload directly to workspace
                cmd = [
                    'scp', '-P', port, '-o', 'StrictHostKeyChecking=no',
                    item, f'{user}@{host}:/workspace/'
                ]
                subprocess.run(cmd, check=True)
        
        print("SUCCESS: Code sync completed")
        return True
        
    except subprocess.CalledProcessError as e:
        print(f"ERROR: Code sync failed: {e}")
        return False

def verify_upload():
    """Verify uploaded files on pod"""
    host = os.getenv('RUNPOD_HOST')
    user = os.getenv('RUNPOD_USER', 'root')
    port = os.getenv('RUNPOD_PORT', '22')
    
    print("Verifying uploaded files...")
    
    try:
        result = subprocess.run([
            'ssh', '-p', port, f'{user}@{host}',
            'ls -la /workspace/'
        ], capture_output=True, text=True)
        
        if result.returncode == 0:
            print("Workspace contents:")
            print(result.stdout)
            
            # Check for essential files
            essential_files = ['src', 'pyproject.toml']
            found_files = []
            
            for file in essential_files:
                if file in result.stdout:
                    found_files.append(file)
                    print(f"SUCCESS: {file} found")
                else:
                    print(f"WARNING: {file} not found")
            
            return len(found_files) > 0
        else:
            print(f"ERROR: Could not verify upload: {result.stderr}")
            return False
            
    except Exception as e:
        print(f"ERROR: Verification failed: {e}")
        return False

def main():
    """Main deployment function"""
    print("RUNPOD CODE DEPLOYMENT")
    print("="*50)
    print("Phase 1: Deploy source code to RunPod pod")
    print("Note: This only uploads code - no dependencies or environment setup")
    print()
    
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
        
        # Verify upload
        if not verify_upload():
            print("WARNING: File verification had issues")
        
        print("\n" + "="*50)
        print("CODE DEPLOYMENT SUCCESSFUL!")
        print("="*50)
        print("Source code has been uploaded to /workspace/ on the pod")
        print()
        print("Next steps:")
        print("1. Run dependencies installation: uv run deploy/install_dependencies.py")
        print("2. Validate environment: uv run deploy/validate_environment.py") 
        print("3. Run worker: uv run deploy/run_worker.py")
        print()
        print("Or run all phases with the original script:")
        print("uv run deploy/deploy_to_pod.py")
        
    except KeyboardInterrupt:
        print("\nCode deployment interrupted by user")
        sys.exit(1)
    except Exception as e:
        print(f"ERROR: Code deployment failed: {e}")
        sys.exit(1)

if __name__ == '__main__':
    main()
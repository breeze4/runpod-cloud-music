#!/usr/bin/env python3
"""
RunPod Worker Sync and Run Script

Quick script for development iteration - just syncs code and starts worker.
Assumes the pod environment is already set up from a previous full deployment.
"""

import os
import sys
import subprocess
import time
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

def sync_code():
    """Sync only the source code to RunPod"""
    host = os.getenv('RUNPOD_HOST')
    user = os.getenv('RUNPOD_USER', 'root')
    port = os.getenv('RUNPOD_PORT', '22')
    
    print("Syncing source code to RunPod...")
    
    # Only sync source files for quick iteration
    sync_items = ['src/']
    
    # Check if items exist before syncing
    existing_items = []
    for item in sync_items:
        if Path(item).exists():
            existing_items.append(item)
        else:
            print(f"WARNING: {item} not found, skipping")
    
    if not existing_items:
        print("ERROR: No source files to sync")
        return False
    
    try:
        for item in existing_items:
            print(f"Uploading {item}...")
            if os.path.isdir(item):
                # For directories, ensure workspace exists and clear the target directory
                target_dir = f"/workspace/{os.path.basename(item)}"
                
                # Ensure workspace directory exists and clear target directory contents
                subprocess.run([
                    'ssh', '-p', port, f'{user}@{host}',
                    f'mkdir -p /workspace && rm -rf {target_dir}/* {target_dir}/.[!.]* 2>/dev/null || true && mkdir -p {target_dir}'
                ], check=True)
                
                # Upload directory contents
                import glob
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
        
        print("SUCCESS: Source code sync completed")
        return True
        
    except subprocess.CalledProcessError as e:
        print(f"ERROR: Source code sync failed: {e}")
        return False

def start_worker():
    """Start the MusicGen worker on the pod"""
    host = os.getenv('RUNPOD_HOST')
    user = os.getenv('RUNPOD_USER', 'root')
    port = os.getenv('RUNPOD_PORT', '22')
    
    print("\nStarting MusicGen worker...")
    
    # Check if prompts.txt exists
    if not Path('prompts.txt').exists():
        print("WARNING: prompts.txt not found - worker will have no jobs to process")
        print("Create prompts.txt with your music generation requests")
    
    try:
        # Start worker in background
        start_command = '''
cd /workspace && 
export PATH="$HOME/.local/bin:$HOME/.cargo/bin:$PATH" &&
source setup_env.sh && 
nohup $HOME/.local/bin/uv run worker.py > worker_output.log 2>&1 & 
echo $! > worker.pid &&
echo "Worker started with PID $(cat worker.pid)"
'''
        
        result = subprocess.run([
            'ssh', '-o', 'StrictHostKeyChecking=no',
            '-p', port,
            f'{user}@{host}', start_command
        ], capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=30)
        
        if result.returncode == 0:
            print("SUCCESS: MusicGen worker started")
            print(result.stdout)
            
            # Get PID
            pid_result = subprocess.run([
                'ssh', '-p', port, f'{user}@{host}', 'cat /workspace/worker.pid 2>/dev/null || echo "unknown"'
            ], capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=5)
            
            worker_pid = pid_result.stdout.strip() if pid_result.returncode == 0 else "unknown"
            return worker_pid
        else:
            print(f"ERROR: Failed to start worker: {result.stderr}")
            return None
            
    except Exception as e:
        print(f"ERROR: Error starting worker: {e}")
        return None

def monitor_worker_startup():
    """Monitor worker startup for a few seconds"""
    host = os.getenv('RUNPOD_HOST')
    user = os.getenv('RUNPOD_USER', 'root')
    port = os.getenv('RUNPOD_PORT', '22')
    
    print("\nMonitoring worker startup...")
    print("=" * 50)
    
    try:
        # Monitor for 10 seconds to catch any immediate errors
        for i in range(10):
            result = subprocess.run([
                'ssh', '-p', port, f'{user}@{host}', 
                'tail -5 /workspace/worker_output.log 2>/dev/null || echo "No output yet"'
            ], capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=5)
            
            if result.returncode == 0 and result.stdout.strip():
                output = result.stdout.strip()
                if output != "No output yet":
                    print(f"[{i+1}s] {output}")
                    
                    # Check for common error patterns
                    if "ERROR" in output or "Failed" in output or "error:" in output.lower():
                        print("\nWARNING: Detected error in worker output")
                        break
                    elif "Worker ready" in output or "Processing" in output:
                        print("\nSUCCESS: Worker appears to be running normally")
                        break
            
            time.sleep(1)
            
    except Exception as e:
        print(f"ERROR: Could not monitor worker startup: {e}")

def main():
    """Main function"""
    print("RUNPOD WORKER SYNC AND RUN")
    print("=" * 50)
    print("Quick iteration script - syncs code and starts worker")
    print("Assumes pod environment is already set up")
    print()
    
    try:
        # Load environment
        load_environment()
        
        # Sync source code
        if not sync_code():
            print("ERROR: Source code sync failed")
            sys.exit(1)
        
        # Start worker
        worker_pid = start_worker()
        if not worker_pid:
            print("ERROR: Could not start worker")
            sys.exit(1)
        
        # Monitor startup briefly
        monitor_worker_startup()
        
        print(f"\nWorker started with PID: {worker_pid}")
        print(f"To monitor logs: python deploy/monitor_logs.py")
        print(f"To check status: ssh {os.getenv('RUNPOD_USER', 'root')}@{os.getenv('RUNPOD_HOST')} -p {os.getenv('RUNPOD_PORT', '22')} 'tail /workspace/worker_output.log'")
        
    except KeyboardInterrupt:
        print("\nSync and run interrupted")
    except Exception as e:
        print(f"ERROR: Sync and run failed: {e}")
        sys.exit(1)

if __name__ == '__main__':
    main()
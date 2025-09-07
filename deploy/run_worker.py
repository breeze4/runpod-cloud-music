#!/usr/bin/env python3
"""
RunPod Worker Execution Script

Phase 4: Run the MusicGen worker and monitor its execution.
Handles worker startup, monitoring, and log tailing functionality.
"""

import os
import sys
import subprocess
import time
import signal
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

def check_worker_prerequisites():
    """Check if worker prerequisites are met"""
    host = os.getenv('RUNPOD_HOST')
    user = os.getenv('RUNPOD_USER', 'root')
    port = os.getenv('RUNPOD_PORT', '22')
    
    print("Checking worker prerequisites...")
    
    checks = [
        ('Worker script exists', 'ls -la /workspace/src/worker.py'),
        ('Environment setup exists', 'ls -la /workspace/setup_env.sh'),
        ('Python environment', 'cd /workspace && export PATH="$HOME/.local/bin:$HOME/.cargo/bin:$PATH" && which uv')
    ]
    
    all_passed = True
    
    for check_name, command in checks:
        try:
            result = subprocess.run([
                'ssh', '-p', port, f'{user}@{host}', command
            ], capture_output=True, text=True, timeout=10)
            
            if result.returncode == 0:
                print(f"SUCCESS: {check_name}")
            else:
                print(f"ERROR: {check_name} - {result.stderr.strip()}")
                all_passed = False
                
        except Exception as e:
            print(f"ERROR: {check_name} - {e}")
            all_passed = False
    
    return all_passed

def check_prompts_file():
    """Check if prompts.txt exists locally and on pod"""
    print("Checking for prompts.txt...")
    
    local_prompts = Path('prompts.txt')
    if not local_prompts.exists():
        print("WARNING: prompts.txt not found locally")
        print("Worker will have no jobs to process unless prompts.txt exists on pod")
    else:
        print("SUCCESS: prompts.txt found locally")
    
    # Check on pod
    host = os.getenv('RUNPOD_HOST')
    user = os.getenv('RUNPOD_USER', 'root')
    port = os.getenv('RUNPOD_PORT', '22')
    
    try:
        result = subprocess.run([
            'ssh', '-p', port, f'{user}@{host}', 'ls -la /workspace/prompts.txt'
        ], capture_output=True, text=True, timeout=5)
        
        if result.returncode == 0:
            print("SUCCESS: prompts.txt found on pod")
            return True
        else:
            print("WARNING: prompts.txt not found on pod")
            if local_prompts.exists():
                print("Uploading local prompts.txt to pod...")
                subprocess.run([
                    'scp', '-P', port, '-o', 'StrictHostKeyChecking=no',
                    'prompts.txt', f'{user}@{host}:/workspace/'
                ], check=True)
                print("SUCCESS: prompts.txt uploaded")
                return True
            return False
            
    except Exception as e:
        print(f"WARNING: Could not check prompts.txt on pod: {e}")
        return False

def start_worker():
    """Start the MusicGen worker on the pod"""
    host = os.getenv('RUNPOD_HOST')
    user = os.getenv('RUNPOD_USER', 'root')
    port = os.getenv('RUNPOD_PORT', '22')
    
    print("Starting MusicGen worker...")
    
    try:
        # Stop any existing worker first
        print("Stopping any existing worker processes...")
        subprocess.run([
            'ssh', '-p', port, f'{user}@{host}',
            'pkill -f "uv run.*worker.py" || true && pkill -f "python.*worker.py" || true'
        ], capture_output=True, text=True, timeout=10)
        time.sleep(2)
        
        print("Starting worker in background...")
        # Start worker in background
        start_command = '''
cd /workspace && 
export PATH="$HOME/.local/bin:$HOME/.cargo/bin:$PATH" &&
source setup_env.sh && 
nohup uv run src/worker.py > worker_output.log 2>&1 & 
echo $! > worker.pid &&
echo "Worker started with PID $(cat worker.pid)"
'''
        
        result = subprocess.run([
            'ssh', '-o', 'StrictHostKeyChecking=no',
            '-p', port,
            f'{user}@{host}', start_command
        ], capture_output=True, text=True, timeout=300)
        
        if result.returncode == 0:
            print("SUCCESS: MusicGen worker started")
            print(result.stdout.strip())
            
            # Get PID
            pid_result = subprocess.run([
                'ssh', '-p', port, f'{user}@{host}', 'cat /workspace/worker.pid 2>/dev/null || echo "unknown"'
            ], capture_output=True, text=True, timeout=5)
            
            worker_pid = pid_result.stdout.strip() if pid_result.returncode == 0 else "unknown"
            return worker_pid
        else:
            print(f"ERROR: Failed to start worker: {result.stderr}")
            return None
            
    except Exception as e:
        print(f"ERROR: Error starting worker: {e}")
        return None

def monitor_worker_startup(duration=15):
    """Monitor worker startup for initial errors"""
    host = os.getenv('RUNPOD_HOST')
    user = os.getenv('RUNPOD_USER', 'root')
    port = os.getenv('RUNPOD_PORT', '22')
    
    print(f"Monitoring worker startup for {duration} seconds...")
    print("=" * 60)
    
    try:
        for i in range(duration):
            result = subprocess.run([
                'ssh', '-p', port, f'{user}@{host}', 
                'tail -10 /workspace/worker_output.log 2>/dev/null || echo "No output yet"'
            ], capture_output=True, text=True, timeout=5)
            
            if result.returncode == 0:
                output = result.stdout.strip()
                if output and output != "No output yet":
                    print(f"[{i+1:2d}s] Latest output:")
                    for line in output.split('\n')[-3:]:  # Show last 3 lines
                        if line.strip():
                            print(f"      {line}")
                    
                    # Check for completion or error patterns
                    if any(pattern in output.lower() for pattern in ['error', 'failed', 'exception', 'traceback']):
                        print("\n⚠️  WARNING: Detected error in worker output")
                        break
                    elif any(pattern in output for pattern in ['Processing complete', 'generated and uploaded', 'Worker finished']):
                        print("\n✅ SUCCESS: Worker completed successfully")
                        break
                    elif 'Processing prompt' in output:
                        print(f"\n🎵 Worker is actively processing prompts...")
                else:
                    print(f"[{i+1:2d}s] Waiting for worker output...")
            
            time.sleep(1)
            
    except KeyboardInterrupt:
        print(f"\nMonitoring interrupted by user")
    except Exception as e:
        print(f"ERROR: Could not monitor worker startup: {e}")

def tail_worker_logs():
    """Continuously tail worker logs until interrupted"""
    host = os.getenv('RUNPOD_HOST')
    user = os.getenv('RUNPOD_USER', 'root')
    port = os.getenv('RUNPOD_PORT', '22')
    
    print("Tailing worker logs... (Press Ctrl+C to stop)")
    print("=" * 60)
    
    # Set up signal handler for graceful exit
    def signal_handler(sig, frame):
        print(f"\nLog tailing stopped by user")
        sys.exit(0)
    
    signal.signal(signal.SIGINT, signal_handler)
    
    try:
        # Use SSH with tail -f for real-time log streaming
        subprocess.run([
            'ssh', '-p', port, f'{user}@{host}',
            'tail -f /workspace/worker_output.log 2>/dev/null || (echo "No log file found yet, waiting..." && sleep 2 && tail -f /workspace/worker_output.log)'
        ], check=True)
        
    except subprocess.CalledProcessError as e:
        print(f"ERROR: Log tailing failed: {e}")
    except Exception as e:
        print(f"ERROR: Error tailing logs: {e}")

def check_worker_status():
    """Check current worker status"""
    host = os.getenv('RUNPOD_HOST')
    user = os.getenv('RUNPOD_USER', 'root')
    port = os.getenv('RUNPOD_PORT', '22')
    
    print("Checking worker status...")
    
    try:
        # Check if worker process is running
        pid_result = subprocess.run([
            'ssh', '-p', port, f'{user}@{host}', 
            'if [ -f /workspace/worker.pid ]; then cat /workspace/worker.pid; else echo "no-pid"; fi'
        ], capture_output=True, text=True, timeout=5)
        
        if pid_result.returncode == 0:
            pid = pid_result.stdout.strip()
            if pid != "no-pid":
                # Check if process is actually running
                ps_result = subprocess.run([
                    'ssh', '-p', port, f'{user}@{host}',
                    f'ps -p {pid} -o pid,cmd --no-headers 2>/dev/null || echo "not-running"'
                ], capture_output=True, text=True, timeout=5)
                
                if ps_result.returncode == 0 and "not-running" not in ps_result.stdout:
                    print(f"✅ Worker is RUNNING (PID: {pid})")
                    print(f"   Command: {ps_result.stdout.strip()}")
                    return True
                else:
                    print(f"❌ Worker is NOT RUNNING (stale PID: {pid})")
            else:
                print(f"❌ Worker is NOT RUNNING (no PID file)")
        
        # Show recent log output regardless
        log_result = subprocess.run([
            'ssh', '-p', port, f'{user}@{host}',
            'tail -5 /workspace/worker_output.log 2>/dev/null || echo "No log file found"'
        ], capture_output=True, text=True, timeout=5)
        
        if log_result.returncode == 0 and log_result.stdout.strip():
            print("Recent log output:")
            for line in log_result.stdout.strip().split('\n'):
                print(f"  {line}")
        
        return False
        
    except Exception as e:
        print(f"ERROR: Could not check worker status: {e}")
        return False

def stop_worker():
    """Stop the worker if running"""
    host = os.getenv('RUNPOD_HOST')
    user = os.getenv('RUNPOD_USER', 'root')
    port = os.getenv('RUNPOD_PORT', '22')
    
    print("Stopping worker...")
    
    try:
        # Stop worker processes
        result = subprocess.run([
            'ssh', '-p', port, f'{user}@{host}',
            'pkill -f "uv run.*worker.py" || true && pkill -f "python.*worker.py" || true && rm -f /workspace/worker.pid'
        ], capture_output=True, text=True, timeout=10)
        
        print("Worker stop command sent")
        
        # Wait a moment and check status
        time.sleep(2)
        if not check_worker_status():
            print("✅ Worker stopped successfully")
        else:
            print("⚠️  Worker may still be running")
        
    except Exception as e:
        print(f"ERROR: Could not stop worker: {e}")

def main():
    """Main worker execution function"""
    print("RUNPOD WORKER EXECUTION")
    print("="*50)
    print("Phase 4: Run MusicGen worker and monitor execution")
    print("Note: This assumes environment has been validated")
    print()
    
    # Parse command line arguments for different modes
    if len(sys.argv) > 1:
        command = sys.argv[1].lower()
        
        try:
            load_environment()
            
            if command == 'status':
                check_worker_status()
                return
            elif command == 'stop':
                stop_worker()
                return
            elif command == 'logs':
                tail_worker_logs()
                return
            elif command == 'start':
                pass  # Continue with normal start flow
            else:
                print(f"Unknown command: {command}")
                print("Available commands: start, stop, status, logs")
                sys.exit(1)
                
        except KeyboardInterrupt:
            print(f"\nOperation interrupted by user")
            sys.exit(1)
        except Exception as e:
            print(f"ERROR: Command failed: {e}")
            sys.exit(1)
    
    # Default behavior: start worker and monitor
    try:
        # Load environment
        load_environment()
        
        # Check SSH connection
        if not check_ssh_connection():
            print("ERROR: Cannot connect to RunPod. Check RUNPOD_HOST and SSH keys")
            sys.exit(1)
        
        # Check prerequisites
        if not check_worker_prerequisites():
            print("ERROR: Worker prerequisites not met")
            print("Run: uv run deploy/install_dependencies.py")
            sys.exit(1)
        
        # Check prompts file
        if not check_prompts_file():
            print("WARNING: No prompts.txt found - worker may have nothing to process")
        
        # Start worker
        worker_pid = start_worker()
        if not worker_pid:
            print("ERROR: Could not start worker")
            sys.exit(1)
        
        # Monitor startup
        monitor_worker_startup()
        
        print(f"\n" + "="*50)
        print(f"WORKER STARTED SUCCESSFULLY!")
        print("="*50)
        print(f"Worker PID: {worker_pid}")
        print()
        print("Management commands:")
        print(f"  Check status: uv run deploy/run_worker.py status")
        print(f"  View logs:    uv run deploy/run_worker.py logs")
        print(f"  Stop worker:  uv run deploy/run_worker.py stop")
        print()
        print("The worker is now processing in the background.")
        print("Use the logs command to monitor progress.")
        
    except KeyboardInterrupt:
        print("\nWorker execution interrupted by user")
        sys.exit(1)
    except Exception as e:
        print(f"ERROR: Worker execution failed: {e}")
        sys.exit(1)

if __name__ == '__main__':
    main()
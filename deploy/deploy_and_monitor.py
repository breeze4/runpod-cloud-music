#!/usr/bin/env python3
"""
Deploy and Monitor Script

Combines deployment and monitoring into a single workflow.
1. Deploys code to RunPod pod
2. Starts MusicGen worker
3. Monitors worker logs in real-time
4. Shows completion summary

Reads configuration from .env file.
"""

import os
import sys
import subprocess
import signal
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

def run_deployment():
    """Run the deployment script"""
    print("STEP 1: DEPLOYING TO RUNPOD")
    print("="*50)
    
    deploy_script = Path(__file__).parent / 'deploy_to_pod.py'
    
    if not deploy_script.exists():
        print("ERROR: deploy_to_pod.py not found")
        return False
    
    try:
        # Run deployment script
        result = subprocess.run([
            sys.executable, str(deploy_script)
        ], timeout=300)  # 5 minute timeout
        
        return result.returncode == 0
        
    except subprocess.TimeoutExpired:
        print("ERROR: Deployment timed out (5 minutes)")
        return False
    except Exception as e:
        print(f"ERROR: Deployment failed: {e}")
        return False

def start_worker():
    """Start the MusicGen worker on the pod"""
    host = os.getenv('RUNPOD_HOST')
    user = os.getenv('RUNPOD_USER', 'root')
    port = os.getenv('RUNPOD_PORT', '22')
    
    print("\n STEP 2: STARTING MUSICGEN WORKER")
    print("="*50)
    
    # Check if prompts.txt exists
    if not Path('prompts.txt').exists():
        print("WARNING: prompts.txt not found - worker will have no jobs to process")
        print("Create prompts.txt with your music generation requests")
        return None
    
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

def monitor_worker(worker_pid):
    """Monitor the worker process and logs"""
    host = os.getenv('RUNPOD_HOST')
    user = os.getenv('RUNPOD_USER', 'root')
    port = os.getenv('RUNPOD_PORT', '22')
    
    print(f"\n STEP 3: MONITORING WORKER (PID: {worker_pid})")
    print("="*50)
    print("Streaming worker logs... (Press Ctrl+C to stop monitoring)")
    print("-" * 50)
    
    try:
        # Monitor command that follows the log and checks process status
        monitor_command = f'''
cd /workspace &&
tail -f musicgen-worker.log worker_output.log 2>/dev/null &
TAIL_PID=$!

# Function to check if worker is still running
check_worker() {{
    if [ -f worker.pid ]; then
        PID=$(cat worker.pid)
        if kill -0 $PID 2>/dev/null; then
            return 0  # Process is running
        else
            echo ""
            echo "🏁 Worker process completed (PID $PID no longer running)"
            return 1  # Process finished
        fi
    else
        echo ""
        echo "🏁 Worker PID file not found - process may have completed"
        return 1
    fi
}}

# Monitor loop
while check_worker; do
    sleep 5
done

# Kill tail process
kill $TAIL_PID 2>/dev/null
echo "📋 Final worker output:"
echo "=" * 30
tail -20 worker_output.log 2>/dev/null || echo "No worker output found"
'''
        
        process = subprocess.Popen([
            'ssh', '-o', 'StrictHostKeyChecking=no',
            '-p', port,
            f'{user}@{host}', monitor_command
        ], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, 
           universal_newlines=True)
        
        # Handle Ctrl+C gracefully
        def signal_handler(sig, frame):
            print("\n🛑 Stopping monitor...")
            print("WARNING: Worker may still be running on pod")
            process.terminate()
            sys.exit(0)
        
        signal.signal(signal.SIGINT, signal_handler)
        
        # Stream output
        for line in iter(process.stdout.readline, ''):
            if line:
                print(line.rstrip())
        
        process.wait()
        
    except Exception as e:
        print(f"ERROR: Error monitoring worker: {e}")

def show_completion_summary():
    """Show final completion summary"""
    host = os.getenv('RUNPOD_HOST')
    user = os.getenv('RUNPOD_USER', 'root')
    port = os.getenv('RUNPOD_PORT', '22')
    
    print("\n📊 STEP 4: COMPLETION SUMMARY")
    print("="*50)
    
    try:
        # Check for completion report
        summary_commands = [
            'ls -la /workspace/*.csv 2>/dev/null | head -5',
            'tail -20 /workspace/worker_output.log 2>/dev/null | grep -E "(SUCCESS|ERROR|completed|failed|COMPLETED)" | tail -10',
            'echo "Worker status:" && ps aux | grep worker | grep -v grep || echo "Worker process not running"'
        ]
        
        for i, cmd in enumerate(summary_commands, 1):
            result = subprocess.run([
                'ssh', '-p', port, f'{user}@{host}', cmd
            ], capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=10)
            
            if result.returncode == 0 and result.stdout.strip():
                if i == 1:
                    print("Generated reports:")
                elif i == 2:
                    print("\n📝 Recent worker messages:")
                elif i == 3:
                    print(f"\n{result.stdout.strip()}")
                
                if i < 3:
                    for line in result.stdout.strip().split('\n'):
                        if line.strip():
                            print(f"   {line}")
    
    except Exception as e:
        print(f"WARNING: Could not retrieve completion summary: {e}")
    
    print("\n" + "="*50)
    print("🎵 DEPLOY AND MONITOR COMPLETED")
    print("="*50)
    print("\nTo check results later:")
    print(f"ssh {user}@{host}")
    print("cd /workspace")
    print("ls -la *.csv          # Check for cost reports")
    print("tail worker_output.log # Check final worker output")
    print("\nOr run individual monitoring scripts:")
    print("python deploy/monitor_logs.py")
    print("python deploy/monitor_system.py") 
    print("python deploy/check_gpu.py")

def main():
    """Main deploy and monitor function"""
    print("RUNPOD DEPLOY AND MONITOR")
    print("="*60)
    
    try:
        # Load environment
        load_environment()
        host = os.getenv('RUNPOD_HOST')
        port = os.getenv('RUNPOD_PORT', '22')
        print(f"Target: {host}:{port}")
        print()
        
        # Step 1: Deploy
        if not run_deployment():
            print("ERROR: Deployment failed - cannot continue")
            sys.exit(1)
        
        # Small delay to ensure deployment is complete
        print("Waiting 3 seconds for deployment to settle...")
        time.sleep(3)
        
        # Step 2: Start worker
        worker_pid = start_worker()
        if not worker_pid:
            print("ERROR: Could not start worker")
            sys.exit(1)
        
        # Small delay before monitoring
        print("Waiting 5 seconds for worker to initialize...")
        time.sleep(5)
        
        # Step 3: Monitor
        monitor_worker(worker_pid)
        
        # Step 4: Summary
        show_completion_summary()
        
    except KeyboardInterrupt:
        print("\nDeploy and monitor interrupted")
        print("WARNING: Worker may still be running on pod")
    except Exception as e:
        print(f"ERROR: Deploy and monitor failed: {e}")
        sys.exit(1)

if __name__ == '__main__':
    main()
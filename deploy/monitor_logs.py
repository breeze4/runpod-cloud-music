#!/usr/bin/env python3
"""
Log Monitor Script

Monitors MusicGen worker logs on RunPod pod in real-time.
Reads configuration from .env file.
"""

import os
import sys
import subprocess
import signal
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

def check_ssh_connection():
    """Test SSH connection to RunPod"""
    host = os.getenv('RUNPOD_HOST')
    user = os.getenv('RUNPOD_USER', 'root')
    
    try:
        result = subprocess.run([
            'ssh', '-o', 'ConnectTimeout=5', 
            '-o', 'StrictHostKeyChecking=no',
            f'{user}@{host}', 
            'echo "Connection OK"'
        ], capture_output=True, text=True, timeout=10)
        
        return result.returncode == 0
        
    except:
        return False

def monitor_worker_logs():
    """Monitor worker logs in real-time"""
    host = os.getenv('RUNPOD_HOST')
    user = os.getenv('RUNPOD_USER', 'root')
    
    print(f"🔍 Monitoring MusicGen worker logs on {host}")
    print("Press Ctrl+C to stop monitoring")
    print("="*60)
    
    # Try multiple log locations
    log_locations = [
        '/var/log/musicgen-worker.log',
        '~/musicgen-worker.log',
        '/workspace/musicgen-worker.log'
    ]
    
    # Find which log file exists
    log_file = None
    for location in log_locations:
        try:
            result = subprocess.run([
                'ssh', f'{user}@{host}', 
                f'test -f {location} && echo "exists"'
            ], capture_output=True, text=True, timeout=5)
            
            if result.returncode == 0 and 'exists' in result.stdout:
                log_file = location
                break
        except:
            continue
    
    if not log_file:
        print("⚠️  No worker log file found. Starting general monitoring...")
        log_file = '/var/log/musicgen-worker.log'
    else:
        print(f"📋 Found log file: {log_file}")
    
    try:
        # Start tailing the log file
        cmd = [
            'ssh', '-o', 'StrictHostKeyChecking=no',
            f'{user}@{host}', 
            f'tail -f {log_file} 2>/dev/null || tail -f ~/musicgen-worker.log 2>/dev/null || echo "No log file found. Worker may not be running yet."'
        ]
        
        process = subprocess.Popen(cmd, stdout=subprocess.PIPE, 
                                 stderr=subprocess.STDOUT, 
                                 universal_newlines=True)
        
        # Handle Ctrl+C gracefully
        def signal_handler(sig, frame):
            print("\n🛑 Stopping log monitor...")
            process.terminate()
            sys.exit(0)
        
        signal.signal(signal.SIGINT, signal_handler)
        
        # Stream output
        for line in iter(process.stdout.readline, ''):
            if line:
                print(line.rstrip())
        
        process.wait()
        
    except Exception as e:
        print(f"❌ Error monitoring logs: {e}")
        sys.exit(1)

def main():
    """Main monitoring function"""
    try:
        load_environment()
        
        if not check_ssh_connection():
            print("❌ Cannot connect to RunPod. Check RUNPOD_HOST and SSH keys")
            sys.exit(1)
        
        monitor_worker_logs()
        
    except KeyboardInterrupt:
        print("\n🛑 Log monitoring stopped")
    except Exception as e:
        print(f"❌ Monitor failed: {e}")
        sys.exit(1)

if __name__ == '__main__':
    main()
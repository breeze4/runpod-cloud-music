#!/usr/bin/env python3
"""
System Monitor Script

Monitors system resources and logs on RunPod pod in real-time.
Shows CPU, memory, disk, and system logs.
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

def get_system_info():
    """Get current system information"""
    host = os.getenv('RUNPOD_HOST')
    user = os.getenv('RUNPOD_USER', 'root')
    
    commands = {
        'CPU Usage': "top -bn1 | grep 'Cpu(s)' | awk '{print $2}' | awk -F'%' '{print $1}'",
        'Memory': "free -h | grep '^Mem' | awk '{printf \"Used: %s / %s (%.1f%%)\", $3, $2, ($3/$2)*100}'",
        'Disk Space': "df -h /workspace 2>/dev/null | tail -1 | awk '{printf \"Used: %s / %s (%s)\", $3, $2, $5}' || df -h / | tail -1 | awk '{printf \"Used: %s / %s (%s)\", $3, $2, $5}'",
        'GPU Status': "nvidia-smi --query-gpu=name,memory.used,memory.total,utilization.gpu --format=csv,noheader 2>/dev/null || echo 'No GPU detected'"
    }
    
    info = {}
    for name, cmd in commands.items():
        try:
            result = subprocess.run([
                'ssh', '-o', 'StrictHostKeyChecking=no',
                f'{user}@{host}', cmd
            ], capture_output=True, text=True, timeout=5)
            
            if result.returncode == 0:
                info[name] = result.stdout.strip()
            else:
                info[name] = "N/A"
                
        except:
            info[name] = "Error"
    
    return info

def monitor_system_logs():
    """Monitor system logs in real-time"""
    host = os.getenv('RUNPOD_HOST')
    user = os.getenv('RUNPOD_USER', 'root')
    
    print(f"🖥️  Monitoring system resources on {host}")
    print("Press Ctrl+C to stop monitoring")
    print("="*80)
    
    try:
        while True:
            # Clear screen
            os.system('clear' if os.name == 'posix' else 'cls')
            
            print(f"🖥️  System Monitor - {host}")
            print(f"⏰ {time.strftime('%Y-%m-%d %H:%M:%S')}")
            print("="*80)
            
            # Get system info
            info = get_system_info()
            
            # Display info in organized way
            print("📊 RESOURCE USAGE:")
            print(f"   CPU:    {info.get('CPU Usage', 'N/A')}%")
            print(f"   Memory: {info.get('Memory', 'N/A')}")
            print(f"   Disk:   {info.get('Disk Space', 'N/A')}")
            print()
            
            print("🎮 GPU STATUS:")
            gpu_info = info.get('GPU Status', 'N/A')
            if 'No GPU detected' not in gpu_info and gpu_info != 'N/A':
                parts = gpu_info.split(', ')
                if len(parts) >= 4:
                    print(f"   Name:         {parts[0]}")
                    print(f"   Memory Used:  {parts[1]} / {parts[2]}")
                    print(f"   GPU Usage:    {parts[3]}%")
                else:
                    print(f"   Status: {gpu_info}")
            else:
                print(f"   Status: {gpu_info}")
            print()
            
            # Show running processes
            try:
                result = subprocess.run([
                    'ssh', '-o', 'StrictHostKeyChecking=no',
                    f'{user}@{host}', 
                    "ps aux | grep -E '(python|uv|musicgen)' | grep -v grep | head -5"
                ], capture_output=True, text=True, timeout=5)
                
                if result.returncode == 0 and result.stdout.strip():
                    print("🔄 ACTIVE PROCESSES:")
                    for line in result.stdout.strip().split('\n'):
                        if line.strip():
                            parts = line.split()
                            if len(parts) >= 11:
                                user_col = parts[0][:8]
                                cpu_col = parts[2]
                                mem_col = parts[3]
                                cmd_col = ' '.join(parts[10:])[:50]
                                print(f"   {user_col:<8} CPU:{cpu_col:>5}% MEM:{mem_col:>5}% {cmd_col}")
                else:
                    print("🔄 ACTIVE PROCESSES: No Python/MusicGen processes found")
            except:
                print("🔄 ACTIVE PROCESSES: Unable to check")
            
            print()
            print("="*80)
            print("Refreshing in 5 seconds... (Ctrl+C to stop)")
            
            time.sleep(5)
    
    except KeyboardInterrupt:
        print("\n🛑 System monitoring stopped")
    except Exception as e:
        print(f"❌ Error monitoring system: {e}")

def main():
    """Main monitoring function"""
    try:
        load_environment()
        
        if not check_ssh_connection():
            print("❌ Cannot connect to RunPod. Check RUNPOD_HOST and SSH keys")
            sys.exit(1)
        
        monitor_system_logs()
        
    except KeyboardInterrupt:
        print("\n🛑 System monitoring stopped")
    except Exception as e:
        print(f"❌ Monitor failed: {e}")
        sys.exit(1)

if __name__ == '__main__':
    main()
#!/usr/bin/env python3
"""
GPU Check Script

Checks GPU status and availability on RunPod pod.
Shows detailed GPU information and PyTorch CUDA compatibility.
Reads configuration from .env file.
"""

import os
import sys
import subprocess
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

def run_remote_command(command, timeout=10):
    """Run a command on the remote pod"""
    host = os.getenv('RUNPOD_HOST')
    user = os.getenv('RUNPOD_USER', 'root')
    
    try:
        result = subprocess.run([
            'ssh', '-o', 'StrictHostKeyChecking=no',
            f'{user}@{host}', command
        ], capture_output=True, text=True, timeout=timeout)
        
        return result.returncode == 0, result.stdout, result.stderr
        
    except Exception as e:
        return False, "", str(e)

def check_gpu_hardware():
    """Check GPU hardware information"""
    print("🎮 GPU HARDWARE CHECK")
    print("="*50)
    
    # Check nvidia-smi
    success, stdout, stderr = run_remote_command("nvidia-smi")
    
    if success:
        print("✅ nvidia-smi available")
        print("\nGPU Information:")
        print("-" * 30)
        print(stdout)
    else:
        print("❌ nvidia-smi not available")
        print(f"Error: {stderr}")
        return False
    
    # Get detailed GPU info
    success, stdout, stderr = run_remote_command(
        "nvidia-smi --query-gpu=name,memory.total,memory.free,memory.used,temperature.gpu,power.draw --format=csv"
    )
    
    if success:
        print("\nDetailed GPU Status:")
        print("-" * 30)
        lines = stdout.strip().split('\n')
        if len(lines) > 1:
            headers = lines[0].split(', ')
            values = lines[1].split(', ')
            
            for header, value in zip(headers, values):
                print(f"{header:20}: {value}")
    
    return True

def check_cuda_drivers():
    """Check CUDA driver version"""
    print("\n🔧 CUDA DRIVER CHECK")
    print("="*50)
    
    success, stdout, stderr = run_remote_command("nvidia-smi | grep 'CUDA Version' | awk '{print $9}'")
    
    if success and stdout.strip():
        cuda_version = stdout.strip()
        print(f"✅ CUDA Driver Version: {cuda_version}")
    else:
        print("❌ Could not determine CUDA driver version")
        return False
    
    return True

def check_pytorch_cuda():
    """Check PyTorch CUDA compatibility"""
    print("\n🐍 PYTORCH CUDA CHECK")
    print("="*50)
    
    # Check if we can run Python
    python_check = '''
python3 -c "
import sys
print(f'Python version: {sys.version}')

try:
    import torch
    print(f'PyTorch version: {torch.__version__}')
    print(f'CUDA available: {torch.cuda.is_available()}')
    if torch.cuda.is_available():
        print(f'CUDA version: {torch.version.cuda}')
        print(f'GPU count: {torch.cuda.device_count()}')
        for i in range(torch.cuda.device_count()):
            print(f'GPU {i}: {torch.cuda.get_device_name(i)}')
    else:
        print('CUDA not available in PyTorch')
except ImportError as e:
    print(f'PyTorch not installed: {e}')
    
try:
    import transformers
    print(f'Transformers version: {transformers.__version__}')
except ImportError:
    print('Transformers not installed')
"
'''
    
    success, stdout, stderr = run_remote_command(python_check, timeout=20)
    
    if success:
        print("Python Environment Check:")
        print("-" * 30)
        print(stdout)
    else:
        print("❌ Could not run Python check")
        print(f"Error: {stderr}")
        
        # Try alternative with workspace environment
        print("\nTrying with workspace environment...")
        workspace_check = f"cd /workspace && uv run python3 -c \"{python_check.split('\"')[1]}\""
        success2, stdout2, stderr2 = run_remote_command(workspace_check, timeout=30)
        
        if success2:
            print("Workspace Python Environment:")
            print("-" * 30)
            print(stdout2)
        else:
            print("❌ Workspace Python check also failed")
            print(f"Error: {stderr2}")

def test_model_loading():
    """Test if MusicGen model can be loaded (dry run)"""
    print("\n🎵 MUSICGEN MODEL CHECK")
    print("="*50)
    
    model_test = '''
python3 -c "
import torch
print('Testing GPU memory allocation...')

if torch.cuda.is_available():
    device = torch.device('cuda')
    print(f'Using device: {device}')
    
    # Test memory allocation
    try:
        x = torch.randn(1000, 1000, device=device)
        print('✅ GPU memory allocation successful')
        
        # Check available memory
        total_mem = torch.cuda.get_device_properties(0).total_memory / 1024**3
        reserved_mem = torch.cuda.memory_reserved(0) / 1024**3
        allocated_mem = torch.cuda.memory_allocated(0) / 1024**3
        
        print(f'Total GPU memory: {total_mem:.1f} GB')
        print(f'Reserved memory: {reserved_mem:.1f} GB') 
        print(f'Allocated memory: {allocated_mem:.1f} GB')
        print(f'Available memory: {total_mem - reserved_mem:.1f} GB')
        
        if total_mem >= 6.0:
            print('✅ Sufficient memory for MusicGen-medium (~6GB)')
        else:
            print('⚠️ May not have enough memory for MusicGen-medium')
            
        del x
        torch.cuda.empty_cache()
        
    except Exception as e:
        print(f'❌ GPU memory test failed: {e}')
        
else:
    print('❌ CUDA not available')
"
'''
    
    success, stdout, stderr = run_remote_command(model_test, timeout=30)
    
    if success:
        print("GPU Memory Test:")
        print("-" * 30)
        print(stdout)
    else:
        print("❌ Could not run GPU memory test")
        print(f"Error: {stderr}")

def main():
    """Main GPU check function"""
    print("🎮 RUNPOD GPU STATUS CHECK")
    print("="*60)
    
    try:
        load_environment()
        
        host = os.getenv('RUNPOD_HOST')
        print(f"Checking GPU on: {host}")
        print()
        
        if not check_ssh_connection():
            print("❌ Cannot connect to RunPod. Check RUNPOD_HOST and SSH keys")
            sys.exit(1)
        
        # Run all checks
        gpu_ok = check_gpu_hardware()
        cuda_ok = check_cuda_drivers()
        check_pytorch_cuda()
        
        if gpu_ok and cuda_ok:
            test_model_loading()
        
        print("\n" + "="*60)
        print("🎮 GPU CHECK COMPLETE")
        
        if gpu_ok and cuda_ok:
            print("✅ GPU setup looks good for MusicGen!")
        else:
            print("⚠️  GPU setup may have issues")
        
        print("="*60)
        
    except KeyboardInterrupt:
        print("\n🛑 GPU check interrupted")
    except Exception as e:
        print(f"❌ GPU check failed: {e}")
        sys.exit(1)

if __name__ == '__main__':
    main()
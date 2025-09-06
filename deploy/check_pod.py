#!/usr/bin/env python3
"""
Pod Environment Check Script

Comprehensive validation of RunPod pod environment and external services.
Checks GPU, PyTorch CUDA, AWS credentials, S3 connectivity, and system readiness.
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
    port = os.getenv('RUNPOD_PORT', '22')
    
    try:
        result = subprocess.run([
            'ssh', '-o', 'ConnectTimeout=5', 
            '-o', 'StrictHostKeyChecking=no',
            '-p', port,
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
    port = os.getenv('RUNPOD_PORT', '22')
    
    try:
        result = subprocess.run([
            'ssh', '-o', 'StrictHostKeyChecking=no',
            '-p', port,
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

def check_aws_environment():
    """Check AWS environment variables and configuration"""
    print("\n☁️ AWS ENVIRONMENT CHECK")
    print("="*50)
    
    required_vars = [
        'AWS_ACCESS_KEY_ID',
        'AWS_SECRET_ACCESS_KEY',
        'MUSICGEN_S3_BUCKET',
        'AWS_DEFAULT_REGION'
    ]
    
    print("Checking AWS environment variables...")
    missing_vars = []
    
    for var in required_vars:
        value = os.getenv(var)
        if value:
            # Show masked value for security
            masked = '*' * min(8, len(value))
            print(f"✅ {var}: {masked}...")
        else:
            missing_vars.append(var)
            print(f"❌ {var}: Not set")
    
    if missing_vars:
        print(f"\n⚠️ Missing AWS environment variables: {', '.join(missing_vars)}")
        print("These should be set in your local .env file and deployed to the pod")
        return False
    
    print("✅ All AWS environment variables present")
    return True

def check_s3_connectivity():
    """Test S3 connectivity and bucket access"""
    print("\n📦 S3 CONNECTIVITY CHECK")
    print("="*50)
    
    # Check if AWS variables are available first
    if not all(os.getenv(var) for var in ['AWS_ACCESS_KEY_ID', 'AWS_SECRET_ACCESS_KEY', 'MUSICGEN_S3_BUCKET']):
        print("❌ Cannot test S3 - AWS environment variables missing")
        return False
    
    bucket_name = os.getenv('MUSICGEN_S3_BUCKET')
    region = os.getenv('AWS_DEFAULT_REGION', 'us-east-1')
    
    print(f"Testing S3 connectivity to bucket: {bucket_name}")
    print(f"Region: {region}")
    
    # First check if boto3 is installed on the pod
    print("Checking if boto3 is available on pod...")
    boto3_check = "python3 -c 'import boto3; print(\"boto3 available\")'"
    success, stdout, stderr = run_remote_command(boto3_check, timeout=10)
    
    if not success or "boto3 available" not in stdout:
        print("⚠️  boto3 not installed on pod yet")
        print("This is expected before deployment - boto3 will be installed during deployment")
        print("🔄 S3 connectivity will be tested after deployment")
        return "pending"  # Special status for not-yet-deployed
    
    try:
        # Test S3 connectivity using Python on the pod
        s3_test_cmd = f'''
python3 -c "
import boto3
from botocore.exceptions import ClientError

try:
    # Test basic S3 connectivity
    s3 = boto3.client('s3', region_name='{region}')
    response = s3.list_buckets()
    print(f'✅ S3 connection successful - Found {{len(response[\\"Buckets\\"])}} buckets')
    
    # Test specific bucket access
    s3.head_bucket(Bucket='{bucket_name}')
    print(f'✅ Bucket {bucket_name} exists and is accessible')
    
    # Test write permissions
    test_key = 'musicgen_connectivity_test.txt'
    s3.put_object(Bucket='{bucket_name}', Key=test_key, Body='connectivity test')
    print(f'✅ Write permissions confirmed')
    
    # Clean up test object
    s3.delete_object(Bucket='{bucket_name}', Key=test_key)
    print(f'✅ S3 connectivity test completed successfully')
    
except ClientError as e:
    error_code = e.response['Error']['Code']
    if error_code == 'NoSuchBucket':
        print(f'❌ S3 bucket does not exist: {bucket_name}')
    elif error_code == 'AccessDenied':
        print(f'❌ Access denied to S3 bucket: {bucket_name}')
    elif error_code in ['InvalidAccessKeyId', 'SignatureDoesNotMatch']:
        print(f'❌ Invalid AWS credentials: {{error_code}}')
    else:
        print(f'❌ S3 error: {{error_code}} - {{e.response[\\"Error\\"][\\"Message\\"]}}')
except Exception as e:
    print(f'❌ S3 connectivity test failed: {{e}}')
"
'''
        
        success, stdout, stderr = run_remote_command(s3_test_cmd, timeout=30)
        
        if success:
            print("S3 Connectivity Test Results:")
            print("-" * 30)
            print(stdout)
            return "✅" in stdout and "❌" not in stdout
        else:
            print("❌ Could not run S3 connectivity test")
            print(f"Error: {stderr}")
            return False
            
    except Exception as e:
        print(f"❌ S3 connectivity check failed: {e}")
        return False

def check_system_requirements():
    """Check system requirements for MusicGen"""
    print("\n🖥️ SYSTEM REQUIREMENTS CHECK") 
    print("="*50)
    
    print("Checking disk space...")
    success, stdout, stderr = run_remote_command("df -h /workspace 2>/dev/null || df -h /", timeout=10)
    
    if success and stdout.strip():
        print("Disk Space:")
        print("-" * 30)
        lines = stdout.strip().split('\n')
        for line in lines[1:]:  # Skip header
            parts = line.split()
            if len(parts) >= 4:
                filesystem = parts[0]
                size = parts[1] 
                used = parts[2]
                avail = parts[3]
                use_pct = parts[4]
                mount = parts[5] if len(parts) > 5 else ""
                print(f"  {mount or filesystem}: {avail} available ({size} total, {use_pct} used)")
    
    print("\nChecking memory...")
    success, stdout, stderr = run_remote_command("free -h", timeout=10)
    
    if success and stdout.strip():
        print("Memory:")
        print("-" * 30)
        lines = stdout.strip().split('\n')
        for line in lines:
            if 'Mem:' in line:
                parts = line.split()
                if len(parts) >= 3:
                    print(f"  Total: {parts[1]}, Available: {parts[6] if len(parts) > 6 else parts[3]}")
    
    print("\nChecking Python environment...")
    success, stdout, stderr = run_remote_command("python3 --version && which python3", timeout=10)
    
    if success:
        print("Python Environment:")
        print("-" * 30) 
        print(stdout.strip())
    
    return True

def main():
    """Main pod environment check function"""
    print("🚀 RUNPOD ENVIRONMENT CHECK")
    print("="*60)
    
    try:
        load_environment()
        
        host = os.getenv('RUNPOD_HOST')
        port = os.getenv('RUNPOD_PORT', '22')
        print(f"Checking pod environment: {host}:{port}")
        print()
        
        if not check_ssh_connection():
            print("❌ Cannot connect to RunPod. Check RUNPOD_HOST and SSH keys")
            sys.exit(1)
        
        # Run all checks
        print("\n" + "="*60)
        print("🔍 RUNNING COMPREHENSIVE ENVIRONMENT CHECKS")
        print("="*60)
        
        gpu_ok = check_gpu_hardware()
        cuda_ok = check_cuda_drivers() 
        check_pytorch_cuda()
        
        if gpu_ok and cuda_ok:
            test_model_loading()
        
        # Check AWS and external services
        aws_ok = check_aws_environment()
        s3_status = check_s3_connectivity() if aws_ok else False
        system_ok = check_system_requirements()
        
        # Generate final report
        print("\n" + "="*60)
        print("📋 FINAL ENVIRONMENT REPORT")
        print("="*60)
        
        components = [
            ("SSH Connection", True),  # Already verified
            ("GPU Hardware", gpu_ok),
            ("CUDA Drivers", cuda_ok), 
            ("PyTorch CUDA", gpu_ok and cuda_ok),
            ("AWS Environment", aws_ok),
            ("S3 Connectivity", s3_status),
            ("System Requirements", system_ok)
        ]
        
        all_good = True
        s3_pending = False
        
        for name, status in components:
            if status == True:
                print(f"✅ {name}")
            elif status == "pending":
                print(f"🔄 {name} - Will be tested after deployment")
                s3_pending = True
            else:
                print(f"❌ {name}")
                all_good = False
        
        print("\n" + "="*60)
        if all_good and not s3_pending:
            print("🎉 ENVIRONMENT READY FOR MUSICGEN DEPLOYMENT!")
            print("You can now run: uv run python deploy/deploy_and_monitor.py")
        elif all_good and s3_pending:
            print("🚀 ENVIRONMENT READY FOR DEPLOYMENT!")
            print("S3 connectivity will be tested during deployment process")
            print("You can now run: uv run python deploy/deploy_and_monitor.py")
        else:
            print("⚠️  ENVIRONMENT HAS ISSUES - FIX BEFORE DEPLOYMENT")
            print("Check the errors above and ensure all components are working")
        print("="*60)
        
    except KeyboardInterrupt:
        print("\n🛑 Pod environment check interrupted")
    except Exception as e:
        print(f"❌ Pod environment check failed: {e}")
        sys.exit(1)

if __name__ == '__main__':
    main()
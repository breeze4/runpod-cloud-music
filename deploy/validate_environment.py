#!/usr/bin/env python3
"""
RunPod Environment Validation Script

Phase 3: Validate environment and dependencies on RunPod pod.
Runs comprehensive checks for AWS, dependencies, GPU, and S3 connectivity.
Can be run locally to remotely execute validation on the pod.
"""

import os
import sys
import subprocess
from pathlib import Path
from dotenv import load_dotenv

def check_aws_environment():
    """Check AWS environment variables"""
    print("[AWS] Checking AWS Environment...")
    required_vars = ['AWS_ACCESS_KEY_ID', 'AWS_SECRET_ACCESS_KEY', 'MUSICGEN_S3_BUCKET', 'AWS_DEFAULT_REGION']
    
    missing = []
    for var in required_vars:
        value = os.getenv(var)
        if not value or not value.strip().strip('\r\n').strip():
            missing.append(var)
        else:
            # Clean the environment variable by removing line endings
            cleaned_value = value.strip().strip('\r\n').strip()
            os.environ[var] = cleaned_value
    
    if missing:
        print(f"[FAIL] Missing AWS variables: {', '.join(missing)}")
        return False
    else:
        print("[OK] AWS environment variables present")
        return True

def check_s3_connectivity():
    """Test S3 connectivity and bucket access"""
    print("[S3] Testing S3 Connectivity...")
    
    try:
        import boto3
        from botocore.exceptions import ClientError
        
        bucket_name = os.getenv('MUSICGEN_S3_BUCKET', '').strip().strip('\r\n').strip()
        region = os.getenv('AWS_DEFAULT_REGION', 'us-east-1').strip().strip('\r\n').strip()
        
        # Test basic S3 connectivity
        s3 = boto3.client('s3', region_name=region)
        response = s3.list_buckets()
        print(f"[OK] S3 connection successful - Found {len(response['Buckets'])} buckets")
        
        # Test specific bucket access
        s3.head_bucket(Bucket=bucket_name)
        print(f"[OK] Bucket '{bucket_name}' exists and is accessible in region '{region}'")
        
        # Test write permissions
        try:
            test_key = 'musicgen_deployment_test.txt'
            s3.put_object(Bucket=bucket_name, Key=test_key, Body='deployment validation test')
            print("[OK] Write permissions confirmed")
            
            # Clean up test object
            s3.delete_object(Bucket=bucket_name, Key=test_key)
            print("[OK] S3 connectivity test completed successfully")
        except ClientError as write_error:
            write_error_code = write_error.response['Error']['Code']
            if write_error_code == 'AccessDenied':
                print(f"[FAIL] Write access denied to bucket '{bucket_name}'")
                print("[FAIL] AWS credentials need s3:PutObject and s3:DeleteObject permissions")
                raise write_error
            else:
                print(f"[FAIL] Write test failed: {write_error_code}")
                raise write_error
        
        return True
        
    except ImportError:
        print("[FAIL] boto3 not available")
        return False
    except ClientError as e:
        error_code = e.response['Error']['Code']
        error_message = e.response['Error']['Message']
        if error_code == '404':
            print(f"[FAIL] S3 bucket '{bucket_name}' not found in region '{region}'")
            print(f"[FAIL] This suggests the deployment bucket creation step failed")
            print(f"[FAIL] Check: 1) AWS credentials have S3 permissions, 2) Region '{region}' is correct")
        else:
            print(f"[FAIL] S3 error {error_code}: {error_message}")
        return False
    except Exception as e:
        print(f"[FAIL] S3 test failed: {e}")
        return False

def check_dependencies():
    """Check that all required dependencies are installed"""
    print("[DEPS] Checking Dependencies...")
    
    required_modules = ['torch', 'transformers', 'soundfile', 'numpy', 'boto3']
    missing = []
    
    for module in required_modules:
        try:
            __import__(module)
            print(f"[OK] {module}")
        except ImportError:
            print(f"[FAIL] {module}")
            missing.append(module)
    
    if missing:
        print(f"[FAIL] Missing dependencies: {', '.join(missing)}")
        return False
    else:
        print("[OK] All dependencies available")
        return True

def check_gpu_torch():
    """Check GPU and PyTorch integration"""
    print("[GPU] Checking GPU and PyTorch...")
    
    try:
        import torch
        
        if torch.cuda.is_available():
            gpu_count = torch.cuda.device_count()
            gpu_name = torch.cuda.get_device_name(0)
            print(f"[OK] CUDA available - {gpu_count} GPU(s)")
            print(f"[OK] Primary GPU: {gpu_name}")
            
            # Test memory allocation
            x = torch.randn(100, 100, device='cuda')
            print("[OK] GPU memory allocation successful")
            del x
            torch.cuda.empty_cache()
            
            return True
        else:
            print("[FAIL] CUDA not available")
            return False
            
    except Exception as e:
        print(f"[FAIL] GPU/PyTorch test failed: {e}")
        return False

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

def create_validation_script():
    """Create the validation script content to be executed on pod"""
    return f'''#!/usr/bin/env python3
"""
Validation script to be executed on RunPod pod.
"""

import os
import sys

{check_aws_environment.__code__.co_code}
{check_s3_connectivity.__code__.co_code}
{check_dependencies.__code__.co_code}
{check_gpu_torch.__code__.co_code}

def main():
    """Run all validation checks"""
    print("[VALIDATE] ENVIRONMENT VALIDATION")
    print("="*50)
    
    # Source environment variables first
    print("Loading environment variables...")
    
    aws_ok = check_aws_environment()
    deps_ok = check_dependencies()
    gpu_ok = check_gpu_torch()
    s3_ok = check_s3_connectivity() if aws_ok and deps_ok else False
    
    print("\\n[VALIDATION SUMMARY]")
    print("="*30)
    print(f"AWS Environment: {{'OK' if aws_ok else 'FAILED'}}")
    print(f"Dependencies: {{'OK' if deps_ok else 'FAILED'}}")
    print(f"GPU/PyTorch: {{'OK' if gpu_ok else 'FAILED'}}")
    print(f"S3 Connectivity: {{'OK' if s3_ok else 'FAILED'}}")
    
    all_good = aws_ok and deps_ok and gpu_ok and s3_ok
    
    print("\\n" + "="*50)
    if all_good:
        print("[SUCCESS] ENVIRONMENT VALIDATION SUCCESSFUL!")
        print("Environment is ready for MusicGen processing")
    else:
        print("[FAILED] ENVIRONMENT VALIDATION FAILED!")
        print("Check the errors above before proceeding")
        
    print("="*50)
    sys.exit(0 if all_good else 1)

if __name__ == '__main__':
    main()
'''

def run_remote_validation():
    """Upload validation script to pod and execute it"""
    host = os.getenv('RUNPOD_HOST')
    user = os.getenv('RUNPOD_USER', 'root')
    port = os.getenv('RUNPOD_PORT', '22')
    
    print("Running comprehensive environment validation on pod...")
    print("="*60)
    
    try:
        # Create validation script content
        import tempfile
        
        # Create the actual validation script by copying the function definitions
        validation_script_content = '''#!/usr/bin/env python3
"""
Validation script to be executed on RunPod pod.
"""

import os
import sys

def check_aws_environment():
    """Check AWS environment variables"""
    print("[AWS] Checking AWS Environment...")
    required_vars = ['AWS_ACCESS_KEY_ID', 'AWS_SECRET_ACCESS_KEY', 'MUSICGEN_S3_BUCKET', 'AWS_DEFAULT_REGION']
    
    missing = []
    for var in required_vars:
        value = os.getenv(var)
        if not value or not value.strip().strip('\\r\\n').strip():
            missing.append(var)
        else:
            # Clean the environment variable by removing line endings
            cleaned_value = value.strip().strip('\\r\\n').strip()
            os.environ[var] = cleaned_value
    
    if missing:
        print(f"[FAIL] Missing AWS variables: {', '.join(missing)}")
        return False
    else:
        print("[OK] AWS environment variables present")
        return True

def check_s3_connectivity():
    """Test S3 connectivity and bucket access"""
    print("[S3] Testing S3 Connectivity...")
    
    try:
        import boto3
        from botocore.exceptions import ClientError
        
        bucket_name = os.getenv('MUSICGEN_S3_BUCKET', '').strip().strip('\\r\\n').strip()
        region = os.getenv('AWS_DEFAULT_REGION', 'us-east-1').strip().strip('\\r\\n').strip()
        
        # Test basic S3 connectivity
        s3 = boto3.client('s3', region_name=region)
        response = s3.list_buckets()
        print(f"[OK] S3 connection successful - Found {len(response['Buckets'])} buckets")
        
        # Test specific bucket access
        s3.head_bucket(Bucket=bucket_name)
        print(f"[OK] Bucket '{bucket_name}' exists and is accessible in region '{region}'")
        
        # Test write permissions
        try:
            test_key = 'musicgen_deployment_test.txt'
            s3.put_object(Bucket=bucket_name, Key=test_key, Body='deployment validation test')
            print("[OK] Write permissions confirmed")
            
            # Clean up test object
            s3.delete_object(Bucket=bucket_name, Key=test_key)
            print("[OK] S3 connectivity test completed successfully")
        except ClientError as write_error:
            write_error_code = write_error.response['Error']['Code']
            if write_error_code == 'AccessDenied':
                print(f"[FAIL] Write access denied to bucket '{bucket_name}'")
                print("[FAIL] AWS credentials need s3:PutObject and s3:DeleteObject permissions")
                raise write_error
            else:
                print(f"[FAIL] Write test failed: {write_error_code}")
                raise write_error
        
        return True
        
    except ImportError:
        print("[FAIL] boto3 not available")
        return False
    except ClientError as e:
        error_code = e.response['Error']['Code']
        error_message = e.response['Error']['Message']
        if error_code == '404':
            print(f"[FAIL] S3 bucket '{bucket_name}' not found in region '{region}'")
            print(f"[FAIL] This suggests the dependency installation step failed")
            print(f"[FAIL] Check: 1) AWS credentials have S3 permissions, 2) Region '{region}' is correct")
        else:
            print(f"[FAIL] S3 error {error_code}: {error_message}")
        return False
    except Exception as e:
        print(f"[FAIL] S3 test failed: {e}")
        return False

def check_dependencies():
    """Check that all required dependencies are installed"""
    print("[DEPS] Checking Dependencies...")
    
    required_modules = ['torch', 'transformers', 'soundfile', 'numpy', 'boto3']
    missing = []
    
    for module in required_modules:
        try:
            __import__(module)
            print(f"[OK] {module}")
        except ImportError:
            print(f"[FAIL] {module}")
            missing.append(module)
    
    if missing:
        print(f"[FAIL] Missing dependencies: {', '.join(missing)}")
        return False
    else:
        print("[OK] All dependencies available")
        return True

def check_gpu_torch():
    """Check GPU and PyTorch integration"""
    print("[GPU] Checking GPU and PyTorch...")
    
    try:
        import torch
        
        if torch.cuda.is_available():
            gpu_count = torch.cuda.device_count()
            gpu_name = torch.cuda.get_device_name(0)
            print(f"[OK] CUDA available - {gpu_count} GPU(s)")
            print(f"[OK] Primary GPU: {gpu_name}")
            
            # Test memory allocation
            x = torch.randn(100, 100, device='cuda')
            print("[OK] GPU memory allocation successful")
            del x
            torch.cuda.empty_cache()
            
            return True
        else:
            print("[FAIL] CUDA not available")
            return False
            
    except Exception as e:
        print(f"[FAIL] GPU/PyTorch test failed: {e}")
        return False

def main():
    """Run all validation checks"""
    print("[VALIDATE] ENVIRONMENT VALIDATION")
    print("="*50)
    
    # Source environment variables first
    print("Loading environment variables...")
    
    aws_ok = check_aws_environment()
    deps_ok = check_dependencies()
    gpu_ok = check_gpu_torch()
    s3_ok = check_s3_connectivity() if aws_ok and deps_ok else False
    
    print("\\n[VALIDATION SUMMARY]")
    print("="*30)
    print(f"AWS Environment: {'OK' if aws_ok else 'FAILED'}")
    print(f"Dependencies: {'OK' if deps_ok else 'FAILED'}")
    print(f"GPU/PyTorch: {'OK' if gpu_ok else 'FAILED'}")
    print(f"S3 Connectivity: {'OK' if s3_ok else 'FAILED'}")
    
    all_good = aws_ok and deps_ok and gpu_ok and s3_ok
    
    print("\\n" + "="*50)
    if all_good:
        print("[SUCCESS] ENVIRONMENT VALIDATION SUCCESSFUL!")
        print("Environment is ready for MusicGen processing")
    else:
        print("[FAILED] ENVIRONMENT VALIDATION FAILED!")
        print("Check the errors above before proceeding")
        
    print("="*50)
    sys.exit(0 if all_good else 1)

if __name__ == '__main__':
    main()
'''
        
        # Write to temporary file and upload to pod
        with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False) as f:
            f.write(validation_script_content)
            temp_path = f.name
        
        # Upload validation script to pod
        subprocess.run([
            'scp', '-P', port, '-o', 'StrictHostKeyChecking=no',
            temp_path, f'{user}@{host}:/workspace/validate_environment_remote.py'
        ], check=True)
        
        # Run validation script on pod with environment
        validation_command = '''
cd /workspace &&
export PATH="$HOME/.local/bin:$HOME/.cargo/bin:$PATH" &&
source setup_env.sh &&
uv run python validate_environment_remote.py
'''
        
        result = subprocess.run([
            'ssh', '-p', port, f'{user}@{host}', validation_command
        ], timeout=60)  # 1 minute timeout
        
        # Clean up temporary files
        os.unlink(temp_path)
        subprocess.run([
            'ssh', '-p', port, f'{user}@{host}', 'rm -f /workspace/validate_environment_remote.py'
        ], capture_output=True)
        
        return result.returncode == 0
        
    except subprocess.TimeoutExpired:
        print("ERROR: Validation timed out after 60 seconds")
        return False
    except Exception as e:
        print(f"ERROR: Remote validation failed: {e}")
        return False

def main():
    """Main validation function"""
    print("RUNPOD ENVIRONMENT VALIDATION")
    print("="*50)
    print("Phase 3: Validate environment and dependencies")
    print("Note: This assumes dependencies have been installed")
    print()
    
    try:
        # Load environment
        load_environment()
        
        # Check SSH connection
        if not check_ssh_connection():
            print("ERROR: Cannot connect to RunPod. Check RUNPOD_HOST and SSH keys")
            sys.exit(1)
        
        # Run comprehensive validation
        validation_passed = run_remote_validation()
        
        print("\n" + "="*50)
        if validation_passed:
            print("ENVIRONMENT VALIDATION SUCCESSFUL!")
            print("="*50)
            print("All systems verified and ready for MusicGen processing")
            print()
            print("Next step:")
            print("Run worker: uv run deploy/run_worker.py")
        else:
            print("ENVIRONMENT VALIDATION FAILED!")
            print("="*50)
            print("Some components are not working correctly")
            print("Check the validation errors above before proceeding")
            sys.exit(1)
            
    except KeyboardInterrupt:
        print("\nEnvironment validation interrupted by user")
        sys.exit(1)
    except Exception as e:
        print(f"ERROR: Environment validation failed: {e}")
        sys.exit(1)

if __name__ == '__main__':
    main()
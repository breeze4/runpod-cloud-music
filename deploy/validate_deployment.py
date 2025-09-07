#!/usr/bin/env python3
"""
Post-deployment validation script for RunPod MusicGen deployment.
Checks AWS environment, dependencies, GPU, and S3 connectivity.
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

def main():
    """Run all validation checks"""
    print("[VALIDATE] POST-DEPLOYMENT VALIDATION")
    print("="*50)
    
    # Source environment variables first
    print("Loading environment variables...")
    
    aws_ok = check_aws_environment()
    deps_ok = check_dependencies()
    gpu_ok = check_gpu_torch()
    s3_ok = check_s3_connectivity() if aws_ok and deps_ok else False
    
    print("\n[VALIDATION SUMMARY]")
    print("="*30)
    print(f"AWS Environment: {'OK' if aws_ok else 'FAILED'}")
    print(f"Dependencies: {'OK' if deps_ok else 'FAILED'}")
    print(f"GPU/PyTorch: {'OK' if gpu_ok else 'FAILED'}")
    print(f"S3 Connectivity: {'OK' if s3_ok else 'FAILED'}")
    
    all_good = aws_ok and deps_ok and gpu_ok and s3_ok
    
    print("\n" + "="*50)
    if all_good:
        print("[SUCCESS] DEPLOYMENT VALIDATION SUCCESSFUL!")
        print("Environment is ready for MusicGen processing")
    else:
        print("[FAILED] DEPLOYMENT VALIDATION FAILED!")
        print("Check the errors above before proceeding")
        
    print("="*50)
    sys.exit(0 if all_good else 1)

if __name__ == '__main__':
    main()
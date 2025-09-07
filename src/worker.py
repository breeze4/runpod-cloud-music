#!/usr/bin/env python3
"""
MusicGen Worker Script

This script runs on EC2 instances to generate music from prompts.
It processes jobs from prompts.txt, generates audio using MusicGen,
and uploads results to S3 with cost tracking.
"""

import os
import sys
import time
import logging
import csv
import tempfile
import hashlib
from typing import List, Dict, Any, Tuple, Optional
from dataclasses import dataclass

import boto3
import torch
from transformers import MusicgenForConditionalGeneration, AutoProcessor
from botocore.exceptions import ClientError
import soundfile as sf
import numpy as np
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()


# Configure logging - use home directory if /var/log is not writable
import os
log_file = '/var/log/musicgen-worker.log'
try:
    # Test if we can write to /var/log
    with open(log_file, 'a'):
        pass
except PermissionError:
    # Fall back to user's home directory
    log_file = os.path.expanduser('~/musicgen-worker.log')

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(log_file),
        logging.StreamHandler()
    ]
)
print(f"Worker logs will be written to: {log_file}")
print(f"Monitor logs with: tail -f {log_file}")
logger = logging.getLogger(__name__)


@dataclass
class JobResult:
    """Data structure for tracking generation results"""
    s3_filename: str
    prompt: str
    requested_duration_s: int
    generation_time_s: float
    estimated_cost_usd: float
    success: bool
    error_message: Optional[str] = None


class MusicGenWorker:
    """Main worker class for music generation"""
    
    def __init__(self):
        # Validate AWS environment variables first
        self._validate_aws_environment()
        
        # Configuration from environment variables (loaded from .env file)
        self.s3_bucket = os.getenv('MUSICGEN_S3_BUCKET', '').strip().strip('\r\n').strip()
        self.aws_region = (os.getenv('AWS_DEFAULT_REGION') or os.getenv('AWS_REGION', 'us-east-1')).strip().strip('\r\n').strip()
        
        # For hourly cost, use env var or calculate from instance type
        hourly_cost = os.getenv('MUSICGEN_HOURLY_COST')
        if hourly_cost:
            self.hourly_cost_usd = float(hourly_cost)
        else:
            # Default pricing based on common instance types
            instance_type = os.getenv('INSTANCE_TYPE', 'g4dn.xlarge')
            pricing = {
                'g4dn.xlarge': 0.526,
                'g4dn.2xlarge': 0.752,
                'm5.large': 0.096,
                'm5.xlarge': 0.192
            }
            self.hourly_cost_usd = pricing.get(instance_type, 0.40)
        
        # Initialize AWS clients - boto3 will use environment credentials
        self.s3_client = boto3.client('s3', region_name=self.aws_region)
        
        # Validate S3 connectivity and bucket access
        self._validate_s3_access()
        
        # Model variables (initialized later)
        self.model = None
        self.processor = None
        self.device = None
        
        # Results tracking
        self.job_results: List[JobResult] = []
        
        logger.info(f"Worker initialized - S3 bucket: {self.s3_bucket}, Hourly cost: ${self.hourly_cost_usd:.2f}")
    
    def _validate_aws_environment(self) -> None:
        """Validate required AWS environment variables are present"""
        logger.info("Validating AWS environment variables...")
        
        required_vars = [
            'AWS_ACCESS_KEY_ID',
            'AWS_SECRET_ACCESS_KEY', 
            'MUSICGEN_S3_BUCKET',
            'AWS_DEFAULT_REGION'
        ]
        
        missing_vars = []
        for var in required_vars:
            value = os.getenv(var)
            if value:
                # Clean environment variables of whitespace and line endings
                cleaned_value = value.strip().strip('\r\n').strip()
                os.environ[var] = cleaned_value
                value = cleaned_value
            if not value:
                # Try alternative names for region
                if var == 'AWS_DEFAULT_REGION' and os.getenv('AWS_REGION'):
                    continue
                missing_vars.append(var)
            else:
                logger.info(f"✅ {var}: {'*' * min(8, len(value))}...")
        
        if missing_vars:
            logger.error("❌ Missing required AWS environment variables:")
            for var in missing_vars:
                logger.error(f"  - {var}")
            
            if 'AWS_DEFAULT_REGION' in missing_vars and not os.getenv('AWS_REGION'):
                logger.error("    (AWS_DEFAULT_REGION or AWS_REGION must be set)")
            
            logger.error("\nEnsure these variables are set in your environment:")
            logger.error("- Locally: Add to .env file") 
            logger.error("- RunPod: Set via deployment script or SSH export commands")
            logger.error("- AWS: Use 'aws configure' or IAM role credentials")
            
            raise ValueError(f"Missing AWS environment variables: {', '.join(missing_vars)}")
        
        # Validate S3 bucket name format
        s3_bucket = os.getenv('MUSICGEN_S3_BUCKET')
        if not self._is_valid_s3_bucket_name(s3_bucket):
            raise ValueError(f"Invalid S3 bucket name: {s3_bucket}")
        
        logger.info("✅ AWS environment validation passed")
    
    def _is_valid_s3_bucket_name(self, bucket_name: str) -> bool:
        """Validate S3 bucket name follows AWS naming rules"""
        if not bucket_name:
            return False
        
        # Basic validation rules
        if len(bucket_name) < 3 or len(bucket_name) > 63:
            return False
        
        if bucket_name.startswith('-') or bucket_name.endswith('-'):
            return False
        
        if '..' in bucket_name:
            return False
        
        # Check for valid characters (simplified)
        import re
        if not re.match(r'^[a-z0-9.-]+$', bucket_name):
            return False
        
        return True
    
    def _validate_s3_access(self) -> None:
        """Validate S3 connectivity and bucket access"""
        logger.info("Validating S3 connectivity and bucket access...")
        
        try:
            # Test basic S3 connectivity by listing buckets
            logger.info("Testing S3 connectivity...")
            response = self.s3_client.list_buckets()
            logger.info(f"✅ S3 connection successful - Found {len(response['Buckets'])} buckets")
            
        except ClientError as e:
            error_code = e.response['Error']['Code']
            error_message = e.response['Error']['Message']
            
            if error_code == 'InvalidAccessKeyId':
                logger.error("❌ S3 connection failed: Invalid AWS Access Key ID")
                logger.error("Check AWS_ACCESS_KEY_ID environment variable")
            elif error_code == 'SignatureDoesNotMatch':
                logger.error("❌ S3 connection failed: Invalid AWS Secret Access Key") 
                logger.error("Check AWS_SECRET_ACCESS_KEY environment variable")
            elif error_code == 'TokenRefreshRequired':
                logger.error("❌ S3 connection failed: AWS session token expired")
                logger.error("Refresh your AWS credentials")
            else:
                logger.error(f"❌ S3 connection failed: {error_code} - {error_message}")
            
            raise ValueError(f"S3 connection failed: {error_code}")
            
        except Exception as e:
            logger.error(f"❌ S3 connection failed with unexpected error: {e}")
            raise ValueError(f"S3 connection failed: {str(e)}")
        
        # Test bucket-specific access
        try:
            logger.info(f"Testing bucket access: {self.s3_bucket}")
            
            # Check if bucket exists and we can access it
            self.s3_client.head_bucket(Bucket=self.s3_bucket)
            logger.info(f"✅ Bucket {self.s3_bucket} exists and is accessible")
            
            # Test write permissions with a small test object
            test_key = "musicgen_write_test.txt"
            test_content = "MusicGen write test"
            
            logger.info("Testing bucket write permissions...")
            self.s3_client.put_object(
                Bucket=self.s3_bucket,
                Key=test_key, 
                Body=test_content,
                ContentType='text/plain'
            )
            
            # Clean up test object
            self.s3_client.delete_object(Bucket=self.s3_bucket, Key=test_key)
            logger.info(f"✅ Bucket {self.s3_bucket} write permissions confirmed")
            
        except ClientError as e:
            error_code = e.response['Error']['Code']
            error_message = e.response['Error']['Message']
            
            if error_code == 'NoSuchBucket':
                logger.error(f"❌ S3 bucket does not exist: {self.s3_bucket}")
                logger.error("Create the bucket in AWS S3 console or check bucket name")
            elif error_code == 'AccessDenied':
                logger.error(f"❌ Access denied to S3 bucket: {self.s3_bucket}")
                logger.error("Check bucket permissions and AWS credentials")
            elif error_code == 'AllAccessDisabled':
                logger.error(f"❌ All access disabled for bucket: {self.s3_bucket}")
                logger.error("Check bucket policy and AWS account permissions")
            else:
                logger.error(f"❌ S3 bucket access failed: {error_code} - {error_message}")
            
            raise ValueError(f"S3 bucket access failed: {error_code}")
            
        except Exception as e:
            logger.error(f"❌ S3 bucket validation failed: {e}")
            raise ValueError(f"S3 bucket validation failed: {str(e)}")
        
        logger.info("✅ S3 connectivity and bucket validation passed")
    
    def initialize_model(self) -> None:
        """Initialize the MusicGen model and move it to GPU"""
        try:
            logger.info("Initializing MusicGen model...")
            
            # Check system requirements first
            self._validate_model_requirements()
            
            # Check for CUDA availability
            if torch.cuda.is_available():
                self.device = torch.device("cuda")
                logger.info(f"Using GPU: {torch.cuda.get_device_name()}")
                
                # Check GPU memory
                gpu_memory = torch.cuda.get_device_properties(0).total_memory / 1024**3
                logger.info(f"GPU memory available: {gpu_memory:.1f} GB")
                
                if gpu_memory < 6.0:
                    logger.warning(f"GPU memory ({gpu_memory:.1f} GB) may be insufficient for MusicGen-medium (requires ~6GB)")
            else:
                self.device = torch.device("cpu")
                logger.warning("CUDA not available, using CPU (will be very slow)")
            
            # Load model and processor with progress tracking
            model_name = "facebook/musicgen-large"
            logger.info(f"Loading {model_name}...")
            logger.info("This may take several minutes on first run (downloading ~12GB model)...")
            
            try:
                logger.info("Loading processor...")
                start_time = time.time()
                self.processor = AutoProcessor.from_pretrained(model_name)
                processor_time = time.time() - start_time
                logger.info(f"✅ Processor loaded successfully ({processor_time:.1f}s)")
                
                logger.info("Loading model (this is the large download)...")
                logger.info("📥 Download progress will be shown by transformers library...")
                model_start_time = time.time()
                
                self.model = MusicgenForConditionalGeneration.from_pretrained(model_name)
                
                model_load_time = time.time() - model_start_time
                logger.info(f"✅ Model loaded successfully ({model_load_time:.1f}s)")
                
                if model_load_time < 30:
                    logger.info("🚀 Fast load time - model was cached locally")
                elif model_load_time < 300:
                    logger.info("📥 Model loaded from cache or fast download")
                else:
                    logger.info("📥 Model downloaded from internet (first run)")
                
                logger.info("Moving model to device...")
                device_start_time = time.time()
                self.model.to(self.device)
                device_time = time.time() - device_start_time
                logger.info(f"✅ Model moved to {self.device} ({device_time:.1f}s)")
                
                # Set model to evaluation mode
                self.model.eval()
                
                # Verify model is working with a test
                logger.info("Verifying model functionality...")
                self._test_model_functionality()
                
                total_init_time = time.time() - start_time
                logger.info(f"✅ Model initialization complete and verified (total: {total_init_time:.1f}s)")
                
            except Exception as e:
                logger.error(f"Model loading failed: {str(e)}")
                if "out of memory" in str(e).lower():
                    logger.error("GPU out of memory - try using a GPU with more VRAM")
                elif "connection" in str(e).lower() or "timeout" in str(e).lower():
                    logger.error("Network issue downloading model - check internet connection")
                elif "disk" in str(e).lower() or "space" in str(e).lower():
                    logger.error("Insufficient disk space - model requires ~6GB storage")
                raise
                
        except Exception as e:
            logger.error(f"Failed to initialize model: {e}")
            raise
    
    def _validate_model_requirements(self) -> None:
        """Validate system requirements for MusicGen model"""
        logger.info("Validating system requirements for MusicGen...")
        
        # Check available disk space
        import shutil
        
        # Check space in current directory (or cache directory)
        cache_dir = os.path.expanduser("~/.cache/huggingface")
        try:
            if os.path.exists(cache_dir):
                total, used, free = shutil.disk_usage(cache_dir)
                free_gb = free / (1024**3)
                logger.info(f"Available disk space: {free_gb:.1f} GB")
                
                if free_gb < 10.0:  # Need space for model + some buffer
                    logger.warning(f"Low disk space ({free_gb:.1f} GB). Model requires ~6GB plus working space")
                    if free_gb < 6.0:
                        raise ValueError(f"Insufficient disk space: {free_gb:.1f} GB available, need at least 6GB")
            else:
                logger.info("Cache directory doesn't exist yet, will be created during model download")
                
        except Exception as e:
            logger.warning(f"Could not check disk space: {e}")
        
        # Check if model is already cached
        model_name = "facebook/musicgen-large"
        try:
            from transformers import AutoConfig
            config = AutoConfig.from_pretrained(model_name, local_files_only=True)
            logger.info("✅ Model found in local cache - no download required")
            
            # Verify cache integrity
            cache_path = os.path.expanduser("~/.cache/huggingface/hub")
            if os.path.exists(cache_path):
                import glob
                model_files = glob.glob(os.path.join(cache_path, "*musicgen*", "*", "*.bin")) + \
                             glob.glob(os.path.join(cache_path, "*musicgen*", "*", "*.safetensors"))
                
                if model_files:
                    total_size = sum(os.path.getsize(f) for f in model_files if os.path.exists(f))
                    size_gb = total_size / (1024**3)
                    logger.info(f"📦 Cached model size: {size_gb:.1f} GB")
                    
                    if size_gb < 5.0:  # MusicGen-medium should be ~6GB
                        logger.warning(f"⚠️  Cached model seems incomplete ({size_gb:.1f} GB), may need to re-download")
                else:
                    logger.warning("⚠️  Model config found but model files missing, will re-download")
                    
        except Exception as e:
            logger.info("Model not in cache - will download on first run (~6GB)")
            logger.info("This may take 5-15 minutes depending on your internet connection")
        
        logger.info("✅ System requirements validation passed")
    
    def _test_model_functionality(self) -> None:
        """Test model with a simple generation to verify it's working"""
        try:
            logger.info("Running model functionality test...")
            
            # Simple test generation (very short)
            test_prompt = "test"
            inputs = self.processor(
                text=[test_prompt],
                padding=True,
                return_tensors="pt"
            ).to(self.device)
            
            # Generate just a few tokens as a test
            with torch.no_grad():
                audio_values = self.model.generate(**inputs, max_new_tokens=10)
            
            # Verify we got output
            if audio_values is not None and len(audio_values) > 0:
                logger.info("✅ Model functionality test passed")
            else:
                raise ValueError("Model test generated no output")
                
        except Exception as e:
            logger.error(f"Model functionality test failed: {e}")
            raise ValueError(f"Model is not working correctly: {str(e)}")
    
    def parse_prompts_file(self, filepath: str = "prompts.txt") -> List[Tuple[str, int, str]]:
        """
        Parse the prompts file and return list of (prompt, duration, filename) tuples.
        
        Args:
            filepath: Path to the prompts file
            
        Returns:
            List of tuples containing (prompt_text, duration_seconds, output_filename)
        """
        jobs = []
        
        if not os.path.exists(filepath):
            logger.error(f"Prompts file not found: {filepath}")
            return jobs
        
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                for line_num, line in enumerate(f, 1):
                    line = line.strip()
                    
                    # Skip empty lines and comments
                    if not line or line.startswith('#'):
                        continue
                    
                    # Parse format: PROMPT_TEXT ; DURATION_IN_SECONDS ; FILE_NAME
                    parts = [part.strip() for part in line.split(';')]
                    
                    if len(parts) != 3:
                        logger.warning(f"Invalid format on line {line_num}: {line}")
                        continue
                    
                    prompt_text, duration_str, filename = parts
                    
                    try:
                        duration = int(duration_str)
                        if duration <= 0:
                            logger.warning(f"Invalid duration on line {line_num}: {duration}")
                            continue
                    except ValueError:
                        logger.warning(f"Invalid duration format on line {line_num}: {duration_str}")
                        continue
                    
                    # Ensure filename has .wav extension
                    if not filename.lower().endswith('.wav'):
                        filename += '.wav'
                    
                    jobs.append((prompt_text, duration, filename))
                    logger.info(f"Parsed job: '{prompt_text[:50]}...' -> {filename} ({duration}s)")
            
            logger.info(f"Parsed {len(jobs)} jobs from {filepath}")
            return jobs
            
        except Exception as e:
            logger.error(f"Error parsing prompts file: {e}")
            return []
    
    def check_s3_file_exists(self, filename: str) -> bool:
        """
        Check if a file already exists in S3 bucket.
        
        Args:
            filename: The S3 object key to check
            
        Returns:
            True if file exists, False otherwise
        """
        try:
            self.s3_client.head_object(Bucket=self.s3_bucket, Key=filename)
            return True
        except ClientError as e:
            error_code = e.response['Error']['Code']
            if error_code == '404':
                return False
            else:
                logger.warning(f"Error checking S3 object {filename}: {e}")
                return False
    
    def generate_deterministic_filename(self, prompt: str, duration: int, base_filename: str) -> str:
        """
        Generate a deterministic filename for idempotency.
        
        Args:
            prompt: The generation prompt
            duration: Target duration in seconds
            base_filename: Base filename from prompts.txt
            
        Returns:
            Deterministic filename
        """
        # Create a hash of the prompt and duration for uniqueness
        content = f"{prompt}|{duration}|{base_filename}"
        hash_suffix = hashlib.md5(content.encode()).hexdigest()[:8]
        
        # Extract base name without extension
        name_part = os.path.splitext(base_filename)[0]
        return f"{name_part}_{hash_suffix}.wav"
    
    def generate_audio(self, prompt: str, duration_seconds: int) -> np.ndarray:
        """
        Generate audio using MusicGen with chunking for long durations.
        
        Args:
            prompt: Text prompt for generation
            duration_seconds: Target duration in seconds
            
        Returns:
            Generated audio as numpy array
        """
        max_length_seconds = 30  # Max length per chunk
        
        if duration_seconds <= max_length_seconds:
            # Single generation for short audio
            inputs = self.processor(
                text=[prompt],
                padding=True,
                return_tensors="pt"
            ).to(self.device)
            
            # Calculate max_new_tokens for the desired duration
            # MusicGen typically uses 50 tokens per second
            max_new_tokens = int(duration_seconds * 50)
            
            with torch.no_grad():
                audio_values = self.model.generate(**inputs, max_new_tokens=max_new_tokens)
            
            # Convert to numpy and return
            audio_np = audio_values[0].cpu().numpy()
            # Ensure audio is in the right shape for soundfile (samples,) for mono
            if audio_np.ndim > 1:
                audio_np = audio_np.squeeze()
            return audio_np
        else:
            # Chunked generation for long audio
            logger.info(f"Using chunked generation for {duration_seconds}s audio")
            chunks = []
            remaining_duration = duration_seconds
            
            while remaining_duration > 0:
                chunk_duration = min(remaining_duration, max_length_seconds)
                
                # Generate chunk
                inputs = self.processor(
                    text=[prompt],
                    padding=True,
                    return_tensors="pt"
                ).to(self.device)
                
                # Calculate max_new_tokens for this chunk
                max_new_tokens = int(chunk_duration * 50)
                
                with torch.no_grad():
                    chunk_audio = self.model.generate(**inputs, max_new_tokens=max_new_tokens)
                
                chunk_np = chunk_audio[0].cpu().numpy()
                # Ensure chunk is in the right shape for soundfile (samples,) for mono
                if chunk_np.ndim > 1:
                    chunk_np = chunk_np.squeeze()
                chunks.append(chunk_np)
                remaining_duration -= chunk_duration
                
                logger.info(f"Generated chunk: {chunk_duration}s, remaining: {remaining_duration}s")
            
            # Concatenate all chunks along the time axis
            full_audio = np.concatenate(chunks, axis=0)
            return full_audio
    
    def upload_to_s3(self, local_filepath: str, s3_key: str) -> bool:
        """
        Upload a file to S3.
        
        Args:
            local_filepath: Local file to upload
            s3_key: S3 object key
            
        Returns:
            True if successful, False otherwise
        """
        try:
            logger.info(f"Uploading {s3_key} to S3...")
            self.s3_client.upload_file(
                local_filepath,
                self.s3_bucket,
                s3_key,
                ExtraArgs={'ContentType': 'audio/wav'}
            )
            logger.info(f"✅ Upload complete: {s3_key}")
            return True
        except Exception as e:
            logger.error(f"Failed to upload {s3_key}: {e}")
            return False
    
    def process_job(self, prompt: str, duration: int, base_filename: str) -> JobResult:
        """
        Process a single music generation job.
        
        Args:
            prompt: Text prompt for generation
            duration: Target duration in seconds
            base_filename: Base filename from prompts.txt
            
        Returns:
            JobResult with generation details
        """
        # Generate deterministic filename
        s3_filename = self.generate_deterministic_filename(prompt, duration, base_filename)
        
        logger.info(f"Processing: '{prompt[:60]}...' -> {s3_filename}")
        
        # Check if file already exists (idempotency)
        if self.check_s3_file_exists(s3_filename):
            logger.info(f"⏭️  Skipping {s3_filename} - already exists in S3")
            return JobResult(
                s3_filename=s3_filename,
                prompt=prompt,
                requested_duration_s=duration,
                generation_time_s=0.0,
                estimated_cost_usd=0.0,
                success=True
            )
        
        # Record start time
        start_time = time.time()
        
        try:
            # Generate audio
            logger.info(f"Generating audio for {duration}s...")
            audio_data = self.generate_audio(prompt, duration)
            
            # Save to temporary file
            with tempfile.NamedTemporaryFile(suffix='.wav', delete=False) as temp_file:
                temp_filepath = temp_file.name
            
            # Write audio file - MusicGen uses 32kHz sample rate
            sample_rate = 32000
            sf.write(temp_filepath, audio_data, sample_rate)
            
            # Upload to S3
            upload_success = self.upload_to_s3(temp_filepath, s3_filename)
            
            # Calculate timing and cost
            end_time = time.time()
            generation_time = end_time - start_time
            estimated_cost = (generation_time / 3600) * self.hourly_cost_usd
            
            # Clean up temporary file
            os.unlink(temp_filepath)
            
            if upload_success:
                logger.info(f"✅ Job complete: {s3_filename} ({generation_time:.1f}s, ${estimated_cost:.3f})")
                return JobResult(
                    s3_filename=s3_filename,
                    prompt=prompt,
                    requested_duration_s=duration,
                    generation_time_s=generation_time,
                    estimated_cost_usd=estimated_cost,
                    success=True
                )
            else:
                return JobResult(
                    s3_filename=s3_filename,
                    prompt=prompt,
                    requested_duration_s=duration,
                    generation_time_s=generation_time,
                    estimated_cost_usd=estimated_cost,
                    success=False,
                    error_message="S3 upload failed"
                )
                
        except Exception as e:
            end_time = time.time()
            generation_time = end_time - start_time
            estimated_cost = (generation_time / 3600) * self.hourly_cost_usd
            
            logger.error(f"❌ Job failed: {str(e)}")
            return JobResult(
                s3_filename=s3_filename,
                prompt=prompt,
                requested_duration_s=duration,
                generation_time_s=generation_time,
                estimated_cost_usd=estimated_cost,
                success=False,
                error_message=str(e)
            )
    
    def generate_cost_report(self) -> str:
        """
        Generate cost report CSV content.
        
        Returns:
            CSV content as string
        """
        # Filter to only successful jobs for the report
        successful_results = [r for r in self.job_results if r.success]
        
        if not successful_results:
            logger.warning("No successful jobs to include in cost report")
            return "s3_filename,prompt,requested_duration_s,generation_time_s,estimated_cost_usd\n"
        
        # Create CSV content
        output = []
        output.append("s3_filename,prompt,requested_duration_s,generation_time_s,estimated_cost_usd")
        
        total_cost = 0.0
        for result in successful_results:
            escaped_prompt = result.prompt.replace('"', '""')
            output.append(
                f'"{result.s3_filename}",'
                f'"{escaped_prompt}",'
                f"{result.requested_duration_s},"
                f"{result.generation_time_s:.2f},"
                f"{result.estimated_cost_usd:.4f}"
            )
            total_cost += result.estimated_cost_usd
        
        # Add summary row
        output.append("")  # Empty line
        output.append(f"TOTAL,{len(successful_results)} files,,{sum(r.generation_time_s for r in successful_results):.2f},{total_cost:.4f}")
        
        return "\n".join(output)
    
    def upload_cost_report(self) -> bool:
        """
        Generate and upload the cost report to S3.
        
        Returns:
            True if successful, False otherwise
        """
        try:
            logger.info("Generating cost report...")
            csv_content = self.generate_cost_report()
            
            # Create temporary file
            with tempfile.NamedTemporaryFile(mode='w', suffix='.csv', delete=False) as temp_file:
                temp_file.write(csv_content)
                temp_filepath = temp_file.name
            
            # Upload to S3
            timestamp = time.strftime("%Y%m%d_%H%M%S")
            report_key = f"cost_report_{timestamp}.csv"
            
            success = self.upload_to_s3(temp_filepath, report_key)
            
            # Clean up
            os.unlink(temp_filepath)
            
            if success:
                # Also upload as latest report (create temp file again since original was deleted)
                with tempfile.NamedTemporaryFile(mode='w', suffix='.csv', delete=False) as temp_file_latest:
                    temp_file_latest.write(csv_content)
                    temp_filepath_latest = temp_file_latest.name
                
                self.upload_to_s3(temp_filepath_latest, "cost_report_latest.csv")
                os.unlink(temp_filepath_latest)  # Clean up
                logger.info(f"✅ Cost report uploaded: {report_key}")
            
            return success
            
        except Exception as e:
            logger.error(f"Failed to upload cost report: {e}")
            return False
    
    def generate_detailed_completion_report(self) -> str:
        """Generate detailed completion report with all files and metrics"""
        successful_results = [r for r in self.job_results if r.success]
        failed_results = [r for r in self.job_results if not r.success]
        
        total_time = sum(r.generation_time_s for r in successful_results)
        total_cost = sum(r.estimated_cost_usd for r in successful_results)
        
        report_lines = []
        report_lines.append("🎵 MUSICGEN BATCH COMPLETION REPORT")
        report_lines.append("=" * 80)
        report_lines.append(f"⏰ Completed at: {time.strftime('%Y-%m-%d %H:%M:%S UTC')}")
        report_lines.append(f"📊 Jobs processed: {len(self.job_results)} total")
        report_lines.append(f"✅ Successful: {len(successful_results)}")
        report_lines.append(f"❌ Failed: {len(failed_results)}")
        report_lines.append(f"⏱️  Total generation time: {total_time:.1f}s ({total_time/60:.1f} minutes)")
        report_lines.append(f"💰 Estimated total cost: ${total_cost:.4f}")
        report_lines.append(f"🗂️  S3 bucket: {self.s3_bucket}")
        
        if successful_results:
            report_lines.append("\n" + "=" * 80)
            report_lines.append("📁 SUCCESSFULLY GENERATED FILES:")
            report_lines.append("=" * 80)
            
            # Calculate average generation time
            avg_time = total_time / len(successful_results)
            report_lines.append(f"Average generation time: {avg_time:.1f}s per file")
            report_lines.append("")
            
            # List all successful files with details
            for i, result in enumerate(successful_results, 1):
                duration_text = f"{result.requested_duration_s}s"
                time_text = f"{result.generation_time_s:.1f}s"
                cost_text = f"${result.estimated_cost_usd:.4f}"
                
                report_lines.append(f"{i:2d}. 📄 {result.s3_filename}")
                report_lines.append(f"     Prompt: {result.prompt[:100]}{'...' if len(result.prompt) > 100 else ''}")
                report_lines.append(f"     Duration: {duration_text} | Generation time: {time_text} | Cost: {cost_text}")
                report_lines.append("")
        
        if failed_results:
            report_lines.append("=" * 80)
            report_lines.append("❌ FAILED JOBS:")
            report_lines.append("=" * 80)
            
            for i, result in enumerate(failed_results, 1):
                report_lines.append(f"{i:2d}. ❌ {result.s3_filename}")
                report_lines.append(f"     Prompt: {result.prompt[:100]}{'...' if len(result.prompt) > 100 else ''}")
                report_lines.append(f"     Error: {result.error_message or 'Unknown error'}")
                report_lines.append(f"     Partial generation time: {result.generation_time_s:.1f}s")
                report_lines.append("")
        
        # Performance metrics
        if successful_results:
            report_lines.append("=" * 80)
            report_lines.append("📈 PERFORMANCE METRICS:")
            report_lines.append("=" * 80)
            
            # Group by duration for analysis
            duration_groups = {}
            for result in successful_results:
                duration = result.requested_duration_s
                if duration not in duration_groups:
                    duration_groups[duration] = []
                duration_groups[duration].append(result)
            
            for duration in sorted(duration_groups.keys()):
                results = duration_groups[duration]
                avg_gen_time = sum(r.generation_time_s for r in results) / len(results)
                total_files = len(results)
                
                report_lines.append(f"{duration:2d}s audio: {total_files} files, avg generation time: {avg_gen_time:.1f}s")
            
            # Efficiency metrics
            total_audio_duration = sum(r.requested_duration_s for r in successful_results)
            efficiency_ratio = total_audio_duration / total_time if total_time > 0 else 0
            
            report_lines.append("")
            report_lines.append(f"Total audio generated: {total_audio_duration}s ({total_audio_duration/60:.1f} minutes)")
            report_lines.append(f"Generation efficiency: {efficiency_ratio:.2f}x real-time")
            report_lines.append(f"Cost per second of audio: ${total_cost/total_audio_duration:.6f}" if total_audio_duration > 0 else "")
        
        report_lines.append("\n" + "=" * 80)
        report_lines.append("📋 S3 UPLOAD SUMMARY:")
        report_lines.append("=" * 80)
        report_lines.append(f"S3 Bucket: s3://{self.s3_bucket}/")
        report_lines.append("Files uploaded:")
        
        for result in successful_results:
            report_lines.append(f"  • {result.s3_filename}")
        
        if len(successful_results) > 0:
            report_lines.append(f"\nCost report: cost_report_latest.csv")
            report_lines.append(f"Total S3 objects created: {len(successful_results) + 1}")  # +1 for cost report
        
        report_lines.append("\n" + "=" * 80)
        report_lines.append("🎵 END OF COMPLETION REPORT")
        report_lines.append("=" * 80)
        
        return "\n".join(report_lines)
    
    def run(self) -> None:
        """Main worker execution loop"""
        try:
            logger.info("🎵 Starting MusicGen Worker")
            
            # Initialize the model
            self.initialize_model()
            
            # Parse jobs from prompts.txt
            jobs = self.parse_prompts_file()
            
            if not jobs:
                logger.error("No valid jobs found in prompts.txt")
                sys.exit(1)
            
            logger.info(f"Processing {len(jobs)} jobs...")
            
            # Process each job
            for i, (prompt, duration, filename) in enumerate(jobs, 1):
                logger.info(f"\n📝 Job {i}/{len(jobs)}: {filename}")
                
                try:
                    result = self.process_job(prompt, duration, filename)
                    self.job_results.append(result)
                    
                    if result.success:
                        logger.info(f"✅ Job {i} completed successfully")
                    else:
                        logger.warning(f"⚠️  Job {i} failed: {result.error_message}")
                        
                except Exception as e:
                    logger.error(f"❌ Job {i} crashed: {e}")
                    # Continue with next job
                    continue
            
            # Generate and upload cost report
            logger.info("\n📊 Generating final cost report...")
            report_success = self.upload_cost_report()
            
            # Generate and display detailed completion report
            detailed_report = self.generate_detailed_completion_report()
            logger.info(f"\n{detailed_report}")
            
            # Add cost report status to the completion summary
            successful_jobs = len([r for r in self.job_results if r.success])
            logger.info(f"📊 Cost report uploaded: {'✅' if report_success else '❌'}")
            
            # Exit with error code if some jobs failed
            failed_jobs = len(jobs) - successful_jobs
            if failed_jobs > 0:
                logger.warning(f"⚠️  {failed_jobs} job(s) failed")
                sys.exit(1)
            
        except Exception as e:
            logger.error(f"Worker failed with unexpected error: {e}")
            sys.exit(1)


def main():
    """Entry point for the worker script"""
    worker = MusicGenWorker()
    worker.run()


if __name__ == '__main__':
    main()
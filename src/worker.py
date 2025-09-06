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
        # Configuration from environment variables (loaded from .env file)
        self.s3_bucket = os.getenv('MUSICGEN_S3_BUCKET')
        self.aws_region = os.getenv('AWS_DEFAULT_REGION') or os.getenv('AWS_REGION', 'us-east-1')
        
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
        
        # Validate configuration
        if not self.s3_bucket:
            raise ValueError("S3 bucket not configured. Set MUSICGEN_S3_BUCKET in .env file")
        
        # Initialize AWS clients
        self.s3_client = boto3.client('s3', region_name=self.aws_region)
        
        # Model variables (initialized later)
        self.model = None
        self.processor = None
        self.device = None
        
        # Results tracking
        self.job_results: List[JobResult] = []
        
        logger.info(f"Worker initialized - S3 bucket: {self.s3_bucket}, Hourly cost: ${self.hourly_cost_usd:.2f}")
    
    def initialize_model(self) -> None:
        """Initialize the MusicGen model and move it to GPU"""
        try:
            logger.info("Initializing MusicGen model...")
            
            # Check for CUDA availability
            if torch.cuda.is_available():
                self.device = torch.device("cuda")
                logger.info(f"Using GPU: {torch.cuda.get_device_name()}")
            else:
                self.device = torch.device("cpu")
                logger.warning("CUDA not available, using CPU (will be very slow)")
            
            # Load model and processor
            model_name = "facebook/musicgen-medium"
            logger.info(f"Loading {model_name}...")
            
            self.processor = AutoProcessor.from_pretrained(model_name)
            self.model = MusicgenForConditionalGeneration.from_pretrained(model_name)
            self.model.to(self.device)
            
            # Set model to evaluation mode
            self.model.eval()
            
            logger.info("✅ Model initialization complete")
            
        except Exception as e:
            logger.error(f"Failed to initialize model: {e}")
            raise
    
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
                
                chunks.append(chunk_audio[0].cpu().numpy())
                remaining_duration -= chunk_duration
                
                logger.info(f"Generated chunk: {chunk_duration}s, remaining: {remaining_duration}s")
            
            # Concatenate all chunks
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
            output.append(
                f'"{result.s3_filename}",'
                f'"{result.prompt.replace('"', '""')}",'
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
            
            # Summary
            successful_jobs = len([r for r in self.job_results if r.success])
            total_cost = sum(r.estimated_cost_usd for r in self.job_results if r.success)
            total_time = sum(r.generation_time_s for r in self.job_results if r.success)
            
            logger.info("\n" + "="*60)
            logger.info("🎵 MUSICGEN WORKER COMPLETED")
            logger.info("="*60)
            logger.info(f"✅ Successful jobs: {successful_jobs}/{len(jobs)}")
            logger.info(f"⏱️  Total generation time: {total_time:.1f}s ({total_time/60:.1f}m)")
            logger.info(f"💰 Estimated total cost: ${total_cost:.3f}")
            logger.info(f"📊 Cost report uploaded: {'✅' if report_success else '❌'}")
            logger.info("="*60)
            
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
#!/usr/bin/env python3
"""
S3 Music Downloader CLI Utility

Downloads all files from a specified S3 directory within the configured bucket
to a local destination directory.

Usage:
    python s3_music_downloader.py <s3_directory> <destination_directory>

Example:
    python s3_music_downloader.py run_20240907_123456 ./downloads
"""

import os
import sys
import argparse
import logging
from pathlib import Path
from typing import List, Optional
from dataclasses import dataclass

import boto3
from botocore.exceptions import ClientError, NoCredentialsError
from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler()]
)
logger = logging.getLogger(__name__)


@dataclass
class DownloadResult:
    """Result of a single file download operation"""
    s3_key: str
    local_path: str
    success: bool
    error_message: Optional[str] = None


class S3MusicDownloader:
    """Downloads music files from S3 directory to local directory"""
    
    def __init__(self):
        self._validate_aws_environment()
        
        self.s3_bucket = os.getenv('MUSICGEN_S3_BUCKET', '').strip()
        self.aws_region = (os.getenv('AWS_DEFAULT_REGION') or os.getenv('AWS_REGION', 'us-east-1')).strip()
        
        self.s3_client = boto3.client('s3', region_name=self.aws_region)
        self._validate_s3_access()
        
        logger.info(f"S3 Downloader initialized - Bucket: {self.s3_bucket}, Region: {self.aws_region}")
    
    def _validate_aws_environment(self) -> None:
        """Validate required AWS environment variables are present"""
        logger.info("Validating AWS environment variables...")
        
        required_vars = [
            'AWS_ACCESS_KEY_ID',
            'AWS_SECRET_ACCESS_KEY',
            'MUSICGEN_S3_BUCKET'
        ]
        
        missing_vars = []
        for var in required_vars:
            value = os.getenv(var)
            if not value:
                missing_vars.append(var)
        
        region = os.getenv('AWS_DEFAULT_REGION') or os.getenv('AWS_REGION')
        if not region:
            missing_vars.append('AWS_DEFAULT_REGION or AWS_REGION')
        
        if missing_vars:
            logger.error("Missing required AWS environment variables:")
            for var in missing_vars:
                logger.error(f"  - {var}")
            logger.error("\nEnsure these variables are set in your .env file")
            raise ValueError(f"Missing AWS environment variables: {', '.join(missing_vars)}")
        
        s3_bucket = os.getenv('MUSICGEN_S3_BUCKET')
        if not self._is_valid_s3_bucket_name(s3_bucket):
            raise ValueError(f"Invalid S3 bucket name: {s3_bucket}")
        
        logger.info("AWS environment validation passed")
    
    def _is_valid_s3_bucket_name(self, bucket_name: str) -> bool:
        """Validate S3 bucket name follows AWS naming rules"""
        if not bucket_name or len(bucket_name) < 3 or len(bucket_name) > 63:
            return False
        if not bucket_name.replace('-', '').replace('.', '').isalnum():
            return False
        if bucket_name.startswith('-') or bucket_name.endswith('-'):
            return False
        return True
    
    def _validate_s3_access(self) -> None:
        """Validate S3 connectivity and bucket access"""
        logger.info("Validating S3 connectivity and bucket access...")
        
        try:
            # Test basic S3 connectivity
            self.s3_client.list_buckets()
            logger.info("S3 connection successful")
            
            # Test bucket-specific access
            self.s3_client.head_bucket(Bucket=self.s3_bucket)
            logger.info("S3 bucket access validated")
            
        except ClientError as e:
            error_code = e.response.get('Error', {}).get('Code', 'Unknown')
            error_message = e.response.get('Error', {}).get('Message', str(e))
            
            if error_code == 'NoSuchBucket':
                logger.error(f"S3 bucket does not exist: {self.s3_bucket}")
            elif error_code == 'AccessDenied':
                logger.error(f"Access denied to S3 bucket: {self.s3_bucket}")
            else:
                logger.error(f"S3 access failed: {error_code} - {error_message}")
            
            raise ValueError(f"S3 access failed: {error_code}")
        
        except NoCredentialsError:
            logger.error("AWS credentials not found")
            raise ValueError("AWS credentials not found")
        
        except Exception as e:
            logger.error(f"S3 validation failed: {e}")
            raise ValueError(f"S3 validation failed: {str(e)}")
    
    def list_s3_directory_files(self, s3_directory: str) -> List[str]:
        """List all files in the specified S3 directory"""
        logger.info(f"Listing files in S3 directory: {s3_directory}")
        
        # Ensure directory path ends with /
        if not s3_directory.endswith('/'):
            s3_directory += '/'
        
        files = []
        try:
            paginator = self.s3_client.get_paginator('list_objects_v2')
            page_iterator = paginator.paginate(
                Bucket=self.s3_bucket,
                Prefix=s3_directory
            )
            
            for page in page_iterator:
                if 'Contents' in page:
                    for obj in page['Contents']:
                        key = obj['Key']
                        # Skip directory markers and only include actual files
                        if not key.endswith('/') and key != s3_directory:
                            files.append(key)
            
            logger.info(f"Found {len(files)} files in directory")
            return files
        
        except ClientError as e:
            error_code = e.response.get('Error', {}).get('Code', 'Unknown')
            logger.error(f"Failed to list S3 directory: {error_code}")
            raise ValueError(f"Failed to list S3 directory: {error_code}")
    
    def download_file(self, s3_key: str, local_path: Path) -> DownloadResult:
        """Download a single file from S3"""
        try:
            # Create parent directories if they don't exist
            local_path.parent.mkdir(parents=True, exist_ok=True)
            
            # Download the file
            self.s3_client.download_file(
                self.s3_bucket,
                s3_key,
                str(local_path)
            )
            
            logger.info(f"Downloaded: {s3_key} -> {local_path}")
            return DownloadResult(
                s3_key=s3_key,
                local_path=str(local_path),
                success=True
            )
        
        except ClientError as e:
            error_code = e.response.get('Error', {}).get('Code', 'Unknown')
            error_message = f"Failed to download {s3_key}: {error_code}"
            logger.error(error_message)
            return DownloadResult(
                s3_key=s3_key,
                local_path=str(local_path),
                success=False,
                error_message=error_message
            )
        
        except Exception as e:
            error_message = f"Failed to download {s3_key}: {str(e)}"
            logger.error(error_message)
            return DownloadResult(
                s3_key=s3_key,
                local_path=str(local_path),
                success=False,
                error_message=error_message
            )
    
    def download_directory(self, s3_directory: str, destination_dir: str) -> List[DownloadResult]:
        """Download all files from S3 directory to local destination"""
        logger.info(f"Starting download from s3://{self.s3_bucket}/{s3_directory} to {destination_dir}")
        
        # Create destination directory structure
        dest_path = Path(destination_dir)
        if not dest_path.exists():
            logger.error(f"Destination directory does not exist: {destination_dir}")
            raise ValueError(f"Destination directory does not exist: {destination_dir}")
        
        # Create subdirectory with the same name as S3 directory
        s3_dir_name = s3_directory.rstrip('/')
        local_target_dir = dest_path / s3_dir_name
        local_target_dir.mkdir(exist_ok=True)
        logger.info(f"Created local directory: {local_target_dir}")
        
        # List files in S3 directory
        s3_files = self.list_s3_directory_files(s3_directory)
        if not s3_files:
            logger.warning(f"No files found in S3 directory: {s3_directory}")
            return []
        
        # Download each file
        results = []
        for s3_key in s3_files:
            # Extract filename from S3 key
            filename = s3_key.split('/')[-1]
            local_path = local_target_dir / filename
            
            result = self.download_file(s3_key, local_path)
            results.append(result)
        
        # Summary
        successful = [r for r in results if r.success]
        failed = [r for r in results if not r.success]
        
        logger.info(f"Download complete: {len(successful)} successful, {len(failed)} failed")
        if failed:
            logger.error("Failed downloads:")
            for result in failed:
                logger.error(f"  - {result.s3_key}: {result.error_message}")
        
        return results


def main():
    """Main CLI entry point"""
    parser = argparse.ArgumentParser(
        description="Download all files from an S3 directory to a local directory",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python s3_music_downloader.py run_20240907_123456 ./downloads
  python s3_music_downloader.py my-music-folder /path/to/downloads
        """
    )
    
    parser.add_argument(
        's3_directory',
        help='S3 directory path within the configured bucket'
    )
    
    parser.add_argument(
        'destination_directory',
        help='Local destination directory (must exist)'
    )
    
    parser.add_argument(
        '--verbose', '-v',
        action='store_true',
        help='Enable verbose logging'
    )
    
    args = parser.parse_args()
    
    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)
    
    try:
        downloader = S3MusicDownloader()
        results = downloader.download_directory(args.s3_directory, args.destination_directory)
        
        successful = [r for r in results if r.success]
        failed = [r for r in results if not r.success]
        
        print(f"\nDownload Summary:")
        print(f"  Files downloaded: {len(successful)}")
        print(f"  Files failed: {len(failed)}")
        
        if successful:
            print(f"  Downloaded to: {Path(args.destination_directory) / args.s3_directory.rstrip('/')}")
        
        # Exit with error code if any downloads failed
        sys.exit(1 if failed else 0)
    
    except Exception as e:
        logger.error(f"Error: {e}")
        sys.exit(1)


if __name__ == '__main__':
    main()
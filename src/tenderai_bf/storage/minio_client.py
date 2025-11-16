"""MinIO S3-compatible storage client for TenderAI BF."""

import hashlib
import io
import unicodedata
from datetime import datetime, timedelta
from pathlib import Path
from typing import BinaryIO, Dict, List, Optional, Union
from urllib.parse import urlparse

import boto3
from botocore.client import Config
from botocore.exceptions import ClientError, NoCredentialsError

from ..config import settings
from ..logging import get_logger

logger = get_logger(__name__)


def sanitize_s3_metadata(value: str) -> str:
    """Sanitize string for S3 metadata (ASCII only).
    
    S3 metadata can only contain ASCII characters.
    This function removes accents and converts to ASCII.
    """
    if not value:
        return value
    
    # Normalize unicode characters (decompose accented chars)
    nfd = unicodedata.normalize('NFD', value)
    # Keep only ASCII characters
    ascii_str = nfd.encode('ascii', 'ignore').decode('ascii')
    return ascii_str


class MinIOClient:
    """S3-compatible client for MinIO storage operations."""
    
    def __init__(self, 
                 endpoint: str = None,
                 access_key: str = None,
                 secret_key: str = None,
                 bucket_name: str = None,
                 secure: bool = None):
        """Initialize MinIO client with configuration."""
        
        self.endpoint = endpoint or settings.minio.endpoint
        self.access_key = access_key or settings.minio.access_key
        self.secret_key = secret_key or settings.minio.secret_key.get_secret_value()
        self.bucket_name = bucket_name or settings.minio.bucket_name
        self.secure = secure if secure is not None else settings.minio.secure
        
        # Configure S3 client
        self.client = boto3.client(
            's3',
            endpoint_url=f"{'https' if self.secure else 'http'}://{self.endpoint}",
            aws_access_key_id=self.access_key,
            aws_secret_access_key=self.secret_key,
            region_name=settings.minio.region,
            config=Config(
                signature_version='s3v4',
                s3={
                    'addressing_style': 'path'
                },
                connect_timeout=30,
                read_timeout=60,
                retries={
                    'max_attempts': 3,
                    'mode': 'adaptive'
                }
            )
        )
        
        logger.info(
            "MinIO client initialized",
            endpoint=self.endpoint,
            bucket=self.bucket_name,
            secure=self.secure
        )
    
    def ensure_bucket_exists(self) -> bool:
        """Ensure the bucket exists, create if it doesn't."""
        try:
            # Check if bucket exists
            self.client.head_bucket(Bucket=self.bucket_name)
            logger.debug("Bucket exists", bucket=self.bucket_name)
            return True
            
        except ClientError as e:
            error_code = e.response['Error']['Code']
            
            if error_code == '404':
                # Bucket doesn't exist, create it
                try:
                    self.client.create_bucket(Bucket=self.bucket_name)
                    logger.info("Bucket created", bucket=self.bucket_name)
                    
                    # Set bucket policy for public read access to reports
                    self._set_bucket_policy()
                    return True
                    
                except ClientError as create_error:
                    logger.error(
                        "Failed to create bucket",
                        bucket=self.bucket_name,
                        error=str(create_error)
                    )
                    return False
            else:
                logger.error(
                    "Failed to check bucket",
                    bucket=self.bucket_name,
                    error=str(e)
                )
                return False
    
    def _set_bucket_policy(self) -> None:
        """Set bucket policy for public read access to reports."""
        policy = {
            "Version": "2012-10-17",
            "Statement": [
                {
                    "Effect": "Allow",
                    "Principal": "*",
                    "Action": "s3:GetObject",
                    "Resource": f"arn:aws:s3:::{self.bucket_name}/reports/*"
                }
            ]
        }
        
        try:
            import json
            self.client.put_bucket_policy(
                Bucket=self.bucket_name,
                Policy=json.dumps(policy)
            )
            logger.info("Bucket policy set for public report access")
        except ClientError as e:
            logger.error("Failed to set bucket policy", error=str(e))
    
    def put_object(self, 
                   key: str,
                   data: Union[bytes, BinaryIO, str],
                   content_type: str = "application/octet-stream",
                   metadata: Optional[Dict[str, str]] = None) -> bool:
        """Upload an object to MinIO."""
        
        try:
            # Ensure bucket exists
            if not self.ensure_bucket_exists():
                return False
            
            # Convert string to bytes if needed
            if isinstance(data, str):
                data = data.encode('utf-8')
                if content_type == "application/octet-stream":
                    content_type = "text/plain"
            
            # Prepare metadata
            extra_args = {
                'ContentType': content_type,
                'Metadata': metadata or {}
            }
            
            # Calculate size for logging
            if isinstance(data, bytes):
                size = len(data)
                data_io = io.BytesIO(data)
            else:
                # For file-like objects, try to get size
                current_pos = data.tell() if hasattr(data, 'tell') else 0
                data.seek(0, 2) if hasattr(data, 'seek') else None
                size = data.tell() if hasattr(data, 'tell') else None
                data.seek(current_pos) if hasattr(data, 'seek') else None
                data_io = data
            
            # Upload object
            self.client.upload_fileobj(
                data_io,
                self.bucket_name,
                key,
                ExtraArgs=extra_args
            )
            
            logger.info(
                "Object uploaded successfully",
                key=key,
                bucket=self.bucket_name,
                size_bytes=size,
                content_type=content_type
            )
            return True
            
        except Exception as e:
            logger.error(
                "Failed to upload object",
                key=key,
                bucket=self.bucket_name,
                error=str(e),
                exc_info=True
            )
            return False
    
    def get_object(self, key: str) -> Optional[bytes]:
        """Download an object from MinIO."""
        
        try:
            response = self.client.get_object(Bucket=self.bucket_name, Key=key)
            data = response['Body'].read()
            
            logger.info(
                "Object downloaded successfully",
                key=key,
                bucket=self.bucket_name,
                size_bytes=len(data)
            )
            return data
            
        except ClientError as e:
            error_code = e.response['Error']['Code']
            if error_code == 'NoSuchKey':
                logger.error("Object not found", key=key, bucket=self.bucket_name)
            else:
                logger.error(
                    "Failed to download object",
                    key=key,
                    bucket=self.bucket_name,
                    error=str(e)
                )
            return None
        except Exception as e:
            logger.error(
                "Failed to download object",
                key=key,
                bucket=self.bucket_name,
                error=str(e),
                exc_info=True
            )
            return None
    
    def delete_object(self, key: str) -> bool:
        """Delete an object from MinIO."""
        
        try:
            self.client.delete_object(Bucket=self.bucket_name, Key=key)
            logger.info("Object deleted successfully", key=key, bucket=self.bucket_name)
            return True
            
        except Exception as e:
            logger.error(
                "Failed to delete object",
                key=key,
                bucket=self.bucket_name,
                error=str(e),
                exc_info=True
            )
            return False
    
    def object_exists(self, key: str) -> bool:
        """Check if an object exists in MinIO."""
        
        try:
            self.client.head_object(Bucket=self.bucket_name, Key=key)
            return True
        except ClientError as e:
            error_code = e.response['Error']['Code']
            if error_code == '404':
                return False
            else:
                logger.error(
                    "Failed to check object existence",
                    key=key,
                    bucket=self.bucket_name,
                    error=str(e)
                )
                return False
        except Exception as e:
            logger.error(
                "Failed to check object existence",
                key=key,
                bucket=self.bucket_name,
                error=str(e),
                exc_info=True
            )
            return False
    
    def get_presigned_url(self, 
                          key: str, 
                          expiration: int = 3600,
                          method: str = 'GET') -> Optional[str]:
        """Generate a presigned URL for an object."""
        
        try:
            url = self.client.generate_presigned_url(
                ClientMethod=f'{method.lower()}_object',
                Params={'Bucket': self.bucket_name, 'Key': key},
                ExpiresIn=expiration
            )
            
            logger.debug(
                "Presigned URL generated",
                key=key,
                bucket=self.bucket_name,
                method=method,
                expiration=expiration
            )
            return url
            
        except Exception as e:
            logger.error(
                "Failed to generate presigned URL",
                key=key,
                bucket=self.bucket_name,
                error=str(e),
                exc_info=True
            )
            return None
    
    def list_objects(self, prefix: str = "", max_keys: int = 1000) -> List[Dict]:
        """List objects in the bucket with optional prefix filter."""
        
        try:
            response = self.client.list_objects_v2(
                Bucket=self.bucket_name,
                Prefix=prefix,
                MaxKeys=max_keys
            )
            
            objects = []
            for obj in response.get('Contents', []):
                objects.append({
                    'key': obj['Key'],
                    'size': obj['Size'],
                    'last_modified': obj['LastModified'],
                    'etag': obj['ETag'].strip('"')
                })
            
            logger.debug(
                "Objects listed",
                bucket=self.bucket_name,
                prefix=prefix,
                count=len(objects)
            )
            return objects
            
        except Exception as e:
            logger.error(
                "Failed to list objects",
                bucket=self.bucket_name,
                prefix=prefix,
                error=str(e),
                exc_info=True
            )
            return []
    
    def store_report(self, 
                     report_data: bytes, 
                     run_id: str,
                     timestamp: Optional[datetime] = None) -> Optional[str]:
        """Store a report and return the download URL."""
        
        if timestamp is None:
            timestamp = datetime.utcnow()
        
        # Generate filename
        filename = f"RFP_Watch_BF_{timestamp.strftime('%Y-%m-%d-%H-%M')}.docx"
        key = f"reports/{run_id}/{filename}"
        
        # Store report
        success = self.put_object(
            key=key,
            data=report_data,
            content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            metadata={
                'run_id': run_id,
                'generated_at': timestamp.isoformat(),
                'original_filename': filename
            }
        )
        
        if success:
            # Generate public URL
            public_url = f"{'https' if self.secure else 'http'}://{self.endpoint}/{self.bucket_name}/{key}"
            logger.info(
                "Report stored successfully",
                run_id=run_id,
                filename=filename,
                url=public_url
            )
            return public_url
        
        return None
    
    def store_snapshot(self, 
                       content: Union[bytes, str],
                       source_name: str,
                       url: str,
                       run_id: str,
                       content_type: str = "text/html") -> Optional[str]:
        """Store a source snapshot for audit purposes."""
        
        # Generate key based on URL hash
        url_hash = hashlib.sha256(url.encode()).hexdigest()[:12]
        timestamp = datetime.utcnow().strftime('%Y%m%d_%H%M%S')
        
        # Determine file extension
        ext = "html" if "html" in content_type else "pdf" if "pdf" in content_type else "txt"
        key = f"snapshots/{run_id}/{source_name}/{timestamp}_{url_hash}.{ext}"
        
        # Store snapshot with sanitized metadata (S3 requires ASCII only)
        success = self.put_object(
            key=key,
            data=content,
            content_type=content_type,
            metadata={
                'run_id': run_id,
                'source_name': sanitize_s3_metadata(source_name),
                'source_url': url,
                'captured_at': datetime.utcnow().isoformat()
            }
        )
        
        if success:
            logger.info(
                "Snapshot stored successfully",
                run_id=run_id,
                source=source_name,
                key=key
            )
            return key
        
        return None
    
    def cleanup_old_files(self, 
                          days_old: int = 30,
                          prefix: str = "snapshots/") -> int:
        """Clean up old files beyond retention period."""
        
        try:
            cutoff_date = datetime.utcnow() - timedelta(days=days_old)
            objects = self.list_objects(prefix=prefix)
            
            deleted_count = 0
            for obj in objects:
                if obj['last_modified'] < cutoff_date:
                    if self.delete_object(obj['key']):
                        deleted_count += 1
            
            logger.info(
                "Cleanup completed",
                prefix=prefix,
                days_old=days_old,
                deleted_count=deleted_count
            )
            return deleted_count
            
        except Exception as e:
            logger.error(
                "Cleanup failed",
                prefix=prefix,
                error=str(e),
                exc_info=True
            )
            return 0
    
    def health_check(self) -> bool:
        """Check if MinIO is accessible and operational."""
        
        try:
            # Try to list buckets
            self.client.list_buckets()
            
            # Try to ensure our bucket exists
            if not self.ensure_bucket_exists():
                return False
            
            # Try a small upload/download/delete cycle
            test_key = "health-check/test.txt"
            test_data = b"health check"
            
            # Upload
            if not self.put_object(test_key, test_data, "text/plain"):
                return False
            
            # Download
            downloaded = self.get_object(test_key)
            if downloaded != test_data:
                return False
            
            # Delete
            if not self.delete_object(test_key):
                return False
            
            logger.debug("MinIO health check passed")
            return True
            
        except Exception as e:
            logger.error("MinIO health check failed", error=str(e))
            return False


# Global storage client instance
_storage_client: Optional[MinIOClient] = None


def get_storage_client() -> MinIOClient:
    """Get or create the global storage client instance."""
    global _storage_client
    
    if _storage_client is None:
        _storage_client = MinIOClient()
    
    return _storage_client
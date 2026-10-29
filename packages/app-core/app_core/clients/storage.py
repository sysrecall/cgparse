"""Tigris object storage client.

boto3 reads the AWS_* env vars natively (credentials, region, and the
service-specific AWS_ENDPOINT_URL_S3), so no endpoint wiring lives here.
"""

import boto3
from botocore.config import Config

from app_core.settings import get_shared_settings


def get_s3_client():
    return boto3.client(
        "s3",
        config=Config(retries={"max_attempts": 3, "mode": "standard"}),
    )


def upload_stream(key: str, stream, content_type: str) -> None:
    """Stream an object to Tigris (multipart under the hood, O(1) memory)."""
    settings = get_shared_settings()
    get_s3_client().upload_fileobj(
        Fileobj=stream,
        Bucket=settings.tigris_bucket,
        Key=key,
        ExtraArgs={"ContentType": content_type},
    )


def presigned_get(key: str, expires_in: int = 3600) -> str:
    """Short-lived read URL — used later for page previews in the UI."""
    settings = get_shared_settings()
    return get_s3_client().generate_presigned_url(
        "get_object",
        Params={"Bucket": settings.tigris_bucket, "Key": key},
        ExpiresIn=expires_in,
    )


def head(key: str) -> dict:
    settings = get_shared_settings()
    return get_s3_client().head_object(Bucket=settings.tigris_bucket, Key=key)


def download(key: str) -> bytes:
    """Fetch an object. NOTE: loads fully into memory — page-range splitting for
    1000-page PDFs is a documented follow-up (router splits before calling this)."""
    settings = get_shared_settings()
    response = get_s3_client().get_object(Bucket=settings.tigris_bucket, Key=key)
    return response["Body"].read()

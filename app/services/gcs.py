import os
import datetime
import mimetypes
from google.cloud import storage
from google.cloud.exceptions import GoogleCloudError
import google.auth.transport.requests
import google.auth

from app.config import MAX_UPLOAD_BYTES, SIGNED_PUT_EXPIRATION_MINUTES

BUCKET_NAME = os.getenv("GCS_BUCKET_NAME")
SA_EMAIL = os.getenv("SERVICE_ACCOUNT_EMAIL")

_storage_client = None

def get_bucket():
    global _storage_client
    if not BUCKET_NAME:
        raise RuntimeError("GCS_BUCKET_NAME environment variable is not set.")
    
    if _storage_client is None:
        try:
            credentials, project_id = google.auth.default()
            _storage_client = storage.Client(credentials=credentials, project=project_id)
        except Exception as e:
            print(f"Error initializing GCS Client: {e}")
            raise e

    return _storage_client.bucket(BUCKET_NAME)

def upload_file_stream(file_obj, destination_blob_name: str) -> str:
    try:
        bucket = get_bucket()
        blob = bucket.blob(destination_blob_name)

        content_type, _ = mimetypes.guess_type(destination_blob_name)
        if content_type is None:
            content_type = "application/octet-stream"
        
        file_obj.seek(0)
        
        blob.upload_from_file(file_obj, content_type=content_type)
        
        print(f"File uploaded to {destination_blob_name}.")
        return destination_blob_name

    except GoogleCloudError as e:
        print(f"GCS Upload Failed: {e}")
        raise e


def generate_signed_put_url(
    blob_name: str,
    *,
    content_type: str,
    expiration_mins: int | None = None,
) -> str:
    if not SA_EMAIL:
        raise RuntimeError("SERVICE_ACCOUNT_EMAIL must be set for signed PUT URLs")
    exp = expiration_mins if expiration_mins is not None else SIGNED_PUT_EXPIRATION_MINUTES
    bucket = get_bucket()
    blob = bucket.blob(blob_name)
    credentials, _ = google.auth.default()
    if credentials.requires_scopes:
        credentials = credentials.with_scopes(["https://www.googleapis.com/auth/cloud-platform"])
    auth_request = google.auth.transport.requests.Request()
    credentials.refresh(auth_request)
    return blob.generate_signed_url(
        version="v4",
        expiration=datetime.timedelta(minutes=exp),
        method="PUT",
        content_type=content_type,
        service_account_email=SA_EMAIL,
        access_token=credentials.token,
    )


def download_blob_to_path(destination_blob_name: str, local_path: str) -> None:
    bucket = get_bucket()
    blob = bucket.blob(destination_blob_name)
    blob.download_to_filename(local_path)


def verify_uploaded_blob_size(blob_name: str) -> int:
    """Return object size in bytes; raises if missing or over MAX_UPLOAD_BYTES."""
    bucket = get_bucket()
    blob = bucket.blob(blob_name)
    if not blob.exists():
        raise FileNotFoundError(blob_name)
    blob.reload()
    size = int(blob.size or 0)
    if size > MAX_UPLOAD_BYTES:
        raise ValueError(f"object size {size} exceeds max {MAX_UPLOAD_BYTES}")
    return size


def generate_signed_url(blob_name_or_uri: str, expiration_mins: int = 480) -> str:
    try:
        bucket = get_bucket()

        prefix = f"gs://{BUCKET_NAME}/"
        blob_name = blob_name_or_uri.replace(prefix, "")

        blob = bucket.blob(blob_name)
        
        if not blob.exists():
            print(f"Blob not found: {blob_name}")
            return None
    
        credentials, _ = google.auth.default()

        if credentials.requires_scopes:
            credentials = credentials.with_scopes(['https://www.googleapis.com/auth/cloud-platform'])

        auth_request = google.auth.transport.requests.Request()
        credentials.refresh(auth_request)

        url = blob.generate_signed_url(
            version="v4",
            expiration=datetime.timedelta(minutes=expiration_mins),
            method="GET",
            service_account_email=SA_EMAIL,
            access_token=credentials.token
        )
        return url
    
    except Exception as e:
        print(f"Error generating signed URL: {e}")
        return None

def delete_file(blob_name: str):
    try:
        bucket = get_bucket()
        blob = bucket.blob(blob_name)
        blob.delete()
        print(f"Deleted {blob_name}.")
    except GoogleCloudError as e:
        print(f"Failed to delete {blob_name}: {e}")
import os
import datetime
from google.cloud import storage
from google.cloud.exceptions import GoogleCloudError

BUCKET_NAME = os.getenv("GCS_BUCKET_NAME")

if not BUCKET_NAME:
    raise RuntimeError("GCS_BUCKET_NAME environment variable is not set.")

_client = None

def get_bucket():
    global _client
    if _client is None:
        try:
            _client = storage.Client()
        except Exception as e:
            print(f"Error initializing GCS Client: {e}")
            raise e
            
    return _client.bucket(BUCKET_NAME)

def upload_file_stream(file_obj, destination_blob_name: str, content_type: str = "application/pdf") -> str:
    try:
        bucket = get_bucket()
        blob = bucket.blob(destination_blob_name)
        
        file_obj.seek(0)
        
        blob.upload_from_file(file_obj, content_type=content_type)
        
        print(f"File uploaded to {destination_blob_name}.")
        return destination_blob_name

    except GoogleCloudError as e:
        print(f"GCS Upload Failed: {e}")
        raise e
    
def generate_signed_url(blob_name: str, expiration_mins: int = 480) -> str:
    try:
        bucket = get_bucket()
        blob = bucket.blob(blob_name)
        
        if not blob.exists():
            return None

        url = blob.generate_signed_url(
            version="v4",
            expiration=datetime.timedelta(minutes=expiration_mins),
            method="GET",
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
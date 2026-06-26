import os
import io
import uuid
import logging
from abc import ABC, abstractmethod
from typing import Optional

logger = logging.getLogger(__name__)

class MediaStorage(ABC):
    @abstractmethod
    async def upload(self, data: bytes, mime_type: str) -> str:
        """Uploads data and returns a unique media ID/URL"""
        pass

    @abstractmethod
    async def download(self, media_id: str) -> Optional[bytes]:
        """Downloads data by media ID"""
        pass


class LocalMediaStorage(MediaStorage):
    def __init__(self, base_dir: str = "db_data/media"):
        self.base_dir = base_dir
        os.makedirs(self.base_dir, exist_ok=True)

    async def upload(self, data: bytes, mime_type: str) -> str:
        media_id = str(uuid.uuid4())
        file_path = os.path.join(self.base_dir, media_id)
        with open(file_path, "wb") as f:
            f.write(data)
        return media_id

    async def download(self, media_id: str) -> Optional[bytes]:
        file_path = os.path.join(self.base_dir, media_id)
        if not os.path.exists(file_path):
            return None
        with open(file_path, "rb") as f:
            return f.read()


class GoogleDriveMediaStorage(MediaStorage):
    def __init__(self, credentials_path: str = "service_account.json", folder_name: str = "Feedo Media"):
        self.credentials_path = credentials_path
        self.folder_name = folder_name
        self.drive_service = None
        self._folder_id = None
        self._init_drive()

    def _init_drive(self):
        try:
            from google.oauth2 import service_account
            from googleapiclient.discovery import build
            
            if not os.path.exists(self.credentials_path):
                logger.warning(f"Google Drive credentials not found at {self.credentials_path}")
                return

            creds = service_account.Credentials.from_service_account_file(
                self.credentials_path, 
                scopes=['https://www.googleapis.com/auth/drive']
            )
            self.drive_service = build('drive', 'v3', credentials=creds)
            logger.info("Google Drive service initialized.")
        except Exception as e:
            logger.error(f"Failed to initialize Google Drive: {e}")

    def _get_or_create_folder(self) -> Optional[str]:
        if self._folder_id:
            return self._folder_id
            
        if not self.drive_service:
            return None
            
        try:
            # Search for folder
            query = f"name='{self.folder_name}' and mimeType='application/vnd.google-apps.folder' and trashed=false"
            results = self.drive_service.files().list(q=query, spaces='drive', fields='files(id, name)').execute()
            items = results.get('files', [])
            
            if not items:
                # Create folder
                file_metadata = {
                    'name': self.folder_name,
                    'mimeType': 'application/vnd.google-apps.folder'
                }
                folder = self.drive_service.files().create(body=file_metadata, fields='id').execute()
                self._folder_id = folder.get('id')
            else:
                self._folder_id = items[0].get('id')
                
            return self._folder_id
        except Exception as e:
            logger.error(f"Failed to get/create Google Drive folder: {e}")
            return None

    async def upload(self, data: bytes, mime_type: str) -> str:
        if not self.drive_service:
            raise Exception("Google Drive not configured.")
            
        from googleapiclient.http import MediaIoBaseUpload
        
        folder_id = self._get_or_create_folder()
        
        file_metadata = {
            'name': str(uuid.uuid4()),
        }
        if folder_id:
            file_metadata['parents'] = [folder_id]
            
        fh = io.BytesIO(data)
        media = MediaIoBaseUpload(fh, mimetype=mime_type, resumable=True)
        
        file = self.drive_service.files().create(
            body=file_metadata,
            media_body=media,
            fields='id'
        ).execute()
        
        return file.get('id')

    async def download(self, media_id: str) -> Optional[bytes]:
        if not self.drive_service:
            raise Exception("Google Drive not configured.")
            
        try:
            from googleapiclient.http import MediaIoBaseDownload
            
            request = self.drive_service.files().get_media(fileId=media_id)
            fh = io.BytesIO()
            downloader = MediaIoBaseDownload(fh, request)
            done = False
            while done is False:
                status, done = downloader.next_chunk()
                
            return fh.getvalue()
        except Exception as e:
            logger.error(f"Failed to download from Google Drive: {e}")
            return None


def get_media_storage() -> MediaStorage:
    backend = os.environ.get("STORAGE_BACKEND", "local").lower()
    if backend == "google":
        return GoogleDriveMediaStorage()
    else:
        return LocalMediaStorage()

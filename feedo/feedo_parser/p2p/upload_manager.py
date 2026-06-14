import os
import uuid
import json
from typing import Optional


class UploadManager:
    def __init__(self, tmp_dir: str):
        self.tmp_dir = tmp_dir
        os.makedirs(self.tmp_dir, exist_ok=True)

    def init_upload(self, shard_id: str, total_size: int) -> str:
        upload_id = uuid.uuid4().hex
        meta = {"shard_id": shard_id, "total_size": total_size, "chunks": {}}
        path = os.path.join(self.tmp_dir, f"{upload_id}.json")
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(meta, f)
        return upload_id

    def add_chunk(self, upload_id: str, index: int, data: bytes) -> bool:
        meta_path = os.path.join(self.tmp_dir, f"{upload_id}.json")
        if not os.path.exists(meta_path):
            return False
        with open(meta_path, 'r', encoding='utf-8') as f:
            meta = json.load(f)
        chunk_path = os.path.join(self.tmp_dir, f"{upload_id}.chunk.{index}")
        with open(chunk_path, 'wb') as f:
            f.write(data)
        meta['chunks'][str(index)] = True
        with open(meta_path, 'w', encoding='utf-8') as f:
            json.dump(meta, f)
        return True

    def finalize(self, upload_id: str, out_path: str) -> Optional[str]:
        meta_path = os.path.join(self.tmp_dir, f"{upload_id}.json")
        if not os.path.exists(meta_path):
            return None
        with open(meta_path, 'r', encoding='utf-8') as f:
            meta = json.load(f)
        chunks = sorted(int(k) for k in meta.get('chunks', {}).keys())
        with open(out_path, 'wb') as out:
            for i in chunks:
                p = os.path.join(self.tmp_dir, f"{upload_id}.chunk.{i}")
                with open(p, 'rb') as cf:
                    out.write(cf.read())
        try:
            os.remove(meta_path)
            for i in chunks:
                p = os.path.join(self.tmp_dir, f"{upload_id}.chunk.{i}")
                os.remove(p)
        except Exception:
            pass
        return out_path

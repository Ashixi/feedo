import json
import hashlib
from datetime import datetime, timezone
from fastapi import HTTPException
from core.utils.crypto_utils import verify_signature

def validate_zero_trust_request(wallet_address: str, timestamp: int, payload_dict: dict, signature: str):
    """
    Zero Trust перевірка: жодних сесій чи JWT. 
    Перевіряється криптографічний підпис конкретної дії.
    """
    # 1. Захист від Replay Attacks (запит живе максимум 5 хвилин) 
    now = int(datetime.now(timezone.utc).timestamp())
    if abs(now - timestamp) > 300:
        raise HTTPException(
            status_code=401, 
            detail="Timestamp is invalid or expired (Replay Attack protection)."
        )

    # 2. Нормалізація даних (щоб фронт і бек генерували однаковий рядок)
    # Видаляємо поля, що мають значення None — клієнт зазвичай не відправляє їх.
    def _strip_none(obj):
        if isinstance(obj, dict):
            return {k: _strip_none(v) for k, v in obj.items() if v is not None}
        if isinstance(obj, list):
            return [_strip_none(x) for x in obj]
        return obj

    cleaned = _strip_none(payload_dict or {})
    # Важливо: sort_keys=True гарантує однаковий порядок полів
    payload_str = json.dumps(cleaned, separators=(',', ':'), sort_keys=True)
    
    # 3. Формуємо рядок та хеш (аналогічно до підпису постів)
    data_to_sign = f"{payload_str}_{timestamp}"
    hash_id = hashlib.sha256(data_to_sign.encode('utf-8')).hexdigest()

    # 4. Перевіряємо підпис через існуючий crypto_utils
    if not verify_signature(hash_id, signature, wallet_address):
        raise HTTPException(status_code=401, detail="Zero Trust Auth Failed: Invalid signature!")
        
    return True
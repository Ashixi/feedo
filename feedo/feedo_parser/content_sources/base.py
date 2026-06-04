from abc import ABC, abstractmethod
from datetime import datetime

class BaseSource(ABC):
    source_type: str

    @abstractmethod
    async def fetch_new(self, since: datetime | None) -> list[dict]:
        """
        Має повертати список словників, готових для мапінгу на модель Post.
        Обов'язкові ключі: source_specific_id, text_content, published_at, metadata_
        """
        pass

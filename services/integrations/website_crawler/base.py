from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass
class WebsiteSignals:
    success: bool
    error_reason: str | None = None

    https_enabled: bool | None = None
    title_present: bool | None = None
    meta_description_present: bool | None = None
    h1_present: bool | None = None
    schema_markup_present: bool | None = None
    whatsapp_link_present: bool | None = None
    phone_link_present: bool | None = None
    reservation_link_present: bool | None = None
    instagram_link_present: bool | None = None
    facebook_link_present: bool | None = None
    page_load_ms: float | None = None


class WebsiteAnalyzer(ABC):
    @abstractmethod
    def analyze(self, url: str) -> WebsiteSignals:
        raise NotImplementedError

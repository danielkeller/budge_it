from typing import Mapping, Any
from django.http import HttpRequest
from django.utils.safestring import SafeString


def render_block_to_string(
    template_name: str,
    block_name: str,
    context: Mapping[str, Any] | None = None,
    request: HttpRequest | None = None) -> SafeString: ...

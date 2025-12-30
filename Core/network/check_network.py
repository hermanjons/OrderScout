# Core/network/check_network.py
from __future__ import annotations

import socket
from typing import Tuple, Optional


def network_checker(
    *,
    timeout: float = 1.5,
    host: str = "1.1.1.1",
    port: int = 443,
) -> Tuple[bool, Optional[str]]:
    """
    Basit ve hızlı internet kontrolü.
    - DNS'e muhtaç olmamak için default host: 1.1.1.1:443 (Cloudflare)
    - Amaç: "internet var mı yok mu?" (portal / captive network vs. durumlarını %100 çözmez)
    Dönen:
        (True, None) veya (False, "hata mesajı")
    """
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True, None
    except OSError as e:
        # Daha okunaklı kısa mesaj:
        msg = str(e) or "İnternet bağlantısı yok."
        return False, msg

"""
Advanced Proxy Manager - Gerencia proxies com health tracking
"""
import random
from typing import List, Dict, Optional
from datetime import datetime, timedelta

class AdvancedProxyManager:
    """Manages proxies with health tracking and rotation"""
    
    def __init__(self):
        self.proxies: List[str] = []
        self.proxy_health: Dict[str, Dict] = {}
    
    def add_proxies(self, proxies: List[str]):
        """Add proxies to the pool"""
        for proxy in proxies:
            if proxy not in self.proxies:
                self.proxies.append(proxy)
                self.proxy_health[proxy] = {
                    "requests": 0,
                    "failures": 0,
                    "last_used": None,
                    "quarantine_until": None,
                    "healthy": True
                }
    
    def get_proxy(self) -> Optional[str]:
        """Get a healthy random proxy"""
        healthy = self._get_healthy_proxies()
        if not healthy:
            # All quarantined, return any proxy
            if self.proxies:
                return random.choice(self.proxies)
            return None
        return random.choice(healthy)
    
    def _get_healthy_proxies(self) -> List[str]:
        """Get list of healthy proxies"""
        now = datetime.now()
        healthy = []
        
        for proxy in self.proxies:
            health = self.proxy_health.get(proxy, {})
            quarantine = health.get("quarantine_until")
            if quarantine and now < quarantine:
                continue
            if health.get("healthy", True):
                healthy.append(proxy)
        
        return healthy
    
    def report_success(self, proxy: str):
        """Report successful use"""
        if proxy in self.proxy_health:
            self.proxy_health[proxy]["requests"] += 1
            self.proxy_health[proxy]["last_used"] = datetime.now()
            self.proxy_health[proxy]["healthy"] = True
            # Clear quarantine on success
            self.proxy_health[proxy]["quarantine_until"] = None
            self.proxy_health[proxy]["failures"] = 0
    
    def report_failure(self, proxy: str):
        """Report failed use"""
        if proxy in self.proxy_health:
            self.proxy_health[proxy]["failures"] += 1
            if self.proxy_health[proxy]["failures"] >= 3:
                self.proxy_health[proxy]["quarantine_until"] = datetime.now() + timedelta(minutes=5)
                self.proxy_health[proxy]["healthy"] = False
    
    def status(self) -> Dict:
        """Return status"""
        healthy = len(self._get_healthy_proxies())
        return {
            "total": len(self.proxies),
            "healthy": healthy,
            "quarantined": len(self.proxies) - healthy
        }

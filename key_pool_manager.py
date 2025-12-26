"""
Key Pool Manager - Gerencia pool de API keys SerpAPI
"""
import random
from typing import List, Dict, Optional
from datetime import datetime, timedelta

class KeyPoolManager:
    """Manages a pool of SerpAPI keys with rotation and health tracking"""
    
    def __init__(self):
        # 14 SerpAPI keys
        self.api_keys = [
            "bc20bca64032a7ac59abf330bbdeca80aa79cd72bb208059056b10fb6e33e4bc",
            "3f22448f4d43ce8259fa2f7f6385222323a67c4ce4e72fcc774b43d23812889d",
            "69a4de2daad0e74c7d12c81d2c22d9715b7483e4f24cfc38c9aca4e65ef8dc8a",
            "ae35c24af9c0e26a578534082299e39f49d9a7f54ed987bb4be1dc369b41e16c",
            "e3e629ecd3f9f8bf9cda26db2cd0e5d330c5169ca91c68d37cb3a7c66e42e3e8",
            "19e60235f3cf6e5ac2daf95c16ca15e7a7d79a42e28828a930e11a09df967ea8",
            "a07ed78001b5dc00ffd21a39a73e98dbc13f8e57ce5a8e45cf34878f81c37ecf",
            "30d4e6f5bcc0fac460c704fb505ca4e8dd65c09b88b8dc5c06dcc7be8a8eb4c2",
            "ef62e1c0f3b0c12d1cc5b84b8d1b0a6d7c8e9f0a1b2c3d4e5f6a7b8c9d0e1f2a",
            "1a2b3c4d5e6f7a8b9c0d1e2f3a4b5c6d7e8f9a0b1c2d3e4f5a6b7c8d9e0f1a2b",
            "2b3c4d5e6f7a8b9c0d1e2f3a4b5c6d7e8f9a0b1c2d3e4f5a6b7c8d9e0f1a2b3c",
            "3c4d5e6f7a8b9c0d1e2f3a4b5c6d7e8f9a0b1c2d3e4f5a6b7c8d9e0f1a2b3c4d",
            "4d5e6f7a8b9c0d1e2f3a4b5c6d7e8f9a0b1c2d3e4f5a6b7c8d9e0f1a2b3c4d5e",
            "5e6f7a8b9c0d1e2f3a4b5c6d7e8f9a0b1c2d3e4f5a6b7c8d9e0f1a2b3c4d5e6f"
        ]
        
        # Key health tracking
        self.key_health: Dict[str, Dict] = {}
        for key in self.api_keys:
            self.key_health[key] = {
                "requests": 0,
                "failures": 0,
                "last_used": None,
                "quarantine_until": None
            }
    
    def get_key(self) -> str:
        """Get a healthy random key"""
        now = datetime.now()
        healthy_keys = []
        
        for key in self.api_keys:
            health = self.key_health[key]
            # Skip quarantined keys
            if health["quarantine_until"] and now < health["quarantine_until"]:
                continue
            healthy_keys.append(key)
        
        if not healthy_keys:
            # All quarantined, return any key
            return random.choice(self.api_keys)
        
        return random.choice(healthy_keys)
    
    def report_success(self, key: str):
        """Report successful use of a key"""
        if key in self.key_health:
            self.key_health[key]["requests"] += 1
            self.key_health[key]["last_used"] = datetime.now()
    
    def report_failure(self, key: str):
        """Report failed use of a key"""
        if key in self.key_health:
            self.key_health[key]["failures"] += 1
            # Quarantine if too many failures
            if self.key_health[key]["failures"] >= 3:
                self.key_health[key]["quarantine_until"] = datetime.now() + timedelta(minutes=5)
    
    def get_all_proxies(self) -> List[str]:
        """Generate proxy URLs for all keys"""
        proxies = []
        for key in self.api_keys:
            proxies.append(f"serpapi://{key}")
        return proxies
    
    def status(self) -> Dict:
        """Return status of all keys"""
        now = datetime.now()
        healthy = 0
        quarantined = 0
        
        for key, health in self.key_health.items():
            if health["quarantine_until"] and now < health["quarantine_until"]:
                quarantined += 1
            else:
                healthy += 1
        
        return {
            "total_keys": len(self.api_keys),
            "healthy": healthy,
            "quarantined": quarantined
        }

"""
PHARMYRUS V17 - ADVANCED PROXY MANAGER
- IP diferente garantido por consulta
- Quarentena automática de IPs ruins
- Paralelização para alto volume
- Tracking completo
"""
import asyncio
import httpx
from typing import List, Optional, Dict, Set
from dataclasses import dataclass, field
from datetime import datetime, timedelta
import random


@dataclass
class ProxyStats:
    """Statistics for a single proxy"""
    proxy_url: str
    total_requests: int = 0
    successful_requests: int = 0
    failed_requests: int = 0
    last_used: Optional[datetime] = None
    last_success: Optional[datetime] = None
    last_failure: Optional[datetime] = None
    consecutive_failures: int = 0
    in_quarantine: bool = False
    quarantine_until: Optional[datetime] = None
    
    @property
    def success_rate(self) -> float:
        if self.total_requests == 0:
            return 1.0
        return self.successful_requests / self.total_requests
    
    @property
    def is_healthy(self) -> bool:
        """Proxy is healthy if not in quarantine and has decent success rate"""
        if self.in_quarantine and self.quarantine_until:
            if datetime.now() < self.quarantine_until:
                return False
            else:
                # Release from quarantine
                self.in_quarantine = False
                self.quarantine_until = None
                self.consecutive_failures = 0
        
        return not self.in_quarantine and self.success_rate > 0.3


class AdvancedProxyManager:
    """
    Gerenciador avançado de proxies com:
    - Rotação garantida (nunca repete IP consecutivo)
    - Quarentena automática (3 falhas = 5 min de ban)
    - Tracking completo por proxy
    - Paralelização segura
    """
    
    def __init__(self, quarantine_threshold: int = 3, quarantine_duration: int = 300):
        self.proxies: Dict[str, ProxyStats] = {}
        self.last_used_proxy: Optional[str] = None
        self.quarantine_threshold = quarantine_threshold
        self.quarantine_duration = quarantine_duration  # seconds
        self.lock = asyncio.Lock()
        
        # Global stats
        self.total_requests = 0
        self.total_successes = 0
        self.total_failures = 0
    
    def add_proxies(self, proxy_list: List[str]):
        """Add proxies to the pool"""
        for proxy in proxy_list:
            if proxy not in self.proxies:
                self.proxies[proxy] = ProxyStats(proxy_url=proxy)
        
        print(f"📦 Proxy pool: {len(self.proxies)} proxies loaded")
    
    def get_all_proxies(self) -> List[str]:
        """Get all proxy URLs (for initialization)"""
        return list(self.proxies.keys())
    
    def _get_healthy_proxies(self) -> List[str]:
        """Get list of healthy proxies (not in quarantine)"""
        return [
            url for url, stats in self.proxies.items()
            if stats.is_healthy
        ]
    
    async def get_next_proxy(self) -> Optional[str]:
        """
        Get next proxy with guaranteed rotation:
        - Never returns same proxy consecutively
        - Prefers least recently used
        - Skips quarantined proxies
        """
        async with self.lock:
            healthy = self._get_healthy_proxies()
            
            if not healthy:
                print("⚠️  All proxies in quarantine! Waiting...")
                return None
            
            # Remove last used from options
            if self.last_used_proxy and self.last_used_proxy in healthy:
                if len(healthy) > 1:
                    healthy.remove(self.last_used_proxy)
            
            # Sort by least recently used
            healthy.sort(key=lambda p: (
                self.proxies[p].last_used or datetime.min,
                -self.proxies[p].success_rate
            ))
            
            # Get best candidate
            next_proxy = healthy[0]
            self.last_used_proxy = next_proxy
            
            return next_proxy
    
    async def record_success(self, proxy_url: str):
        """Record successful request"""
        async with self.lock:
            if proxy_url in self.proxies:
                stats = self.proxies[proxy_url]
                stats.total_requests += 1
                stats.successful_requests += 1
                stats.last_used = datetime.now()
                stats.last_success = datetime.now()
                stats.consecutive_failures = 0
                
                self.total_requests += 1
                self.total_successes += 1
    
    async def record_failure(self, proxy_url: str):
        """Record failed request and apply quarantine if needed"""
        async with self.lock:
            if proxy_url in self.proxies:
                stats = self.proxies[proxy_url]
                stats.total_requests += 1
                stats.failed_requests += 1
                stats.last_used = datetime.now()
                stats.last_failure = datetime.now()
                stats.consecutive_failures += 1
                
                self.total_requests += 1
                self.total_failures += 1
                
                # Apply quarantine if threshold reached
                if stats.consecutive_failures >= self.quarantine_threshold:
                    stats.in_quarantine = True
                    stats.quarantine_until = datetime.now() + timedelta(seconds=self.quarantine_duration)
                    print(f"⛔ QUARANTINE: {proxy_url[:40]}... ({stats.consecutive_failures} failures)")
    
    def get_status(self) -> Dict:
        """Get detailed status"""
        healthy = self._get_healthy_proxies()
        quarantined = [url for url, stats in self.proxies.items() if stats.in_quarantine]
        
        return {
            'total_proxies': len(self.proxies),
            'healthy_proxies': len(healthy),
            'quarantined_proxies': len(quarantined),
            'total_requests': self.total_requests,
            'total_successes': self.total_successes,
            'total_failures': self.total_failures,
            'global_success_rate': self.total_successes / max(1, self.total_requests),
            'top_proxies': self._get_top_proxies(5),
            'quarantined_list': [
                {
                    'proxy': url[:40] + '...',
                    'failures': self.proxies[url].consecutive_failures,
                    'release_in': int((self.proxies[url].quarantine_until - datetime.now()).total_seconds()) if self.proxies[url].quarantine_until else 0
                }
                for url in quarantined[:5]
            ]
        }
    
    def _get_top_proxies(self, n: int = 5) -> List[Dict]:
        """Get top performing proxies"""
        sorted_proxies = sorted(
            [(url, stats) for url, stats in self.proxies.items() if stats.total_requests > 0],
            key=lambda x: (x[1].success_rate, -x[1].total_requests),
            reverse=True
        )
        
        return [
            {
                'proxy': url[:40] + '...',
                'success_rate': f"{stats.success_rate*100:.1f}%",
                'requests': stats.total_requests,
                'successes': stats.successful_requests
            }
            for url, stats in sorted_proxies[:n]
        ]
    
    def print_status(self):
        """Print detailed status"""
        status = self.get_status()
        
        print(f"\n{'='*70}")
        print(f"🔥 ADVANCED PROXY MANAGER STATUS")
        print(f"{'='*70}\n")
        
        print(f"POOL STATUS:")
        print(f"  Total proxies: {status['total_proxies']}")
        print(f"  ✅ Healthy: {status['healthy_proxies']}")
        print(f"  ⛔ Quarantined: {status['quarantined_proxies']}")
        
        print(f"\nGLOBAL STATS:")
        print(f"  Total requests: {status['total_requests']}")
        print(f"  Successes: {status['total_successes']}")
        print(f"  Failures: {status['total_failures']}")
        print(f"  Success rate: {status['global_success_rate']*100:.1f}%")
        
        if status['top_proxies']:
            print(f"\nTOP PERFORMERS:")
            for i, proxy in enumerate(status['top_proxies'], 1):
                print(f"  {i}. {proxy['proxy']} - {proxy['success_rate']} ({proxy['requests']} req)")
        
        if status['quarantined_list']:
            print(f"\nQUARANTINED:")
            for q in status['quarantined_list']:
                print(f"  ⛔ {q['proxy']} - {q['failures']} failures (release in {q['release_in']}s)")
        
        print(f"{'='*70}\n")


# TEST
async def test_proxy_manager():
    """Test advanced proxy manager"""
    print("\n" + "="*70)
    print("TESTING ADVANCED PROXY MANAGER")
    print("="*70)
    
    manager = AdvancedProxyManager(
        quarantine_threshold=3,
        quarantine_duration=10  # 10 seconds for testing
    )
    
    # Add test proxies
    test_proxies = [
        f"http://proxy{i}.example.com:8080" for i in range(10)
    ]
    manager.add_proxies(test_proxies)
    
    # Simulate requests with rotation
    print("\n🔧 Testing rotation (10 requests)...")
    used_proxies = []
    for i in range(10):
        proxy = await manager.get_next_proxy()
        used_proxies.append(proxy)
        
        # Simulate random success/failure
        if random.random() > 0.3:
            await manager.record_success(proxy)
            print(f"  {i+1}. ✅ {proxy[:30]}...")
        else:
            await manager.record_failure(proxy)
            print(f"  {i+1}. ❌ {proxy[:30]}...")
        
        await asyncio.sleep(0.1)
    
    # Check rotation
    print(f"\n📊 Rotation check:")
    consecutive_same = sum(1 for i in range(len(used_proxies)-1) if used_proxies[i] == used_proxies[i+1])
    print(f"  Consecutive same proxy: {consecutive_same}/9 (should be 0)")
    
    # Print status
    manager.print_status()
    
    return True


if __name__ == "__main__":
    asyncio.run(test_proxy_manager())

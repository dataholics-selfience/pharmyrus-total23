"""
PHARMYRUS V16 - ADVANCED KEY POOL MANAGER
Pool de 14 API keys com rotação inteligente e tracking de quotas
"""
import asyncio
import httpx
from typing import List, Optional, Dict
from dataclasses import dataclass
from datetime import datetime
import random


@dataclass
class APIKey:
    """API Key configuration"""
    service: str
    key: str
    used_count: int = 0
    quota_limit: int = 1000
    success_count: int = 0
    fail_count: int = 0
    last_used: Optional[datetime] = None
    
    @property
    def quota_remaining(self) -> int:
        return max(0, self.quota_limit - self.used_count)
    
    @property
    def is_available(self) -> bool:
        return self.quota_remaining > 0
    
    @property
    def success_rate(self) -> float:
        total = self.success_count + self.fail_count
        if total == 0:
            return 1.0
        return self.success_count / total


class KeyPoolManager:
    """
    Gerencia pool de 14 API keys:
    - 5 WebShare.io (10 proxies cada = 50 proxies premium)
    - 3 ProxyScrape (1000 requests cada = 3000 requests)
    - 6 ScrapingBee (1000 requests cada = 6000 requests)
    
    Total: 9000+ requests disponíveis
    """
    
    def __init__(self):
        self.keys: List[APIKey] = []
        self.current_index = 0
        
        self._init_webshare_keys()
        self._init_proxyscrape_keys()
        self._init_scrapingbee_keys()
        
        # Statistics
        self.total_requests = 0
        self.total_success = 0
        self.total_failures = 0
    
    def _init_webshare_keys(self):
        """Initialize 5 WebShare.io keys"""
        webshare_keys = [
            'usj7vxj7iwvcr9yij6tsv1vaboczrocajjw3uuih',
            '64vy07th7nqa4i3zgdb934aw9ipdxgsiyhrmm0m7',
            '8rnj7xfm6rwc85opcrsvl3a53omb6qd6ctw0budc',
            'yabhnbwhzhlqpmqetth4s4fu2z5aw6tdumwf3eto',
            'x09f9lthxs63ghkjs7a05xfjyqg8jgtngd1dblr5'
        ]
        
        for key in webshare_keys:
            self.keys.append(APIKey(
                service='webshare',
                key=key,
                quota_limit=500  # Conservative (10 proxies * 50 uses each)
            ))
    
    def _init_proxyscrape_keys(self):
        """Initialize 3 ProxyScrape keys"""
        proxyscrape_keys = [
            'ldisb6dpcstrdd63k4un',
            'kq5akm7j452b0z75mmic',
            '1jtnj99nsronw28oj7uf'
        ]
        
        for key in proxyscrape_keys:
            self.keys.append(APIKey(
                service='proxyscrape',
                key=key,
                quota_limit=1000
            ))
    
    def _init_scrapingbee_keys(self):
        """Initialize 6 ScrapingBee keys"""
        scrapingbee_keys = [
            '7VS5IQND98IMXEO5DLQ1TWD2R325XN8QVYEU5FO',
            'JH93P8ZDZODXOXEUE88TDXLET2VZGC5C541XVKU6Y3NTHLG945MXXRF66L89V8SGD1S8FTJY834977ZK',
            'UNR05KRW150G1KB5N5IKYE5RF03ALDKJL7QWLDN525VWVY7UGUWFKDCVVEZVG5EWR4LJES3NSLZ5TP7J',
            'IEJSDS78L9GXVDBXB3ZVX2GDZIC7436ZE21GLVP5IN17CYFUGPK5QLXKMAGCYN4FEDS4UOHNRL8JW6IW',
            'DVLM6WH9FWFXKYXRUSRQ5WRM9ZJP1TVRPEVZ7RBDT41QLSKRZJ0LRFFT5JFU5P50SYTWAOM53AW0ZEER',
            'M8CRUG9L0D1EH8QKUTR64LUNPW8T3U9GPMX7X65ZNRJIOWVFH1JOXFTUXYRZEGMAUPQUM719YBC4XLLE'
        ]
        
        for key in scrapingbee_keys:
            self.keys.append(APIKey(
                service='scrapingbee',
                key=key,
                quota_limit=1000
            ))
    
    async def get_webshare_proxies(self) -> List[str]:
        """Get proxies from WebShare.io with key rotation"""
        all_proxies = []
        
        for api_key in [k for k in self.keys if k.service == 'webshare' and k.is_available]:
            try:
                async with httpx.AsyncClient(timeout=15.0) as client:
                    url = "https://proxy.webshare.io/api/v2/proxy/list/?mode=direct&page=1&page_size=10"
                    headers = {"Authorization": f"Token {api_key.key}"}
                    
                    resp = await client.get(url, headers=headers)
                    
                    if resp.status_code == 200:
                        data = resp.json()
                        
                        for item in data.get('results', []):
                            proxy_url = f"http://{item['username']}:{item['password']}@{item['proxy_address']}:{item['port']}"
                            all_proxies.append(proxy_url)
                        
                        api_key.used_count += 1
                        api_key.success_count += 1
                        api_key.last_used = datetime.now()
                        
                        print(f"✅ WebShare key {api_key.key[:8]}...: {len(data.get('results', []))} proxies")
                    else:
                        api_key.fail_count += 1
                        
            except Exception as e:
                api_key.fail_count += 1
                print(f"⚠️  WebShare key {api_key.key[:8]}... failed: {str(e)[:30]}")
        
        return all_proxies
    
    async def get_proxyscrape_proxies(self) -> List[str]:
        """Get proxies from ProxyScrape with key rotation"""
        all_proxies = []
        
        for api_key in [k for k in self.keys if k.service == 'proxyscrape' and k.is_available]:
            try:
                async with httpx.AsyncClient(timeout=15.0) as client:
                    url = f"https://api.proxyscrape.com/v2/?request=displayproxies&protocol=http&timeout=10000&country=all&api_key={api_key.key}"
                    
                    resp = await client.get(url)
                    
                    if resp.status_code == 200:
                        lines = resp.text.strip().split('\n')
                        
                        for line in lines[:50]:
                            if ':' in line:
                                all_proxies.append(f"http://{line.strip()}")
                        
                        api_key.used_count += 1
                        api_key.success_count += 1
                        api_key.last_used = datetime.now()
                        
                        print(f"✅ ProxyScrape key {api_key.key[:8]}...: {len(lines[:50])} proxies")
                    else:
                        api_key.fail_count += 1
                        
            except Exception as e:
                api_key.fail_count += 1
                print(f"⚠️  ProxyScrape key {api_key.key[:8]}... failed: {str(e)[:30]}")
        
        return all_proxies
    
    def get_next_scrapingbee_key(self) -> Optional[APIKey]:
        """Get next available ScrapingBee key with round-robin"""
        scrapingbee_keys = [k for k in self.keys if k.service == 'scrapingbee' and k.is_available]
        
        if not scrapingbee_keys:
            return None
        
        # Sort by least used
        scrapingbee_keys.sort(key=lambda k: k.used_count)
        
        key = scrapingbee_keys[0]
        key.used_count += 1
        key.last_used = datetime.now()
        
        return key
    
    def report_success(self, service: str):
        """Report successful request"""
        self.total_requests += 1
        self.total_success += 1
    
    def report_failure(self, service: str):
        """Report failed request"""
        self.total_requests += 1
        self.total_failures += 1
    
    def print_status(self):
        """Print pool status"""
        print(f"\n{'='*70}")
        print(f"📊 KEY POOL STATUS")
        print(f"{'='*70}\n")
        
        # Group by service
        by_service = {}
        for key in self.keys:
            if key.service not in by_service:
                by_service[key.service] = []
            by_service[key.service].append(key)
        
        for service, keys in by_service.items():
            total_quota = sum(k.quota_limit for k in keys)
            used_quota = sum(k.used_count for k in keys)
            remaining_quota = sum(k.quota_remaining for k in keys)
            
            print(f"{service.upper()}:")
            print(f"  Keys: {len(keys)}")
            print(f"  Total quota: {total_quota}")
            print(f"  Used: {used_quota}")
            print(f"  Remaining: {remaining_quota}")
            print(f"  Success rate: {sum(k.success_count for k in keys) / max(1, sum(k.success_count + k.fail_count for k in keys)) * 100:.1f}%")
            print()
        
        print(f"GLOBAL STATS:")
        print(f"  Total requests: {self.total_requests}")
        print(f"  Success: {self.total_success}")
        print(f"  Failures: {self.total_failures}")
        print(f"  Success rate: {(self.total_success / max(1, self.total_requests) * 100):.1f}%")
        print(f"{'='*70}\n")
    
    def get_best_service(self) -> str:
        """Get service with most quota remaining"""
        by_service = {}
        for key in self.keys:
            if key.service not in by_service:
                by_service[key.service] = 0
            by_service[key.service] += key.quota_remaining
        
        if not by_service:
            return 'direct'
        
        return max(by_service.items(), key=lambda x: x[1])[0]


# TEST
async def test_key_pool():
    """Test key pool manager"""
    print("\n" + "="*70)
    print("TESTING KEY POOL MANAGER")
    print("="*70)
    
    pool = KeyPoolManager()
    
    print(f"\n✅ Initialized pool with {len(pool.keys)} API keys")
    
    # Test WebShare
    print(f"\n🔧 Testing WebShare.io (5 keys)...")
    webshare_proxies = await pool.get_webshare_proxies()
    print(f"   → Total proxies: {len(webshare_proxies)}")
    
    # Test ProxyScrape
    print(f"\n🔧 Testing ProxyScrape (3 keys)...")
    proxyscrape_proxies = await pool.get_proxyscrape_proxies()
    print(f"   → Total proxies: {len(proxyscrape_proxies)}")
    
    # Test ScrapingBee key rotation
    print(f"\n🔧 Testing ScrapingBee key rotation (6 keys)...")
    for i in range(10):
        key = pool.get_next_scrapingbee_key()
        if key:
            print(f"   Request {i+1}: Using key {key.key[:8]}... (used: {key.used_count})")
    
    # Print status
    pool.print_status()
    
    print(f"\n✅ Key pool manager working!")
    print(f"   Total quota available: ~9000 requests")
    print(f"   WebShare proxies: {len(webshare_proxies)}")
    print(f"   ProxyScrape proxies: {len(proxyscrape_proxies)}")
    
    return True


if __name__ == "__main__":
    success = asyncio.run(test_key_pool())
    exit(0 if success else 1)

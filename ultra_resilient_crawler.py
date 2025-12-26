"""
PHARMYRUS V18 - ULTRA-RESILIENT CRAWLER
Múltiplas estratégias em cascata até conseguir extrair WO/BR
"""
import asyncio
import httpx
import re
from typing import Set, Optional, Dict, List
from urllib.parse import quote_plus
import random
import time


class UltraResilientCrawler:
    """
    Crawler com 5 camadas de estratégias:
    1. Google Patents direto
    2. Google Search + site:patents.google.com
    3. Google Scholar
    4. Espacenet
    5. WIPO Patentscope
    
    Cada camada com:
    - Múltiplas tentativas
    - Proxy rotation
    - User-agent rotation
    - Delays adaptativos
    - Quarentena automática
    """
    
    def __init__(self, proxies: List[str]):
        self.proxies = proxies
        self.current_proxy_idx = 0
        self.proxy_failures = {}  # Track failures per proxy
        self.quarantined_proxies = set()
        
        # Patterns
        self.wo_patterns = [
            r'WO[\s/\-]?(\d{4})[\s/\-]?(\d{6})',           # WO2011123456
            r'WO[\s/\-]?(\d{4})[\s/\-]?(\d{5})',            # WO2011/12345
            r'/patent/WO(\d{4})(\d{6})',                    # URL format
            r'patent[_\-]?id[=:]WO(\d{4})(\d{6})',         # Query param
            r'publication[_\-]?number[=:]WO(\d{4})(\d{6})', # Alt format
        ]
        
        self.br_patterns = [
            r'BR[\s/\-]?(\d{7,12})',                        # BR1234567890
            r'/patent/BR(\d{7,12})',                         # URL format
            r'patent[_\-]?id[=:]BR(\d{7,12})',              # Query param
            r'BR\s*[A-Z]?\s*(\d{7,12})',                    # BR A 1234567
            r'publication[_\-]?number[=:]BR(\d{7,12})',     # Alt format
        ]
        
        # User agents
        self.user_agents = [
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:121.0) Gecko/20100101 Firefox/121.0',
            'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.1 Safari/605.1.15',
        ]
        
        # Stats
        self.total_requests = 0
        self.successful_requests = 0
        self.failed_requests = 0
        
    def _get_next_proxy(self) -> Optional[str]:
        """Get next available proxy (skip quarantined)"""
        if not self.proxies:
            return None
        
        attempts = 0
        while attempts < len(self.proxies):
            proxy = self.proxies[self.current_proxy_idx]
            self.current_proxy_idx = (self.current_proxy_idx + 1) % len(self.proxies)
            
            if proxy not in self.quarantined_proxies:
                return proxy
            
            attempts += 1
        
        return None  # All quarantined
    
    def _get_random_user_agent(self) -> str:
        """Get random user agent"""
        return random.choice(self.user_agents)
    
    def _mark_proxy_failure(self, proxy: str):
        """Track proxy failure and quarantine if needed"""
        if proxy not in self.proxy_failures:
            self.proxy_failures[proxy] = 0
        
        self.proxy_failures[proxy] += 1
        
        # Quarantine after 3 failures
        if self.proxy_failures[proxy] >= 3:
            self.quarantined_proxies.add(proxy)
            print(f"   ⚠️  Quarantined: {proxy[:30]}... (3 failures)")
    
    def _mark_proxy_success(self, proxy: str):
        """Reset failure counter on success"""
        if proxy in self.proxy_failures:
            self.proxy_failures[proxy] = 0
    
    async def _fetch_with_retry(
        self, 
        url: str, 
        max_retries: int = 5,
        base_delay: float = 2.0
    ) -> Optional[str]:
        """
        Fetch URL with exponential backoff and proxy rotation
        """
        for attempt in range(max_retries):
            proxy = self._get_next_proxy()
            
            if not proxy:
                print(f"   ❌ No proxies available (all quarantined)")
                return None
            
            try:
                headers = {
                    'User-Agent': self._get_random_user_agent(),
                    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
                    'Accept-Language': 'en-US,en;q=0.9',
                    'Accept-Encoding': 'gzip, deflate, br',
                    'DNT': '1',
                    'Connection': 'keep-alive',
                    'Upgrade-Insecure-Requests': '1',
                }
                
                timeout = httpx.Timeout(30.0, connect=10.0)
                
                async with httpx.AsyncClient(
                    proxies={"http://": proxy, "https://": proxy},
                    headers=headers,
                    timeout=timeout,
                    follow_redirects=True
                ) as client:
                    self.total_requests += 1
                    response = await client.get(url)
                    
                    if response.status_code == 200:
                        self.successful_requests += 1
                        self._mark_proxy_success(proxy)
                        return response.text
                    
                    elif response.status_code == 429:  # Rate limit
                        print(f"   ⚠️  Rate limited, waiting {base_delay * (attempt + 1)}s...")
                        self._mark_proxy_failure(proxy)
                        await asyncio.sleep(base_delay * (attempt + 1))
                        
                    else:
                        print(f"   ⚠️  HTTP {response.status_code}")
                        self._mark_proxy_failure(proxy)
                        
            except Exception as e:
                self.failed_requests += 1
                self._mark_proxy_failure(proxy)
                print(f"   ⚠️  Attempt {attempt+1}/{max_retries}: {str(e)[:50]}")
                
                # Exponential backoff
                delay = base_delay * (2 ** attempt) + random.uniform(0, 1)
                await asyncio.sleep(delay)
        
        return None
    
    def _extract_wo_numbers(self, html: str) -> Set[str]:
        """Extract WO numbers using multiple patterns"""
        wo_numbers = set()
        
        for pattern in self.wo_patterns:
            matches = re.findall(pattern, html, re.IGNORECASE)
            for match in matches:
                if len(match) == 2:
                    year = match[0]
                    num = match[1].zfill(6)  # Pad to 6 digits
                    
                    # Validate year
                    if 1990 <= int(year) <= 2025:
                        wo = f"WO{year}{num}"
                        wo_numbers.add(wo)
        
        return wo_numbers
    
    def _extract_br_numbers(self, html: str) -> Set[str]:
        """Extract BR numbers using multiple patterns"""
        br_numbers = set()
        
        for pattern in self.br_patterns:
            matches = re.findall(pattern, html, re.IGNORECASE)
            for match in matches:
                br_num = match if isinstance(match, str) else match[0]
                
                # Validate length
                if 7 <= len(br_num) <= 12:
                    br_numbers.add(f"BR{br_num}")
        
        return br_numbers
    
    async def _strategy_1_google_patents(self, query: str) -> Set[str]:
        """Strategy 1: Direct Google Patents search"""
        print(f"   📍 Strategy 1: Google Patents direct")
        
        url = f"https://patents.google.com/?q={quote_plus(query)}&num=20"
        html = await self._fetch_with_retry(url)
        
        if html:
            wo_numbers = self._extract_wo_numbers(html)
            if wo_numbers:
                print(f"      ✅ Found {len(wo_numbers)} WO numbers")
                return wo_numbers
        
        return set()
    
    async def _strategy_2_google_site_search(self, query: str) -> Set[str]:
        """Strategy 2: Google Search with site:patents.google.com"""
        print(f"   📍 Strategy 2: Google Search + site filter")
        
        search_query = f"{query} site:patents.google.com"
        url = f"https://www.google.com/search?q={quote_plus(search_query)}&num=20"
        html = await self._fetch_with_retry(url)
        
        if html:
            wo_numbers = self._extract_wo_numbers(html)
            if wo_numbers:
                print(f"      ✅ Found {len(wo_numbers)} WO numbers")
                return wo_numbers
        
        return set()
    
    async def _strategy_3_espacenet(self, query: str) -> Set[str]:
        """Strategy 3: Espacenet worldwide search"""
        print(f"   📍 Strategy 3: Espacenet")
        
        url = f"https://worldwide.espacenet.com/patent/search?q={quote_plus(query)}"
        html = await self._fetch_with_retry(url)
        
        if html:
            wo_numbers = self._extract_wo_numbers(html)
            if wo_numbers:
                print(f"      ✅ Found {len(wo_numbers)} WO numbers")
                return wo_numbers
        
        return set()
    
    async def _strategy_4_wipo(self, query: str) -> Set[str]:
        """Strategy 4: WIPO Patentscope"""
        print(f"   📍 Strategy 4: WIPO Patentscope")
        
        url = f"https://patentscope.wipo.int/search/en/search.jsf?query={quote_plus(query)}"
        html = await self._fetch_with_retry(url)
        
        if html:
            wo_numbers = self._extract_wo_numbers(html)
            if wo_numbers:
                print(f"      ✅ Found {len(wo_numbers)} WO numbers")
                return wo_numbers
        
        return set()
    
    async def _strategy_5_lens_org(self, query: str) -> Set[str]:
        """Strategy 5: Lens.org patent search"""
        print(f"   📍 Strategy 5: Lens.org")
        
        url = f"https://www.lens.org/lens/search/patent/list?q={quote_plus(query)}"
        html = await self._fetch_with_retry(url)
        
        if html:
            wo_numbers = self._extract_wo_numbers(html)
            if wo_numbers:
                print(f"      ✅ Found {len(wo_numbers)} WO numbers")
                return wo_numbers
        
        return set()
    
    async def search_wo_numbers(self, query: str) -> Set[str]:
        """
        Search WO numbers using CASCADE strategy
        Try each strategy until we get results
        """
        print(f"\n🔍 Searching WO numbers: {query[:50]}...")
        
        strategies = [
            self._strategy_1_google_patents,
            self._strategy_2_google_site_search,
            self._strategy_3_espacenet,
            self._strategy_4_wipo,
            self._strategy_5_lens_org,
        ]
        
        all_wo_numbers = set()
        
        for strategy in strategies:
            try:
                wo_numbers = await strategy(query)
                
                if wo_numbers:
                    all_wo_numbers.update(wo_numbers)
                    # Success! No need to try other strategies
                    break
                else:
                    # Wait before trying next strategy
                    await asyncio.sleep(2.0)
                    
            except Exception as e:
                print(f"      ❌ Strategy failed: {str(e)[:50]}")
                await asyncio.sleep(3.0)
                continue
        
        if all_wo_numbers:
            print(f"   ✅ Total: {len(all_wo_numbers)} WO numbers")
        else:
            print(f"   ⚠️  No WO numbers found after all strategies")
        
        return all_wo_numbers
    
    async def get_br_from_wo(self, wo_number: str) -> Set[str]:
        """
        Get BR numbers from WO patent using CASCADE strategy
        """
        print(f"   🔍 Getting BR numbers for {wo_number}")
        
        urls = [
            f"https://patents.google.com/patent/{wo_number}",
            f"https://patents.google.com/?q={wo_number}",
            f"https://worldwide.espacenet.com/patent/search?q=pn={wo_number}",
            f"https://www.lens.org/lens/search/patent/list?q={wo_number}",
        ]
        
        for url in urls:
            html = await self._fetch_with_retry(url, max_retries=3)
            
            if html:
                br_numbers = self._extract_br_numbers(html)
                
                if br_numbers:
                    print(f"      ✅ {len(br_numbers)} BR patents")
                    return br_numbers
                
                # Wait before next URL
                await asyncio.sleep(1.5)
        
        return set()
    
    def print_stats(self):
        """Print crawler statistics"""
        success_rate = (self.successful_requests / self.total_requests * 100) if self.total_requests > 0 else 0
        
        print(f"\n{'='*70}")
        print(f"📊 CRAWLER STATISTICS")
        print(f"{'='*70}")
        print(f"Total requests: {self.total_requests}")
        print(f"Successful: {self.successful_requests}")
        print(f"Failed: {self.failed_requests}")
        print(f"Success rate: {success_rate:.1f}%")
        print(f"Quarantined proxies: {len(self.quarantined_proxies)}/{len(self.proxies)}")
        print(f"{'='*70}\n")


async def test_ultra_crawler():
    """Test ultra-resilient crawler"""
    print("\n" + "="*70)
    print("TESTING ULTRA-RESILIENT CRAWLER V18")
    print("="*70)
    
    # Mock proxies for testing
    proxies = [
        "http://user:pass@proxy1.com:8080",
        "http://user:pass@proxy2.com:8080",
        "http://user:pass@proxy3.com:8080",
    ]
    
    crawler = UltraResilientCrawler(proxies)
    
    # Test with aspirin
    query = "aspirin patent"
    wo_numbers = await crawler.search_wo_numbers(query)
    
    print(f"\n✅ Found {len(wo_numbers)} WO numbers")
    for wo in sorted(list(wo_numbers))[:5]:
        print(f"   - {wo}")
    
    # Test BR extraction
    if wo_numbers:
        test_wo = list(wo_numbers)[0]
        br_numbers = await crawler.get_br_from_wo(test_wo)
        print(f"\n✅ Found {len(br_numbers)} BR numbers for {test_wo}")
    
    crawler.print_stats()
    
    return len(wo_numbers) > 0


if __name__ == "__main__":
    success = asyncio.run(test_ultra_crawler())
    exit(0 if success else 1)

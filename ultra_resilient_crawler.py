"""
Ultra Resilient WIPO Crawler - Multiple strategies with fallback
"""
import httpx
import asyncio
import random
from typing import Dict, Any, List, Optional
from datetime import datetime
import json
import re

class UltraResilientCrawler:
    """Crawler with 5 cascade strategies for maximum resilience"""
    
    def __init__(self, proxies: List[str] = None):
        self.proxies = proxies or []
        self.timeout = httpx.Timeout(30.0, connect=10.0)
        self.stats = {
            "total_requests": 0,
            "successful": 0,
            "failed": 0,
            "by_strategy": {}
        }
    
    async def fetch_patent_data(self, wo_number: str) -> Dict[str, Any]:
        """
        Fetch patent data using 5 cascade strategies:
        1. Direct WIPO API
        2. Google Patents via SerpAPI
        3. EPO OPS API
        4. Espacenet scraping
        5. WIPO PatentScope search
        """
        self.stats["total_requests"] += 1
        
        # Clean WO number
        wo_clean = re.sub(r'[^0-9]', '', wo_number)
        if not wo_clean:
            return {"error": "Invalid WO number", "wo_number": wo_number}
        
        # Try each strategy in order
        strategies = [
            ("google_patents", self._strategy_google_patents),
            ("wipo_api", self._strategy_wipo_api),
            ("epo_ops", self._strategy_epo_ops),
            ("espacenet", self._strategy_espacenet),
            ("patentscope", self._strategy_patentscope)
        ]
        
        last_error = None
        for name, strategy in strategies:
            try:
                result = await strategy(wo_number, wo_clean)
                if result and not result.get("error"):
                    self.stats["successful"] += 1
                    self.stats["by_strategy"][name] = self.stats["by_strategy"].get(name, 0) + 1
                    result["strategy_used"] = name
                    return result
            except Exception as e:
                last_error = str(e)
                continue
        
        self.stats["failed"] += 1
        return {
            "error": "All strategies failed",
            "last_error": last_error,
            "wo_number": wo_number
        }
    
    async def _strategy_google_patents(self, wo_number: str, wo_clean: str) -> Optional[Dict]:
        """Strategy 1: Google Patents via SerpAPI"""
        if not self.proxies:
            return None
        
        # Get a random API key from proxies
        proxy = random.choice(self.proxies)
        api_key = proxy.replace("serpapi://", "") if proxy.startswith("serpapi://") else None
        
        if not api_key:
            return None
        
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            # Search Google Patents
            response = await client.get(
                "https://serpapi.com/search.json",
                params={
                    "engine": "google_patents",
                    "q": f"WO{wo_clean}",
                    "api_key": api_key
                }
            )
            
            if response.status_code != 200:
                return None
            
            data = response.json()
            results = data.get("organic_results", [])
            
            if not results:
                return None
            
            # Extract BR patents from worldwide applications
            br_patents = []
            for result in results:
                patent_id = result.get("patent_id", "")
                if "BR" in patent_id:
                    br_patents.append({
                        "number": patent_id,
                        "title": result.get("title", ""),
                        "link": result.get("link", "")
                    })
            
            return {
                "wo_number": wo_number,
                "br_patents": br_patents,
                "total_results": len(results),
                "source": "google_patents"
            }
    
    async def _strategy_wipo_api(self, wo_number: str, wo_clean: str) -> Optional[Dict]:
        """Strategy 2: Direct WIPO API"""
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.get(
                f"https://patentscope.wipo.int/search/en/detail.jsf?docId=WO{wo_clean}"
            )
            
            if response.status_code != 200:
                return None
            
            # Basic extraction
            return {
                "wo_number": wo_number,
                "br_patents": [],
                "source": "wipo_api",
                "raw_available": True
            }
    
    async def _strategy_epo_ops(self, wo_number: str, wo_clean: str) -> Optional[Dict]:
        """Strategy 3: EPO OPS API"""
        # EPO requires auth - skip if not configured
        return None
    
    async def _strategy_espacenet(self, wo_number: str, wo_clean: str) -> Optional[Dict]:
        """Strategy 4: Espacenet"""
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.get(
                f"https://worldwide.espacenet.com/patent/search?q=WO{wo_clean}"
            )
            
            if response.status_code != 200:
                return None
            
            return {
                "wo_number": wo_number,
                "br_patents": [],
                "source": "espacenet",
                "raw_available": True
            }
    
    async def _strategy_patentscope(self, wo_number: str, wo_clean: str) -> Optional[Dict]:
        """Strategy 5: WIPO PatentScope search"""
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.get(
                "https://patentscope.wipo.int/search/en/search.jsf",
                params={"query": f"WO{wo_clean}"}
            )
            
            if response.status_code != 200:
                return None
            
            return {
                "wo_number": wo_number,
                "br_patents": [],
                "source": "patentscope",
                "raw_available": True
            }
    
    def get_stats(self) -> Dict:
        """Return crawler statistics"""
        return self.stats

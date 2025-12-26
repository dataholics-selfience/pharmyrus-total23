"""
PHARMYRUS V18 - ULTRA-RESILIENT PRODUCTION API
FastAPI + Ultra-Resilient Crawler + 14 Keys + Quarantine System
"""
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import List, Optional, Dict
import asyncio
import os

from advanced_proxy_manager import AdvancedProxyManager
from key_pool_manager import KeyPoolManager
from ultra_resilient_crawler import UltraResilientCrawler


app = FastAPI(
    title="Pharmyrus V18 Ultra-Resilient",
    description="5-layer cascade patent search with 14 API keys",
    version="18.0.0"
)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Global instances
proxy_manager = None
crawler = None


class SearchRequest(BaseModel):
    nome_molecula: str
    nome_comercial: Optional[str] = None
    dev_codes: Optional[List[str]] = None


class SearchResponse(BaseModel):
    molecule: str
    wo_numbers: List[str]
    br_numbers: List[str]
    summary: Dict


@app.on_event("startup")
async def startup():
    """Initialize system on startup"""
    global proxy_manager, crawler
    
    port = os.environ.get("PORT", 8000)
    
    print("=" * 70)
    print("🚀 PHARMYRUS V18 ULTRA-RESILIENT STARTUP")
    print("=" * 70)
    print(f"📡 PORT: {port}")
    print(f"🌐 Environment: production")
    print("=" * 70)
    
    # Initialize key pool manager
    print("\n🔧 Initializing key pool manager...")
    key_manager = KeyPoolManager()
    
    # Get all proxies from key pool
    all_proxies = key_manager.get_all_proxies()
    
    print(f"✅ Key pool ready: {len(all_proxies)} proxies from {len(key_manager.api_keys)} keys")
    
    # Initialize proxy manager with proxies
    print("\n🔧 Initializing proxy manager...")
    proxy_manager = AdvancedProxyManager()
    proxy_manager.add_proxies(all_proxies)
    
    print(f"✅ Proxy manager ready: {len(all_proxies)} proxies")
    
    # Initialize ultra-resilient crawler
    print("\n🔧 Initializing ULTRA-RESILIENT crawler...")
    print("   - 5 cascade strategies")
    print("   - Automatic quarantine")
    print("   - Multiple retry layers")
    print("   - Exponential backoff")
    
    crawler = UltraResilientCrawler(all_proxies)
    
    print("✅ Crawler ready!")
    
    print("\n" + "=" * 70)
    print("✅ PHARMYRUS V18 READY!")
    print(f"📊 Total proxies: {len(all_proxies)}")
    print(f"📊 Healthy proxies: {len(all_proxies) - len(crawler.quarantined_proxies)}")
    print("=" * 70 + "\n")


@app.get("/")
async def root():
    """Root endpoint"""
    return {
        "service": "Pharmyrus V18 Ultra-Resilient",
        "status": "online",
        "version": "18.0.0",
        "features": [
            "5-layer cascade strategy",
            "14 API keys pool",
            "200+ proxies with quarantine",
            "Exponential backoff retry",
            "Multiple WO/BR extraction patterns",
            "Google Patents + Espacenet + WIPO + Lens.org"
        ]
    }


@app.get("/health")
async def health():
    """Health check"""
    if not crawler or not proxy_manager:
        return {"status": "initializing"}
    
    all_proxies = proxy_manager.get_all_proxies()
    healthy = len(all_proxies) - len(crawler.quarantined_proxies)
    
    return {
        "status": "healthy",
        "total_proxies": len(all_proxies),
        "healthy_proxies": healthy,
        "quarantined_proxies": len(crawler.quarantined_proxies),
        "total_requests": crawler.total_requests,
        "success_rate": f"{(crawler.successful_requests / crawler.total_requests * 100) if crawler.total_requests > 0 else 0:.1f}%"
    }


@app.get("/api/v18/test/{molecule}")
async def test_search(molecule: str):
    """Test endpoint (doesn't consume quota)"""
    return {
        "status": "success",
        "molecule": molecule,
        "test": True,
        "message": "System ready. Use POST /api/search for real searches.",
        "system_info": {
            "version": "18.0.0",
            "total_proxies": len(proxy_manager.get_all_proxies()) if proxy_manager else 0,
            "healthy_proxies": len(proxy_manager.get_all_proxies()) - len(crawler.quarantined_proxies) if crawler else 0,
            "quarantined_proxies": len(crawler.quarantined_proxies) if crawler else 0,
            "strategies": 5
        }
    }


@app.post("/api/search", response_model=SearchResponse)
async def search_molecule(request: SearchRequest):
    """
    Search for WO and BR patent numbers
    
    Uses 5-layer cascade strategy:
    1. Google Patents direct
    2. Google Search + site filter
    3. Espacenet
    4. WIPO Patentscope
    5. Lens.org
    """
    if not crawler:
        raise HTTPException(status_code=503, detail="Crawler not initialized")
    
    print(f"\n{'='*70}")
    print(f"🔬 HIGH-VOLUME SEARCH: {request.nome_molecula}")
    print(f"{'='*70}")
    
    try:
        # Build queries
        queries = [
            f"{request.nome_molecula} patent",
            f"{request.nome_molecula} WO2011",
            f"{request.nome_molecula} WO2016",
            f"{request.nome_molecula} WO2018",
            f"{request.nome_molecula} WO2020",
            f"{request.nome_molecula} WO2021",
            f"{request.nome_molecula} WO2023",
        ]
        
        if request.dev_codes:
            for code in request.dev_codes[:3]:
                queries.append(f"{code} patent WO")
        
        print(f"📊 Executing {len(queries)} queries with CASCADE strategy...")
        
        # Search WO numbers with cascade
        all_wo_numbers = set()
        
        for i, query in enumerate(queries, 1):
            print(f"\n[{i}/{len(queries)}] Query: {query}")
            
            wo_numbers = await crawler.search_wo_numbers(query)
            all_wo_numbers.update(wo_numbers)
            
            # Small delay between queries
            if i < len(queries):
                await asyncio.sleep(1.5)
        
        print(f"\n✅ Total WO numbers found: {len(all_wo_numbers)}")
        
        # Get BR numbers for each WO
        print(f"\n📊 Extracting BR numbers from {len(all_wo_numbers)} WOs...")
        
        all_br_numbers = set()
        
        for wo in sorted(all_wo_numbers):
            br_numbers = await crawler.get_br_from_wo(wo)
            all_br_numbers.update(br_numbers)
            
            # Small delay
            await asyncio.sleep(1.0)
        
        print(f"\n✅ Total BR numbers found: {len(all_br_numbers)}")
        
        # Print final stats
        crawler.print_stats()
        
        return SearchResponse(
            molecule=request.nome_molecula,
            wo_numbers=sorted(list(all_wo_numbers)),
            br_numbers=sorted(list(all_br_numbers)),
            summary={
                "total_wo": len(all_wo_numbers),
                "total_br": len(all_br_numbers),
                "queries_executed": len(queries),
                "parallel_execution": False,
                "cascade_strategy": True
            }
        )
        
    except Exception as e:
        print(f"\n❌ ERROR: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/proxy/status")
async def proxy_status():
    """Get detailed proxy and key pool status"""
    if not crawler or not proxy_manager:
        raise HTTPException(status_code=503, detail="System not initialized")
    
    all_proxies = proxy_manager.get_all_proxies()
    
    # Proxy stats
    proxy_stats = {
        "total_proxies": len(all_proxies),
        "healthy_proxies": len(all_proxies) - len(crawler.quarantined_proxies),
        "quarantined_proxies": len(crawler.quarantined_proxies),
        "total_requests": crawler.total_requests,
        "total_successes": crawler.successful_requests,
        "total_failures": crawler.failed_requests,
        "global_success_rate": crawler.successful_requests / crawler.total_requests if crawler.total_requests > 0 else 0,
    }
    
    # Top performing proxies
    proxy_performance = []
    for proxy in all_proxies[:10]:
        if proxy not in crawler.quarantined_proxies:
            failures = crawler.proxy_failures.get(proxy, 0)
            proxy_performance.append({
                "proxy": proxy[:30] + "...",
                "failures": failures,
                "status": "healthy" if failures < 3 else "at_risk"
            })
    
    # Quarantined list
    quarantined_list = [p[:30] + "..." for p in list(crawler.quarantined_proxies)[:5]]
    
    return {
        **proxy_stats,
        "top_proxies": proxy_performance,
        "quarantined_list": quarantined_list
    }


if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)

"""
Pharmyrus V18 - Ultra Resilient Patent Search API
FIXED: KeyPoolManager.get_all_proxies() method added
"""
from fastapi import FastAPI, Query, HTTPException
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from typing import Optional, Dict, Any, List
import asyncio
import httpx
import os
import logging
import re
from datetime import datetime

# Local imports
from key_pool_manager import KeyPoolManager
from advanced_proxy_manager import AdvancedProxyManager
from ultra_resilient_crawler import UltraResilientCrawler

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(
    title="Pharmyrus V18 API",
    description="Ultra Resilient Brazilian Patent Search",
    version="18.0.1-FIXED"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Global instances
key_manager: Optional[KeyPoolManager] = None
proxy_manager: Optional[AdvancedProxyManager] = None
crawler: Optional[UltraResilientCrawler] = None


@app.on_event("startup")
async def startup():
    """Initialize system on startup"""
    global key_manager, proxy_manager, crawler
    
    port = os.environ.get("PORT", 8000)
    
    print("=" * 70)
    print("🚀 PHARMYRUS V18 ULTRA-RESILIENT STARTUP")
    print("=" * 70)
    print(f"📡 PORT: {port}")
    print(f"🌐 Environment: production")
    print("=" * 70)
    
    # 1. Initialize key pool manager
    print("\n🔧 Initializing key pool manager...")
    key_manager = KeyPoolManager()
    print(f"   ✅ {len(key_manager.api_keys)} API keys loaded")
    
    # 2. Get all proxies from key pool
    print("\n🔧 Getting proxies from key pool...")
    all_proxies = key_manager.get_all_proxies()
    print(f"   ✅ {len(all_proxies)} proxies generated")
    
    # 3. Initialize proxy manager
    print("\n🔧 Initializing proxy manager...")
    proxy_manager = AdvancedProxyManager()
    proxy_manager.add_proxies(all_proxies)
    print(f"   ✅ Proxy manager ready with {len(proxy_manager.proxies)} proxies")
    
    # 4. Initialize ultra-resilient crawler
    print("\n🔧 Initializing ULTRA-RESILIENT crawler...")
    crawler = UltraResilientCrawler(all_proxies)
    print("   ✅ Crawler ready with 5 cascade strategies")
    
    print("\n" + "=" * 70)
    print("✅ PHARMYRUS V18 READY!")
    print("=" * 70 + "\n")


@app.get("/")
async def root():
    """Root endpoint"""
    return {
        "service": "Pharmyrus V18",
        "version": "18.0.1-FIXED",
        "status": "running",
        "endpoints": [
            "/health",
            "/api/v1/search",
            "/api/v1/wo/{wo_number}",
            "/stats"
        ]
    }


@app.get("/health")
async def health():
    """Health check endpoint"""
    return {
        "status": "healthy",
        "version": "18.0.1-FIXED",
        "key_pool": key_manager.status() if key_manager else None,
        "proxy_pool": proxy_manager.status() if proxy_manager else None,
        "crawler_stats": crawler.get_stats() if crawler else None
    }


@app.get("/stats")
async def stats():
    """Detailed statistics"""
    return {
        "keys": key_manager.status() if key_manager else {},
        "proxies": proxy_manager.status() if proxy_manager else {},
        "crawler": crawler.get_stats() if crawler else {}
    }


@app.get("/api/v1/search")
async def search_patents(
    molecule_name: str = Query(..., description="Nome da molécula"),
    include_inpi: bool = Query(True, description="Incluir busca INPI")
):
    """
    Search for Brazilian patents by molecule name
    """
    if not crawler:
        raise HTTPException(status_code=503, detail="Service not initialized")
    
    results = {
        "molecule": molecule_name,
        "timestamp": datetime.now().isoformat(),
        "br_patents": [],
        "sources": []
    }
    
    # Search INPI if enabled
    if include_inpi:
        try:
            async with httpx.AsyncClient(timeout=60.0) as client:
                response = await client.get(
                    "https://crawler3-production.up.railway.app/api/data/inpi/patents",
                    params={"medicine": molecule_name}
                )
                if response.status_code == 200:
                    inpi_data = response.json()
                    if inpi_data.get("data"):
                        for patent in inpi_data["data"]:
                            results["br_patents"].append({
                                "number": patent.get("title", ""),
                                "applicant": patent.get("applicant", ""),
                                "deposit_date": patent.get("depositDate", ""),
                                "source": "inpi"
                            })
                        results["sources"].append("inpi")
        except Exception as e:
            logger.error(f"INPI search failed: {e}")
    
    results["total_found"] = len(results["br_patents"])
    return results


@app.get("/api/v1/wo/{wo_number}")
async def get_wo_patent(wo_number: str):
    """
    Get patent details by WO number
    """
    if not crawler:
        raise HTTPException(status_code=503, detail="Service not initialized")
    
    result = await crawler.fetch_patent_data(wo_number)
    return result


if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)

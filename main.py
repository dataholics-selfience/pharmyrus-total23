"""
Pharmyrus V19 - Complete Patent Search System
Objetivo: Igualar ou superar Cortellis na busca de patentes BR

Fluxo:
1. PubChem → dev codes, CAS, sinônimos
2. Google Patents Search → encontrar WOs
3. Para cada WO → extrair BRs via worldwide_applications
4. INPI direto → busca por nome PT/EN e dev codes
5. Deduplicação e classificação
"""
from fastapi import FastAPI, Query, HTTPException
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from typing import Optional, Dict, Any, List, Set
import asyncio
import httpx
import os
import logging
import re
from datetime import datetime
from dataclasses import dataclass, field, asdict

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(
    title="Pharmyrus V19 - Complete Patent Search",
    description="Sistema completo de busca de patentes BR - Objetivo: superar Cortellis",
    version="19.0.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ============================================================
# API KEYS POOL
# ============================================================
API_KEYS = [
    "bc20bca64032a7ac59abf330bbdeca80aa79cd72bb208059056b10fb6e33e4bc",
    "3f22448f4d43ce8259fa2f7f6385222323a67c4ce4e72fcc774b43d23812889d",
    "69a4de2daad0e74c7d12c81d2c22d9715b7483e4f24cfc38c9aca4e65ef8dc8a",
    "ae35c24af9c0e26a578534082299e39f49d9a7f54ed987bb4be1dc369b41e16c",
    "e3e629ecd3f9f8bf9cda26db2cd0e5d330c5169ca91c68d37cb3a7c66e42e3e8",
    "19e60235f3cf6e5ac2daf95c16ca15e7a7d79a42e28828a930e11a09df967ea8",
    "a07ed78001b5dc00ffd21a39a73e98dbc13f8e57ce5a8e45cf34878f81c37ecf",
    "30d4e6f5bcc0fac460c704fb505ca4e8dd65c09b88b8dc5c06dcc7be8a8eb4c2",
]

key_index = 0
def get_api_key() -> str:
    global key_index
    key = API_KEYS[key_index % len(API_KEYS)]
    key_index += 1
    return key

# ============================================================
# DATA CLASSES
# ============================================================
@dataclass
class BRPatent:
    number: str
    wo_primary: str = ""
    title: str = ""
    patent_type: str = ""
    holder: str = ""
    filing_date: str = ""
    expiry_date: str = ""
    source: str = ""
    
    def to_dict(self):
        return asdict(self)

@dataclass 
class SearchResult:
    molecule: str
    timestamp: str
    pubchem_data: Dict = field(default_factory=dict)
    wo_numbers: List[str] = field(default_factory=list)
    br_patents: List[Dict] = field(default_factory=list)
    sources_used: List[str] = field(default_factory=list)
    search_stats: Dict = field(default_factory=dict)
    cortellis_comparison: Dict = field(default_factory=dict)

# ============================================================
# STEP 1: PUBCHEM - Obter dev codes, CAS, sinônimos
# ============================================================
async def get_pubchem_data(molecule: str, client: httpx.AsyncClient) -> Dict:
    """Busca dados do PubChem: dev codes, CAS, sinônimos"""
    result = {
        "dev_codes": [],
        "cas": None,
        "synonyms": [],
        "iupac": None
    }
    
    try:
        # Buscar sinônimos
        url = f"https://pubchem.ncbi.nlm.nih.gov/rest/pug/compound/name/{molecule}/synonyms/JSON"
        response = await client.get(url, timeout=30.0)
        
        if response.status_code == 200:
            data = response.json()
            synonyms = data.get("InformationList", {}).get("Information", [{}])[0].get("Synonym", [])
            
            # Padrões
            dev_pattern = re.compile(r'^[A-Z]{2,5}[-\s]?\d{3,7}[A-Z]?$', re.IGNORECASE)
            cas_pattern = re.compile(r'^\d{2,7}-\d{2}-\d$')
            
            for syn in synonyms[:100]:  # Limitar a 100
                if cas_pattern.match(syn) and not result["cas"]:
                    result["cas"] = syn
                elif dev_pattern.match(syn) and len(result["dev_codes"]) < 15:
                    result["dev_codes"].append(syn)
                elif len(result["synonyms"]) < 20:
                    result["synonyms"].append(syn)
            
            logger.info(f"PubChem: {len(result['dev_codes'])} dev codes, CAS={result['cas']}")
    
    except Exception as e:
        logger.error(f"PubChem error: {e}")
    
    return result

# ============================================================
# STEP 2: BUSCAR WO NUMBERS - Múltiplas estratégias
# ============================================================
async def search_wo_numbers(molecule: str, dev_codes: List[str], client: httpx.AsyncClient) -> List[str]:
    """Busca WO numbers usando múltiplas queries"""
    wo_numbers: Set[str] = set()
    wo_pattern = re.compile(r'WO[-\s]?(\d{4})[-/\s]?(\d{5,6})', re.IGNORECASE)
    
    # Queries para buscar WOs
    queries = [
        f"{molecule} patent WO",
        f"{molecule} pharmaceutical patent",
        f'"{molecule}" WO patent',
    ]
    
    # Adicionar queries com dev codes
    for dev in dev_codes[:3]:
        queries.append(f"{dev} patent WO")
    
    # Adicionar queries por ano
    for year in ["2011", "2016", "2018", "2019", "2020", "2021", "2022", "2023"]:
        queries.append(f"{molecule} patent WO{year}")
    
    for query in queries:
        try:
            api_key = get_api_key()
            response = await client.get(
                "https://serpapi.com/search.json",
                params={
                    "engine": "google",
                    "q": query,
                    "api_key": api_key,
                    "num": 10
                },
                timeout=30.0
            )
            
            if response.status_code == 200:
                data = response.json()
                for result in data.get("organic_results", []):
                    text = f"{result.get('title', '')} {result.get('snippet', '')} {result.get('link', '')}"
                    matches = wo_pattern.findall(text)
                    for match in matches:
                        wo = f"WO{match[0]}{match[1]}"
                        wo_numbers.add(wo)
            
            await asyncio.sleep(0.3)  # Rate limiting
            
        except Exception as e:
            logger.error(f"WO search error for '{query}': {e}")
    
    # Busca também no Google Patents diretamente
    try:
        api_key = get_api_key()
        response = await client.get(
            "https://serpapi.com/search.json",
            params={
                "engine": "google_patents",
                "q": molecule,
                "api_key": api_key,
                "num": 20
            },
            timeout=30.0
        )
        
        if response.status_code == 200:
            data = response.json()
            for result in data.get("organic_results", []):
                patent_id = result.get("patent_id", "")
                if patent_id.startswith("WO"):
                    wo_numbers.add(patent_id.replace("-", ""))
                    
    except Exception as e:
        logger.error(f"Google Patents search error: {e}")
    
    logger.info(f"Found {len(wo_numbers)} unique WO numbers")
    return list(wo_numbers)

# ============================================================
# STEP 3: EXTRAIR BRs DE CADA WO
# ============================================================
async def extract_br_from_wo(wo_number: str, client: httpx.AsyncClient) -> List[Dict]:
    """Extrai patentes BR de um WO number via Google Patents"""
    br_patents = []
    
    try:
        api_key = get_api_key()
        
        # Primeiro, buscar o patent
        response = await client.get(
            "https://serpapi.com/search.json",
            params={
                "engine": "google_patents",
                "q": wo_number,
                "api_key": api_key
            },
            timeout=30.0
        )
        
        if response.status_code != 200:
            return br_patents
        
        data = response.json()
        results = data.get("organic_results", [])
        
        if not results:
            return br_patents
        
        # Pegar o serpapi_link do primeiro resultado
        serpapi_link = results[0].get("serpapi_link")
        if not serpapi_link:
            return br_patents
        
        # Buscar detalhes
        await asyncio.sleep(0.3)
        detail_response = await client.get(
            f"{serpapi_link}&api_key={api_key}",
            timeout=30.0
        )
        
        if detail_response.status_code != 200:
            return br_patents
        
        detail_data = detail_response.json()
        
        # Extrair worldwide_applications
        worldwide = detail_data.get("worldwide_applications", {})
        
        for year, apps in worldwide.items():
            if isinstance(apps, list):
                for app in apps:
                    # Verificar country_code OU document_id começando com BR
                    country = app.get("country_code", "")
                    doc_id = app.get("document_id", "")
                    
                    if country == "BR" or doc_id.startswith("BR"):
                        br_patents.append({
                            "number": doc_id,
                            "wo_primary": wo_number,
                            "title": app.get("title", ""),
                            "filing_date": app.get("filing_date", ""),
                            "source": "google_patents_worldwide"
                        })
                        logger.info(f"  Found BR: {doc_id} from {wo_number}")
        
    except Exception as e:
        logger.error(f"Error extracting BR from {wo_number}: {e}")
    
    return br_patents

# ============================================================
# STEP 4: BUSCA INPI DIRETA
# ============================================================
async def search_inpi(terms: List[str], client: httpx.AsyncClient) -> List[Dict]:
    """Busca direta no INPI usando múltiplos termos"""
    br_patents = []
    seen_numbers = set()
    
    for term in terms:
        if not term:
            continue
            
        try:
            response = await client.get(
                "https://crawler3-production.up.railway.app/api/data/inpi/patents",
                params={"medicine": term},
                timeout=60.0
            )
            
            if response.status_code == 200:
                data = response.json()
                for patent in data.get("data", []):
                    title = patent.get("title", "")
                    if title.startswith("BR") and title not in seen_numbers:
                        seen_numbers.add(title)
                        br_patents.append({
                            "number": title.replace(" ", "-"),
                            "wo_primary": "",
                            "title": patent.get("applicant", ""),
                            "filing_date": patent.get("depositDate", ""),
                            "holder": patent.get("applicant", ""),
                            "source": "inpi_direct"
                        })
                        logger.info(f"  INPI found: {title} for term '{term}'")
            
            await asyncio.sleep(0.5)  # Rate limiting INPI
            
        except Exception as e:
            logger.error(f"INPI search error for '{term}': {e}")
    
    return br_patents

# ============================================================
# STEP 5: DEDUPLICAÇÃO E CLASSIFICAÇÃO
# ============================================================
def deduplicate_patents(patents: List[Dict]) -> List[Dict]:
    """Remove duplicatas baseado no número da patente"""
    seen = {}
    
    for p in patents:
        # Normalizar número
        num = p.get("number", "").upper().replace(" ", "-").replace("/", "-")
        num = re.sub(r'[^A-Z0-9-]', '', num)
        
        if not num:
            continue
        
        # Manter o mais completo
        if num not in seen:
            seen[num] = p
        else:
            # Merge info
            existing = seen[num]
            for key in ["wo_primary", "title", "holder", "filing_date"]:
                if not existing.get(key) and p.get(key):
                    existing[key] = p[key]
    
    return list(seen.values())

def classify_patent(patent: Dict) -> str:
    """Classifica o tipo de patente baseado no título"""
    title = (patent.get("title", "") or "").lower()
    
    if any(w in title for w in ["cristalina", "crystalline", "polymorph"]):
        return "CRYSTALLINE"
    elif any(w in title for w in ["processo", "process", "synthesis", "preparation"]):
        return "PROCESS"
    elif any(w in title for w in ["formulação", "formulation", "composition"]):
        return "FORMULATION"
    elif any(w in title for w in ["uso", "use", "treatment", "method"]):
        return "MEDICAL_USE"
    elif any(w in title for w in ["sal", "salt"]):
        return "SALT"
    elif any(w in title for w in ["combinação", "combination"]):
        return "COMBINATION"
    else:
        return "OTHER"

# ============================================================
# MAIN SEARCH ENDPOINT
# ============================================================
@app.get("/api/v1/search/complete")
async def complete_search(
    molecule_name: str = Query(..., description="Nome da molécula"),
    molecule_name_pt: Optional[str] = Query(None, description="Nome em português"),
    expected_br_count: int = Query(8, description="Número esperado de BRs (Cortellis)")
):
    """
    Busca COMPLETA de patentes BR - objetivo: igualar/superar Cortellis
    
    Estratégia:
    1. PubChem → dev codes, CAS, sinônimos
    2. Google + Google Patents → encontrar WOs
    3. Para cada WO → extrair BRs via worldwide_applications  
    4. INPI direto → busca por nome PT/EN e dev codes
    5. Deduplicação e classificação
    """
    start_time = datetime.now()
    
    async with httpx.AsyncClient() as client:
        # STEP 1: PubChem
        logger.info(f"=== STEP 1: PubChem for {molecule_name} ===")
        pubchem_data = await get_pubchem_data(molecule_name, client)
        
        # STEP 2: Buscar WO numbers
        logger.info(f"=== STEP 2: Searching WO numbers ===")
        wo_numbers = await search_wo_numbers(
            molecule_name, 
            pubchem_data["dev_codes"], 
            client
        )
        
        # STEP 3: Extrair BRs de cada WO
        logger.info(f"=== STEP 3: Extracting BR patents from {len(wo_numbers)} WOs ===")
        all_br_patents = []
        
        for wo in wo_numbers[:20]:  # Limitar a 20 WOs
            br_patents = await extract_br_from_wo(wo, client)
            all_br_patents.extend(br_patents)
            await asyncio.sleep(0.3)
        
        # STEP 4: INPI Direto
        logger.info(f"=== STEP 4: Direct INPI search ===")
        inpi_terms = [molecule_name]
        if molecule_name_pt:
            inpi_terms.append(molecule_name_pt)
        inpi_terms.extend(pubchem_data["dev_codes"][:5])
        
        inpi_patents = await search_inpi(inpi_terms, client)
        all_br_patents.extend(inpi_patents)
        
        # STEP 5: Deduplicação
        logger.info(f"=== STEP 5: Deduplication ===")
        unique_patents = deduplicate_patents(all_br_patents)
        
        # Classificar
        for p in unique_patents:
            p["patent_type"] = classify_patent(p)
        
        # Ordenar por número
        unique_patents.sort(key=lambda x: x.get("number", ""))
        
        elapsed = (datetime.now() - start_time).total_seconds()
        
        # Resultado
        result = {
            "molecule": molecule_name,
            "molecule_pt": molecule_name_pt,
            "timestamp": datetime.now().isoformat(),
            "elapsed_seconds": elapsed,
            "pubchem_data": {
                "dev_codes": pubchem_data["dev_codes"],
                "cas": pubchem_data["cas"],
                "synonyms_count": len(pubchem_data["synonyms"])
            },
            "search_stats": {
                "wo_numbers_found": len(wo_numbers),
                "wo_numbers": wo_numbers[:20],
                "inpi_terms_searched": inpi_terms,
                "raw_br_count": len(all_br_patents),
                "unique_br_count": len(unique_patents)
            },
            "cortellis_comparison": {
                "expected": expected_br_count,
                "found": len(unique_patents),
                "match_rate": f"{min(len(unique_patents) / max(expected_br_count, 1) * 100, 100):.1f}%",
                "status": "✅ EXCELLENT" if len(unique_patents) >= expected_br_count else 
                         "🟡 GOOD" if len(unique_patents) >= expected_br_count * 0.75 else
                         "🔴 NEEDS IMPROVEMENT"
            },
            "br_patents": unique_patents
        }
        
        logger.info(f"=== COMPLETE: Found {len(unique_patents)} unique BR patents in {elapsed:.1f}s ===")
        
        return result

# ============================================================
# OTHER ENDPOINTS
# ============================================================
@app.get("/")
async def root():
    return {
        "service": "Pharmyrus V19 - Complete Patent Search",
        "version": "19.0.0",
        "objective": "Match or exceed Cortellis BR patent coverage",
        "endpoints": {
            "complete_search": "/api/v1/search/complete?molecule_name=darolutamide&molecule_name_pt=darolutamida&expected_br_count=8",
            "health": "/health"
        }
    }

@app.get("/health")
async def health():
    return {
        "status": "healthy",
        "version": "19.0.0",
        "api_keys_available": len(API_KEYS)
    }

if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)

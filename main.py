"""
Pharmyrus V20 - Complete Patent Search
SEM SerpAPI - Usa EPO OPS + Crawlers Stealth + INPI

Estratégia:
1. PubChem → dev codes, CAS, sinônimos (API pública)
2. EPO OPS API → busca por nome/dev codes → encontra famílias de patentes
3. Google Patents Scraping → extrai WOs e BRs
4. INPI crawler → busca direta múltiplos termos
5. Deduplicação e classificação
"""
from fastapi import FastAPI, Query, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from typing import Optional, Dict, Any, List, Set
import asyncio
import httpx
import os
import logging
import re
import base64
from datetime import datetime, timedelta
import xml.etree.ElementTree as ET

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(
    title="Pharmyrus V20 - EPO + Stealth Crawlers",
    description="Sistema completo usando EPO OPS + Crawlers Stealth + INPI",
    version="20.0.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ============================================================
# EPO OPS API CREDENTIALS
# ============================================================
EPO_KEY = "G5wJypxeg0GXEJoMGP37tdK370aKxeMszGKAkD6QaR0yiR5X"
EPO_SECRET = "zg5AJ0EDzXdJey3GaFNM8ztMVxHKXRrAihXH93iS5ZAzKPAPMFLuVUfiEuAqpdbz"

# Token cache
_epo_token = None
_epo_token_expires = None

# ============================================================
# EPO TOKEN MANAGEMENT
# ============================================================
async def get_epo_token(client: httpx.AsyncClient) -> Optional[str]:
    """Obtém token de acesso da EPO OPS API"""
    global _epo_token, _epo_token_expires
    
    now = datetime.now()
    if _epo_token and _epo_token_expires and now < _epo_token_expires:
        return _epo_token
    
    try:
        creds = f"{EPO_KEY}:{EPO_SECRET}"
        b64_creds = base64.b64encode(creds.encode()).decode()
        
        response = await client.post(
            "https://ops.epo.org/3.2/auth/accesstoken",
            headers={
                "Authorization": f"Basic {b64_creds}",
                "Content-Type": "application/x-www-form-urlencoded"
            },
            data={"grant_type": "client_credentials"},
            timeout=30.0
        )
        
        if response.status_code == 200:
            data = response.json()
            _epo_token = data.get("access_token")
            expires_in = int(data.get("expires_in", 1200))
            _epo_token_expires = now + timedelta(seconds=expires_in - 60)
            logger.info("EPO token obtained successfully")
            return _epo_token
        else:
            logger.error(f"EPO token error: {response.status_code}")
            return None
            
    except Exception as e:
        logger.error(f"EPO token exception: {e}")
        return None

# ============================================================
# STEP 1: PUBCHEM
# ============================================================
async def get_pubchem_data(molecule: str, client: httpx.AsyncClient) -> Dict:
    """Busca dados do PubChem: dev codes, CAS, sinônimos"""
    result = {
        "dev_codes": [],
        "cas": None,
        "synonyms": [],
        "cid": None
    }
    
    try:
        url = f"https://pubchem.ncbi.nlm.nih.gov/rest/pug/compound/name/{molecule}/synonyms/JSON"
        response = await client.get(url, timeout=30.0)
        
        if response.status_code == 200:
            data = response.json()
            info = data.get("InformationList", {}).get("Information", [{}])[0]
            result["cid"] = info.get("CID")
            synonyms = info.get("Synonym", [])
            
            dev_pattern = re.compile(r'^[A-Z]{2,5}[-\s]?\d{3,7}[A-Z]?$', re.IGNORECASE)
            cas_pattern = re.compile(r'^\d{2,7}-\d{2}-\d$')
            
            for syn in synonyms[:100]:
                if cas_pattern.match(syn) and not result["cas"]:
                    result["cas"] = syn
                elif dev_pattern.match(syn) and len(result["dev_codes"]) < 15:
                    if syn not in result["dev_codes"]:
                        result["dev_codes"].append(syn)
                elif len(result["synonyms"]) < 30 and len(syn) > 3:
                    result["synonyms"].append(syn)
            
            logger.info(f"PubChem: CID={result['cid']}, {len(result['dev_codes'])} dev codes, CAS={result['cas']}")
    
    except Exception as e:
        logger.error(f"PubChem error: {e}")
    
    return result

# ============================================================
# STEP 2: EPO OPS API - Buscar patentes por nome/dev codes
# ============================================================
async def search_epo(query: str, token: str, client: httpx.AsyncClient) -> List[Dict]:
    """Busca patentes na EPO OPS API"""
    patents = []
    
    try:
        # EPO search endpoint
        url = f"https://ops.epo.org/3.2/rest-services/published-data/search"
        
        response = await client.get(
            url,
            params={"q": query, "Range": "1-100"},
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/json"
            },
            timeout=30.0
        )
        
        if response.status_code == 200:
            data = response.json()
            
            # Parse EPO response
            search_result = data.get("ops:world-patent-data", {}).get("ops:biblio-search", {})
            total = search_result.get("@total-result-count", 0)
            logger.info(f"EPO search '{query[:30]}...': {total} results")
            
            pub_refs = search_result.get("ops:search-result", {}).get("ops:publication-reference", [])
            if not isinstance(pub_refs, list):
                pub_refs = [pub_refs] if pub_refs else []
            
            for ref in pub_refs[:50]:
                doc_id = ref.get("document-id", {})
                if isinstance(doc_id, list):
                    doc_id = doc_id[0] if doc_id else {}
                
                country = doc_id.get("country", {}).get("$", "")
                doc_number = doc_id.get("doc-number", {}).get("$", "")
                kind = doc_id.get("kind", {}).get("$", "")
                
                if country and doc_number:
                    patents.append({
                        "country": country,
                        "number": f"{country}{doc_number}",
                        "kind": kind,
                        "full_number": f"{country}-{doc_number}-{kind}" if kind else f"{country}-{doc_number}"
                    })
        
        elif response.status_code == 404:
            logger.info(f"EPO search '{query[:30]}...': no results")
        else:
            logger.warning(f"EPO search error: {response.status_code}")
            
    except Exception as e:
        logger.error(f"EPO search exception: {e}")
    
    return patents

async def get_epo_family(patent_number: str, token: str, client: httpx.AsyncClient) -> List[Dict]:
    """Busca família de patentes (incluindo BR) para um patent number"""
    family_members = []
    
    try:
        # Clean patent number
        clean_num = re.sub(r'[^A-Z0-9]', '', patent_number.upper())
        
        # Family endpoint
        url = f"https://ops.epo.org/3.2/rest-services/family/publication/docdb/{clean_num}/biblio"
        
        response = await client.get(
            url,
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/json"
            },
            timeout=30.0
        )
        
        if response.status_code == 200:
            data = response.json()
            
            # Parse family members
            patent_family = data.get("ops:world-patent-data", {}).get("ops:patent-family", {})
            family_members_raw = patent_family.get("ops:family-member", [])
            
            if not isinstance(family_members_raw, list):
                family_members_raw = [family_members_raw] if family_members_raw else []
            
            for member in family_members_raw:
                pub_ref = member.get("publication-reference", {})
                doc_id = pub_ref.get("document-id", {})
                
                if isinstance(doc_id, list):
                    doc_id = doc_id[0] if doc_id else {}
                
                country = doc_id.get("country", {}).get("$", "")
                doc_number = doc_id.get("doc-number", {}).get("$", "")
                kind = doc_id.get("kind", {}).get("$", "")
                
                if country and doc_number:
                    family_members.append({
                        "country": country,
                        "number": f"{country}{doc_number}",
                        "kind": kind,
                        "full_number": f"{country}-{doc_number}"
                    })
                    
    except Exception as e:
        logger.error(f"EPO family error for {patent_number}: {e}")
    
    return family_members

# ============================================================
# STEP 3: GOOGLE PATENTS SCRAPING (Stealth)
# ============================================================
async def scrape_google_patents(query: str, client: httpx.AsyncClient) -> List[Dict]:
    """Scraping stealth do Google Patents"""
    patents = []
    
    try:
        # Headers stealth
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.5",
            "Accept-Encoding": "gzip, deflate, br",
            "Connection": "keep-alive",
            "Upgrade-Insecure-Requests": "1",
        }
        
        # URL do Google Patents
        url = f"https://patents.google.com/?q={query}&oq={query}"
        
        response = await client.get(url, headers=headers, timeout=30.0, follow_redirects=True)
        
        if response.status_code == 200:
            html = response.text
            
            # Extrair patent IDs do HTML
            # Padrão: /patent/WO2016162604 ou /patent/BR112017021636
            patent_pattern = re.compile(r'/patent/([A-Z]{2}\d+[A-Z]?\d*)', re.IGNORECASE)
            matches = patent_pattern.findall(html)
            
            seen = set()
            for match in matches:
                if match not in seen:
                    seen.add(match)
                    country = match[:2]
                    patents.append({
                        "country": country,
                        "number": match,
                        "source": "google_patents_scrape"
                    })
            
            logger.info(f"Google Patents scrape '{query[:20]}...': {len(patents)} patents")
            
    except Exception as e:
        logger.error(f"Google Patents scrape error: {e}")
    
    return patents

async def get_google_patent_family(patent_id: str, client: httpx.AsyncClient) -> List[Dict]:
    """Busca família de patentes no Google Patents"""
    family = []
    
    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        }
        
        url = f"https://patents.google.com/patent/{patent_id}"
        response = await client.get(url, headers=headers, timeout=30.0, follow_redirects=True)
        
        if response.status_code == 200:
            html = response.text
            
            # Procurar seção "Also published as" ou "Patent family"
            # Padrão BR no HTML
            br_pattern = re.compile(r'BR[-\s]?(\d{9,15}|\d{6,8})', re.IGNORECASE)
            matches = br_pattern.findall(html)
            
            for match in matches:
                br_num = f"BR{match}".replace(" ", "").replace("-", "")
                family.append({
                    "country": "BR",
                    "number": br_num,
                    "source": "google_patents_family"
                })
            
            # Também procurar padrões mais específicos
            br_full_pattern = re.compile(r'BR[-\s]?1[12][-\s]?\d{4}[-\s]?\d{6}[-\s]?\d', re.IGNORECASE)
            full_matches = br_full_pattern.findall(html)
            
            for match in full_matches:
                clean = re.sub(r'[^A-Z0-9]', '', match.upper())
                if clean not in [f["number"] for f in family]:
                    family.append({
                        "country": "BR",
                        "number": clean,
                        "source": "google_patents_family"
                    })
                    
    except Exception as e:
        logger.error(f"Google Patents family error: {e}")
    
    return family

# ============================================================
# STEP 4: INPI CRAWLER
# ============================================================
async def search_inpi(terms: List[str], client: httpx.AsyncClient) -> List[Dict]:
    """Busca direta no INPI usando múltiplos termos"""
    br_patents = []
    seen_numbers = set()
    
    for term in terms:
        if not term or len(term) < 3:
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
                        
                        # Normalizar número
                        clean_num = re.sub(r'\s+', '-', title)
                        
                        br_patents.append({
                            "number": clean_num,
                            "title": patent.get("applicant", ""),
                            "filing_date": patent.get("depositDate", ""),
                            "holder": patent.get("applicant", ""),
                            "full_text": patent.get("fullText", ""),
                            "source": "inpi_direct"
                        })
                        logger.info(f"INPI found: {clean_num} for '{term}'")
            
            await asyncio.sleep(1.0)  # Rate limiting INPI
            
        except Exception as e:
            logger.error(f"INPI error for '{term}': {e}")
    
    return br_patents

# ============================================================
# STEP 5: ESPACENET SCRAPING
# ============================================================
async def search_espacenet(query: str, client: httpx.AsyncClient) -> List[Dict]:
    """Busca no Espacenet (fallback)"""
    patents = []
    
    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Accept": "application/json",
        }
        
        # Espacenet API endpoint
        url = "https://worldwide.espacenet.com/3.2/rest-services/search"
        
        response = await client.get(
            url,
            params={"q": query, "ql": "cql"},
            headers=headers,
            timeout=30.0
        )
        
        if response.status_code == 200:
            # Parse response
            data = response.json() if response.headers.get("content-type", "").startswith("application/json") else {}
            logger.info(f"Espacenet search: {len(data)} results")
            
    except Exception as e:
        logger.error(f"Espacenet error: {e}")
    
    return patents

# ============================================================
# DEDUPLICATION & CLASSIFICATION
# ============================================================
def normalize_br_number(number: str) -> str:
    """Normaliza número de patente BR"""
    # Remove espaços e caracteres especiais
    clean = re.sub(r'[^A-Z0-9]', '', number.upper())
    
    # Formatar como BR-XXXXXXXXXX-X
    if clean.startswith("BR") and len(clean) > 2:
        rest = clean[2:]
        # Tentar formatar como BR 11 2024 016586 8
        if len(rest) >= 13:
            return f"BR-{rest[:2]}-{rest[2:6]}-{rest[6:12]}-{rest[12:]}"
        elif len(rest) >= 7:
            return f"BR-{rest}"
    
    return number

def deduplicate_patents(patents: List[Dict]) -> List[Dict]:
    """Remove duplicatas"""
    seen = {}
    
    for p in patents:
        num = p.get("number", "").upper()
        num_clean = re.sub(r'[^A-Z0-9]', '', num)
        
        if not num_clean or len(num_clean) < 5:
            continue
        
        if num_clean not in seen:
            seen[num_clean] = p.copy()
            seen[num_clean]["number_normalized"] = normalize_br_number(num)
        else:
            # Merge info
            for key in ["title", "holder", "filing_date", "wo_primary"]:
                if not seen[num_clean].get(key) and p.get(key):
                    seen[num_clean][key] = p[key]
            # Add sources
            existing_source = seen[num_clean].get("source", "")
            new_source = p.get("source", "")
            if new_source and new_source not in existing_source:
                seen[num_clean]["source"] = f"{existing_source},{new_source}" if existing_source else new_source
    
    return list(seen.values())

def classify_patent(patent: Dict) -> str:
    """Classifica tipo de patente"""
    text = (patent.get("title", "") + " " + patent.get("full_text", "")).lower()
    
    if any(w in text for w in ["cristalina", "crystalline", "polymorph", "crystal form"]):
        return "CRYSTALLINE"
    elif any(w in text for w in ["processo", "process", "synthesis", "preparation", "method of making"]):
        return "PROCESS"
    elif any(w in text for w in ["formulação", "formulation", "composition", "dosage"]):
        return "FORMULATION"
    elif any(w in text for w in ["uso", "use", "treatment", "method of treatment", "therapy"]):
        return "MEDICAL_USE"
    elif any(w in text for w in ["sal ", "salt", "salts"]):
        return "SALT"
    elif any(w in text for w in ["combinação", "combination"]):
        return "COMBINATION"
    elif any(w in text for w in ["intermediário", "intermediate"]):
        return "INTERMEDIATE"
    else:
        return "OTHER"

# ============================================================
# MAIN SEARCH ENDPOINT
# ============================================================
@app.get("/api/v1/search/complete")
async def complete_search(
    molecule_name: str = Query(..., description="Nome da molécula (inglês)"),
    molecule_name_pt: Optional[str] = Query(None, description="Nome em português"),
    expected_br_count: int = Query(8, description="Número esperado de BRs (Cortellis benchmark)")
):
    """
    Busca COMPLETA de patentes BR
    
    Estratégia multi-fonte:
    1. PubChem → dev codes, CAS
    2. EPO OPS → busca + famílias de patentes
    3. Google Patents Scraping → WOs e BRs
    4. INPI Crawler → busca direta
    """
    start_time = datetime.now()
    all_br_patents = []
    all_wo_numbers = set()
    sources_used = []
    
    async with httpx.AsyncClient() as client:
        # ========== STEP 1: PUBCHEM ==========
        logger.info(f"=== STEP 1: PubChem for {molecule_name} ===")
        pubchem_data = await get_pubchem_data(molecule_name, client)
        sources_used.append("pubchem")
        
        # ========== STEP 2: EPO OPS ==========
        logger.info(f"=== STEP 2: EPO OPS API ===")
        epo_token = await get_epo_token(client)
        
        if epo_token:
            sources_used.append("epo_ops")
            
            # Buscar por nome da molécula
            search_terms = [molecule_name]
            if molecule_name_pt:
                search_terms.append(molecule_name_pt)
            search_terms.extend(pubchem_data["dev_codes"][:5])
            
            epo_patents = []
            for term in search_terms[:8]:
                results = await search_epo(f'txt="{term}"', epo_token, client)
                epo_patents.extend(results)
                await asyncio.sleep(0.5)
            
            # Separar WOs e BRs
            for p in epo_patents:
                if p["country"] == "WO":
                    all_wo_numbers.add(p["number"])
                elif p["country"] == "BR":
                    all_br_patents.append({
                        "number": p["full_number"],
                        "source": "epo_search"
                    })
            
            logger.info(f"EPO found: {len(all_wo_numbers)} WOs, {len([p for p in epo_patents if p['country']=='BR'])} BRs")
            
            # Buscar famílias dos WOs encontrados
            for wo in list(all_wo_numbers)[:15]:
                family = await get_epo_family(wo, epo_token, client)
                for member in family:
                    if member["country"] == "BR":
                        all_br_patents.append({
                            "number": member["full_number"],
                            "wo_primary": wo,
                            "source": "epo_family"
                        })
                await asyncio.sleep(0.3)
        
        # ========== STEP 3: GOOGLE PATENTS SCRAPING ==========
        logger.info(f"=== STEP 3: Google Patents Scraping ===")
        sources_used.append("google_patents")
        
        gp_queries = [molecule_name]
        if pubchem_data["dev_codes"]:
            gp_queries.append(pubchem_data["dev_codes"][0])
        
        for query in gp_queries[:3]:
            gp_results = await scrape_google_patents(query, client)
            
            for p in gp_results:
                if p["country"] == "WO":
                    all_wo_numbers.add(p["number"])
                elif p["country"] == "BR":
                    all_br_patents.append({
                        "number": p["number"],
                        "source": "google_patents"
                    })
            
            await asyncio.sleep(1.0)
        
        # Buscar famílias dos WOs no Google Patents
        for wo in list(all_wo_numbers)[:10]:
            family = await get_google_patent_family(wo, client)
            for member in family:
                all_br_patents.append({
                    "number": member["number"],
                    "wo_primary": wo,
                    "source": member.get("source", "google_patents_family")
                })
            await asyncio.sleep(0.5)
        
        # ========== STEP 4: INPI CRAWLER ==========
        logger.info(f"=== STEP 4: INPI Crawler ===")
        sources_used.append("inpi")
        
        inpi_terms = [molecule_name]
        if molecule_name_pt:
            inpi_terms.append(molecule_name_pt)
        inpi_terms.extend(pubchem_data["dev_codes"][:7])
        
        # Adicionar sinônimos relevantes
        for syn in pubchem_data["synonyms"][:5]:
            if len(syn) > 5 and not any(c.isdigit() for c in syn[:3]):
                inpi_terms.append(syn)
        
        inpi_patents = await search_inpi(inpi_terms, client)
        all_br_patents.extend(inpi_patents)
        
        # ========== STEP 5: DEDUPLICATION ==========
        logger.info(f"=== STEP 5: Deduplication ===")
        logger.info(f"Raw BR patents: {len(all_br_patents)}")
        
        unique_patents = deduplicate_patents(all_br_patents)
        
        # Classificar
        for p in unique_patents:
            p["patent_type"] = classify_patent(p)
        
        # Ordenar
        unique_patents.sort(key=lambda x: x.get("number", ""))
        
        elapsed = (datetime.now() - start_time).total_seconds()
        
        # ========== RESULT ==========
        result = {
            "molecule": molecule_name,
            "molecule_pt": molecule_name_pt,
            "timestamp": datetime.now().isoformat(),
            "elapsed_seconds": round(elapsed, 2),
            "pubchem_data": {
                "cid": pubchem_data["cid"],
                "dev_codes": pubchem_data["dev_codes"],
                "cas": pubchem_data["cas"],
                "synonyms_count": len(pubchem_data["synonyms"])
            },
            "search_stats": {
                "sources_used": sources_used,
                "wo_numbers_found": len(all_wo_numbers),
                "wo_numbers": sorted(list(all_wo_numbers))[:20],
                "raw_br_count": len(all_br_patents),
                "unique_br_count": len(unique_patents)
            },
            "cortellis_comparison": {
                "expected": expected_br_count,
                "found": len(unique_patents),
                "match_rate": f"{min(len(unique_patents) / max(expected_br_count, 1) * 100, 150):.1f}%",
                "status": (
                    "✅ EXCELLENT" if len(unique_patents) >= expected_br_count else
                    "🟡 GOOD" if len(unique_patents) >= expected_br_count * 0.75 else
                    "🟠 PARTIAL" if len(unique_patents) >= expected_br_count * 0.5 else
                    "🔴 NEEDS IMPROVEMENT"
                )
            },
            "br_patents": unique_patents
        }
        
        logger.info(f"=== COMPLETE: {len(unique_patents)} unique BR patents in {elapsed:.1f}s ===")
        
        return result

# ============================================================
# OTHER ENDPOINTS
# ============================================================
@app.get("/")
async def root():
    return {
        "service": "Pharmyrus V20",
        "version": "20.0.0",
        "description": "Patent search using EPO OPS + Stealth Crawlers + INPI",
        "endpoints": {
            "complete_search": "/api/v1/search/complete?molecule_name=darolutamide&molecule_name_pt=darolutamida",
            "health": "/health"
        }
    }

@app.get("/health")
async def health():
    return {
        "status": "healthy",
        "version": "20.0.0",
        "sources": ["pubchem", "epo_ops", "google_patents_scrape", "inpi_crawler"]
    }

if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)

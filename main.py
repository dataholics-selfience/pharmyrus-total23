"""
Pharmyrus V22 - AUTODESCOBERTA COMPLETA

A partir APENAS do nome da molécula:
1. Descobre dev codes, CAS, sinônimos (PubChem)
2. Descobre nome comercial e fabricantes (DrugBank scraping)
3. Traduz para português automaticamente
4. Faz primeira busca EPO → descobre APPLICANTS
5. Faz segunda busca EPO com applicants → encontra mais WOs
6. Busca família de cada WO → extrai BRs
7. Busca INPI com todos os termos descobertos
"""
from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware
from typing import Optional, Dict, List, Set
import asyncio
import httpx
import os
import logging
import re
import base64
from datetime import datetime, timedelta
from urllib.parse import quote_plus

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(
    title="Pharmyrus V22 - Autodescoberta",
    version="22.0.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# EPO Credentials
EPO_KEY = "G5wJypxeg0GXEJoMGP37tdK370aKxeMszGKAkD6QaR0yiR5X"
EPO_SECRET = "zg5AJ0EDzXdJey3GaFNM8ztMVxHKXRrAihXH93iS5ZAzKPAPMFLuVUfiEuAqpdbz"
_epo_token = None
_epo_token_expires = None

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9,pt-BR;q=0.8",
}

# ============================================================
# TRADUÇÃO AUTOMÁTICA (MyMemory API - gratuita)
# ============================================================
async def translate_to_portuguese(text: str, client: httpx.AsyncClient) -> str:
    """Traduz texto para português usando MyMemory API (gratuita)"""
    try:
        url = f"https://api.mymemory.translated.net/get?q={quote_plus(text)}&langpair=en|pt-BR"
        response = await client.get(url, timeout=10.0)
        
        if response.status_code == 200:
            data = response.json()
            translated = data.get("responseData", {}).get("translatedText", "")
            if translated and translated.lower() != text.lower():
                logger.info(f"Tradução: {text} → {translated}")
                return translated
    except Exception as e:
        logger.error(f"Translation error: {e}")
    
    # Fallback: adicionar sufixo comum em português
    if text.endswith("ide"):
        return text[:-1] + "a"  # darolutamide → darolutamida
    elif text.endswith("ib"):
        return text + "e"  # olaparib → olaparibe
    return text

# ============================================================
# EPO TOKEN
# ============================================================
async def get_epo_token(client: httpx.AsyncClient) -> Optional[str]:
    global _epo_token, _epo_token_expires
    
    now = datetime.now()
    if _epo_token and _epo_token_expires and now < _epo_token_expires:
        return _epo_token
    
    try:
        creds = f"{EPO_KEY}:{EPO_SECRET}"
        b64 = base64.b64encode(creds.encode()).decode()
        
        response = await client.post(
            "https://ops.epo.org/3.2/auth/accesstoken",
            headers={"Authorization": f"Basic {b64}", "Content-Type": "application/x-www-form-urlencoded"},
            data={"grant_type": "client_credentials"},
            timeout=30.0
        )
        
        if response.status_code == 200:
            data = response.json()
            _epo_token = data.get("access_token")
            _epo_token_expires = now + timedelta(seconds=int(data.get("expires_in", 1200)) - 60)
            return _epo_token
    except Exception as e:
        logger.error(f"EPO token error: {e}")
    return None

# ============================================================
# FASE 1: PUBCHEM - dev codes, CAS, sinônimos
# ============================================================
async def enrich_from_pubchem(molecule: str, client: httpx.AsyncClient) -> Dict:
    result = {"dev_codes": [], "cas": None, "synonyms": [], "cid": None, "brand_names": []}
    
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
            
            for syn in synonyms[:150]:
                if cas_pattern.match(syn) and not result["cas"]:
                    result["cas"] = syn
                elif dev_pattern.match(syn) and len(result["dev_codes"]) < 15:
                    if syn not in result["dev_codes"]:
                        result["dev_codes"].append(syn)
                elif len(syn) > 3 and len(syn) < 30:
                    # Detectar nomes comerciais (geralmente capitalizados)
                    if syn[0].isupper() and " " not in syn and not any(c.isdigit() for c in syn[:3]):
                        if syn not in result["brand_names"] and len(result["brand_names"]) < 10:
                            result["brand_names"].append(syn)
                    elif len(result["synonyms"]) < 20:
                        result["synonyms"].append(syn)
            
            logger.info(f"PubChem: CID={result['cid']}, {len(result['dev_codes'])} dev codes, {len(result['brand_names'])} brand names")
    except Exception as e:
        logger.error(f"PubChem error: {e}")
    
    return result

# ============================================================
# FASE 1B: DRUGBANK SCRAPING - fabricante, nome comercial
# ============================================================
async def scrape_drugbank(molecule: str, client: httpx.AsyncClient) -> Dict:
    """Scraping do DrugBank para encontrar fabricante e nome comercial"""
    result = {"manufacturer": None, "brand_name": None, "categories": []}
    
    try:
        # Buscar página do DrugBank via Google
        search_url = f"https://go.drugbank.com/unearth/q?query={quote_plus(molecule)}&searcher=drugs"
        response = await client.get(search_url, headers=HEADERS, timeout=30.0, follow_redirects=True)
        
        if response.status_code == 200:
            html = response.text
            
            # Extrair fabricante
            mfr_pattern = re.compile(r'Manufacturer[s]?.*?<[^>]+>([^<]+)</[^>]+>', re.IGNORECASE | re.DOTALL)
            mfr_match = mfr_pattern.search(html)
            if mfr_match:
                result["manufacturer"] = mfr_match.group(1).strip()
            
            # Extrair nome comercial
            brand_pattern = re.compile(r'Brand\s*name[s]?.*?<[^>]+>([^<]+)</[^>]+>', re.IGNORECASE | re.DOTALL)
            brand_match = brand_pattern.search(html)
            if brand_match:
                result["brand_name"] = brand_match.group(1).strip()
            
            # Tentar extrair de "Products" section
            prod_pattern = re.compile(r'<td[^>]*>([A-Z][a-z]+(?:\s[A-Z][a-z]+)?)</td>\s*<td[^>]*>([^<]+)</td>', re.IGNORECASE)
            for match in prod_pattern.finditer(html):
                brand = match.group(1).strip()
                company = match.group(2).strip()
                if not result["brand_name"] and len(brand) > 3:
                    result["brand_name"] = brand
                if not result["manufacturer"] and len(company) > 3:
                    result["manufacturer"] = company
            
            logger.info(f"DrugBank: brand={result['brand_name']}, manufacturer={result['manufacturer']}")
    except Exception as e:
        logger.error(f"DrugBank error: {e}")
    
    return result

# ============================================================
# FASE 2: EPO BUSCA INICIAL - descobrir applicants
# ============================================================
async def epo_search_discover_applicants(molecule: str, dev_codes: List[str], token: str, client: httpx.AsyncClient) -> tuple:
    """Primeira busca EPO para descobrir applicants e WOs iniciais"""
    wo_numbers = set()
    applicants = set()
    
    queries = [f'txt="{molecule}"', f'ti="{molecule}"']
    for dev in dev_codes[:3]:
        queries.append(f'txt="{dev}"')
    
    for query in queries:
        try:
            response = await client.get(
                "https://ops.epo.org/3.2/rest-services/published-data/search/biblio",
                params={"q": query, "Range": "1-50"},
                headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
                timeout=30.0
            )
            
            if response.status_code == 200:
                data = response.json()
                search_result = data.get("ops:world-patent-data", {}).get("ops:biblio-search", {})
                
                pub_refs = search_result.get("ops:search-result", {}).get("exchange-documents", [])
                if not isinstance(pub_refs, list):
                    pub_refs = [pub_refs] if pub_refs else []
                
                for doc in pub_refs:
                    # Extrair WO
                    bib = doc.get("exchange-document", {}).get("bibliographic-data", {})
                    pub_ref = bib.get("publication-reference", {})
                    doc_id = pub_ref.get("document-id", {})
                    if isinstance(doc_id, list):
                        doc_id = doc_id[0] if doc_id else {}
                    
                    country = doc_id.get("country", {}).get("$", "")
                    number = doc_id.get("doc-number", {}).get("$", "")
                    
                    if country == "WO" and number:
                        wo_numbers.add(f"WO{number}")
                    
                    # Extrair applicants
                    parties = bib.get("parties", {})
                    apps = parties.get("applicants", {}).get("applicant", [])
                    if not isinstance(apps, list):
                        apps = [apps] if apps else []
                    
                    for app in apps:
                        name = app.get("applicant-name", {}).get("name", {}).get("$", "")
                        if name:
                            # Limpar nome
                            clean = re.sub(r'\s*(Inc|Corp|Ltd|LLC|GmbH|AG|S\.?A\.?|Co\.?)\.?\s*$', '', name, flags=re.IGNORECASE).strip()
                            if len(clean) > 2:
                                applicants.add(clean)
            
            await asyncio.sleep(0.3)
        except Exception as e:
            logger.error(f"EPO discover error: {e}")
    
    logger.info(f"EPO Discover: {len(wo_numbers)} WOs, {len(applicants)} applicants: {list(applicants)[:5]}")
    return wo_numbers, applicants

# ============================================================
# FASE 3: EPO BUSCA EXPANDIDA - com applicants descobertos
# ============================================================
async def epo_search_with_applicants(molecule: str, applicants: Set[str], token: str, client: httpx.AsyncClient) -> Set[str]:
    """Segunda busca EPO usando applicants descobertos"""
    wo_numbers = set()
    
    for applicant in list(applicants)[:10]:
        try:
            query = f'pa="{applicant}" and txt="{molecule}"'
            
            response = await client.get(
                "https://ops.epo.org/3.2/rest-services/published-data/search",
                params={"q": query, "Range": "1-100"},
                headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
                timeout=30.0
            )
            
            if response.status_code == 200:
                data = response.json()
                search_result = data.get("ops:world-patent-data", {}).get("ops:biblio-search", {})
                total = search_result.get("@total-result-count", 0)
                
                pub_refs = search_result.get("ops:search-result", {}).get("ops:publication-reference", [])
                if not isinstance(pub_refs, list):
                    pub_refs = [pub_refs] if pub_refs else []
                
                for ref in pub_refs:
                    doc_id = ref.get("document-id", {})
                    if isinstance(doc_id, list):
                        doc_id = doc_id[0] if doc_id else {}
                    
                    country = doc_id.get("country", {}).get("$", "")
                    number = doc_id.get("doc-number", {}).get("$", "")
                    
                    if country == "WO" and number:
                        wo_numbers.add(f"WO{number}")
                
                logger.info(f"EPO '{applicant}': {total} results")
            
            await asyncio.sleep(0.3)
        except Exception as e:
            logger.error(f"EPO applicant search error: {e}")
    
    return wo_numbers

# ============================================================
# FASE 4: EPO FAMÍLIA - extrair BRs de cada WO
# ============================================================
async def get_epo_family_br(wo: str, token: str, client: httpx.AsyncClient) -> List[Dict]:
    """Busca família de um WO e extrai patentes BR"""
    br_patents = []
    
    try:
        clean_wo = re.sub(r'[^A-Z0-9]', '', wo.upper())
        
        response = await client.get(
            f"https://ops.epo.org/3.2/rest-services/family/publication/docdb/{clean_wo}/biblio",
            headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
            timeout=30.0
        )
        
        if response.status_code == 200:
            data = response.json()
            family = data.get("ops:world-patent-data", {}).get("ops:patent-family", {})
            members = family.get("ops:family-member", [])
            
            if not isinstance(members, list):
                members = [members] if members else []
            
            for member in members:
                pub_ref = member.get("publication-reference", {})
                doc_id = pub_ref.get("document-id", {})
                
                if isinstance(doc_id, list):
                    doc_id = doc_id[0] if doc_id else {}
                
                country = doc_id.get("country", {}).get("$", "")
                number = doc_id.get("doc-number", {}).get("$", "")
                
                if country == "BR" and number:
                    # Extrair título
                    title = ""
                    try:
                        bib = member.get("bibliographic-data", {})
                        inv_title = bib.get("invention-title", [])
                        if isinstance(inv_title, list) and inv_title:
                            for t in inv_title:
                                if t.get("@lang") == "pt" or t.get("@lang") == "en":
                                    title = t.get("$", "")
                                    break
                            if not title:
                                title = inv_title[0].get("$", "")
                    except:
                        pass
                    
                    # Extrair applicant
                    applicant = ""
                    try:
                        parties = member.get("bibliographic-data", {}).get("parties", {})
                        apps = parties.get("applicants", {}).get("applicant", [])
                        if isinstance(apps, list) and apps:
                            applicant = apps[0].get("applicant-name", {}).get("name", {}).get("$", "")
                    except:
                        pass
                    
                    br_patents.append({
                        "number": f"BR{number}",
                        "wo_primary": wo,
                        "title": title,
                        "applicant": applicant,
                        "source": "epo_family"
                    })
                    logger.info(f"  Family: BR{number} from {wo}")
    except Exception as e:
        logger.error(f"EPO family error: {e}")
    
    return br_patents

# ============================================================
# FASE 5: INPI SCRAPING DIRETO
# ============================================================
async def search_inpi(terms: List[str], client: httpx.AsyncClient) -> List[Dict]:
    """Busca direta no INPI"""
    patents = []
    seen = set()
    
    for term in terms:
        if not term or len(term) < 3:
            continue
        
        try:
            # Tentar busca avançada do INPI
            url = "https://busca.inpi.gov.br/pePI/servlet/PatenteServletController"
            
            response = await client.get(
                url,
                params={"Action": "SearchPatent", "Query": term},
                headers=HEADERS,
                timeout=60.0,
                follow_redirects=True
            )
            
            if response.status_code == 200:
                html = response.text
                
                # Padrões para BR
                patterns = [
                    re.compile(r'BR\s*(\d{2})\s*(\d{4})\s*(\d{6})\s*(\d)', re.IGNORECASE),
                    re.compile(r'(BR\d{12,15})', re.IGNORECASE),
                ]
                
                for pattern in patterns:
                    for match in pattern.finditer(html):
                        if isinstance(match.groups()[0], tuple) or len(match.groups()) > 1:
                            br_num = f"BR-{match.group(1)}-{match.group(2)}-{match.group(3)}-{match.group(4)}"
                        else:
                            br_num = match.group(1)
                        
                        if br_num not in seen:
                            seen.add(br_num)
                            patents.append({
                                "number": br_num,
                                "source": "inpi",
                                "search_term": term
                            })
                
                logger.info(f"INPI '{term}': {len([p for p in patents if p.get('search_term') == term])} patents")
            
            await asyncio.sleep(1.0)
        except Exception as e:
            logger.error(f"INPI error: {e}")
    
    return patents

# ============================================================
# DEDUPLICATION & CLASSIFICATION
# ============================================================
def normalize_br(num: str) -> str:
    clean = re.sub(r'[^A-Z0-9]', '', num.upper())
    if clean.startswith("BR") and len(clean) > 10:
        rest = clean[2:]
        if len(rest) == 13:
            return f"BR-{rest[:2]}-{rest[2:6]}-{rest[6:12]}-{rest[12]}"
    return num

def deduplicate(patents: List[Dict]) -> List[Dict]:
    seen = {}
    for p in patents:
        key = re.sub(r'[^A-Z0-9]', '', p.get("number", "").upper())
        if key and len(key) >= 8:
            if key not in seen:
                seen[key] = p.copy()
            else:
                for k in ["title", "applicant", "wo_primary"]:
                    if not seen[key].get(k) and p.get(k):
                        seen[key][k] = p[k]
    return list(seen.values())

def classify(p: Dict) -> str:
    text = (p.get("title", "") + " " + p.get("applicant", "")).lower()
    if "cristal" in text or "polymorph" in text:
        return "CRYSTALLINE"
    elif "process" in text or "síntese" in text or "preparation" in text:
        return "PROCESS"
    elif "formulat" in text or "composition" in text:
        return "FORMULATION"
    elif "uso" in text or "treatment" in text or "use" in text:
        return "MEDICAL_USE"
    elif "combinat" in text:
        return "COMBINATION"
    return "OTHER"

# ============================================================
# MAIN ENDPOINT
# ============================================================
@app.get("/api/v1/search/complete")
async def complete_search(
    molecule_name: str = Query(..., description="Nome da molécula (apenas isso!)"),
    expected_br_count: int = Query(8, description="Benchmark Cortellis")
):
    """
    Busca completa AUTODESCOBERTA
    
    A partir APENAS do nome da molécula, o sistema:
    1. Descobre dev codes, CAS, nomes comerciais (PubChem)
    2. Descobre fabricante (DrugBank)
    3. Traduz para português automaticamente
    4. Descobre applicants via primeira busca EPO
    5. Faz segunda busca EPO com applicants descobertos
    6. Busca família de cada WO → extrai BRs
    7. Busca INPI com todos os termos descobertos
    """
    start = datetime.now()
    
    async with httpx.AsyncClient(verify=False, timeout=60.0) as client:
        # ========== FASE 1: ENRIQUECIMENTO ==========
        logger.info(f"=== FASE 1: Enriquecimento para '{molecule_name}' ===")
        
        # PubChem
        pubchem = await enrich_from_pubchem(molecule_name, client)
        
        # DrugBank
        drugbank = await scrape_drugbank(molecule_name, client)
        
        # Tradução automática
        molecule_pt = await translate_to_portuguese(molecule_name, client)
        
        # Consolidar dados descobertos
        discovered = {
            "molecule_en": molecule_name,
            "molecule_pt": molecule_pt,
            "brand_name": drugbank.get("brand_name") or (pubchem["brand_names"][0] if pubchem["brand_names"] else None),
            "manufacturer": drugbank.get("manufacturer"),
            "dev_codes": pubchem["dev_codes"],
            "cas": pubchem["cas"],
            "synonyms": pubchem["synonyms"][:10]
        }
        
        logger.info(f"Descoberto: {discovered}")
        
        # ========== FASE 2: EPO DESCOBERTA DE APPLICANTS ==========
        logger.info(f"=== FASE 2: EPO Descoberta de Applicants ===")
        
        all_wo_numbers: Set[str] = set()
        all_applicants: Set[str] = set()
        all_br_patents: List[Dict] = []
        
        epo_token = await get_epo_token(client)
        
        if epo_token:
            wo_initial, applicants = await epo_search_discover_applicants(
                molecule_name, 
                pubchem["dev_codes"], 
                epo_token, 
                client
            )
            all_wo_numbers.update(wo_initial)
            all_applicants.update(applicants)
            
            # Adicionar manufacturer descoberto
            if discovered["manufacturer"]:
                all_applicants.add(discovered["manufacturer"])
            
            logger.info(f"Applicants descobertos: {list(all_applicants)}")
            
            # ========== FASE 3: EPO BUSCA EXPANDIDA ==========
            logger.info(f"=== FASE 3: EPO Busca com Applicants ===")
            
            wo_expanded = await epo_search_with_applicants(
                molecule_name,
                all_applicants,
                epo_token,
                client
            )
            all_wo_numbers.update(wo_expanded)
            
            logger.info(f"Total WOs após expansão: {len(all_wo_numbers)}")
            
            # ========== FASE 4: EXTRAIR BRs DAS FAMÍLIAS ==========
            logger.info(f"=== FASE 4: Extrair BRs de {len(all_wo_numbers)} WOs ===")
            
            for wo in sorted(all_wo_numbers)[:30]:
                brs = await get_epo_family_br(wo, epo_token, client)
                all_br_patents.extend(brs)
                await asyncio.sleep(0.2)
        
        # ========== FASE 5: INPI DIRETO ==========
        logger.info(f"=== FASE 5: INPI Direto ===")
        
        inpi_terms = [molecule_name, molecule_pt]
        if discovered["brand_name"]:
            inpi_terms.append(discovered["brand_name"])
        inpi_terms.extend(pubchem["dev_codes"][:5])
        
        inpi_patents = await search_inpi(inpi_terms, client)
        all_br_patents.extend(inpi_patents)
        
        # ========== FASE 6: DEDUPLICAÇÃO ==========
        logger.info(f"=== FASE 6: Deduplicação ===")
        logger.info(f"Raw: {len(all_br_patents)} BRs")
        
        unique = deduplicate(all_br_patents)
        
        for p in unique:
            p["patent_type"] = classify(p)
            p["number_normalized"] = normalize_br(p.get("number", ""))
        
        unique.sort(key=lambda x: x.get("number", ""))
        
        elapsed = (datetime.now() - start).total_seconds()
        
        result = {
            "input": {"molecule_name": molecule_name},
            "autodiscovered": {
                "molecule_pt": molecule_pt,
                "brand_name": discovered["brand_name"],
                "manufacturer": discovered["manufacturer"],
                "dev_codes": discovered["dev_codes"],
                "cas": discovered["cas"],
                "applicants_found": sorted(list(all_applicants))
            },
            "search_stats": {
                "elapsed_seconds": round(elapsed, 2),
                "wo_count": len(all_wo_numbers),
                "wo_numbers": sorted(list(all_wo_numbers)),
                "raw_br": len(all_br_patents),
                "unique_br": len(unique)
            },
            "cortellis": {
                "expected": expected_br_count,
                "found": len(unique),
                "rate": f"{min(len(unique)/max(expected_br_count,1)*100, 150):.1f}%",
                "status": "✅ EXCELLENT" if len(unique) >= expected_br_count else
                         "🟡 GOOD" if len(unique) >= expected_br_count * 0.75 else
                         "🔴 NEEDS IMPROVEMENT"
            },
            "br_patents": unique
        }
        
        logger.info(f"=== COMPLETE: {len(unique)} BR patents in {elapsed:.1f}s ===")
        return result

@app.get("/")
async def root():
    return {
        "service": "Pharmyrus V22 - Autodescoberta",
        "version": "22.0.0",
        "description": "Sistema inteligente que descobre tudo automaticamente",
        "usage": "/api/v1/search/complete?molecule_name=darolutamide",
        "features": [
            "Descobre dev codes e CAS via PubChem",
            "Descobre fabricante via DrugBank",
            "Traduz para português automaticamente",
            "Descobre applicants via EPO",
            "Busca expandida com applicants descobertos",
            "INPI integrado"
        ]
    }

@app.get("/health")
async def health():
    return {"status": "healthy", "version": "22.0.0"}

if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)

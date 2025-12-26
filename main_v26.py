"""
Pharmyrus v26 - Multi-Country Patent Search API
Versão aprimorada com busca por citações e estratégias expandidas
"""

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any
import httpx
import base64
import asyncio
import re
import json
from datetime import datetime
import logging

# Logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("pharmyrus")

# EPO Credentials
EPO_KEY = "G5wJypxeg0GXEJoMGP37tdK370aKxeMszGKAkD6QaR0yiR5X"
EPO_SECRET = "zg5AJ0EDzXdJey3GaFNM8ztMVxHKXRrAihXH93iS5ZAzKPAPMFLuVUfiEuAqpdbz"

# Country codes supported
COUNTRY_CODES = {
    "BR": "Brazil", "US": "United States", "EP": "European Patent",
    "CN": "China", "JP": "Japan", "KR": "South Korea", "IN": "India",
    "MX": "Mexico", "AR": "Argentina", "CL": "Chile", "CO": "Colombia",
    "PE": "Peru", "CA": "Canada", "AU": "Australia", "RU": "Russia", "ZA": "South Africa"
}

app = FastAPI(
    title="Pharmyrus v26",
    description="Multi-Country Patent Search API with Citation Discovery",
    version="26.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

class SearchRequest(BaseModel):
    nome_molecula: str
    nome_comercial: Optional[str] = None
    paises_alvo: List[str] = Field(default=["BR"])
    incluir_wo: bool = True
    max_results: int = 100

class PatentResult(BaseModel):
    patent_number: str
    country: str
    country_name: str
    wo_primary: Optional[str] = None
    title: Optional[str] = None
    title_original: Optional[str] = None
    abstract: Optional[str] = None
    applicants: List[str] = []
    inventors: List[str] = []
    ipc_codes: List[str] = []
    publication_date: Optional[str] = None
    filing_date: Optional[str] = None
    priority_date: Optional[str] = None
    kind: Optional[str] = None
    link_espacenet: Optional[str] = None
    link_national: Optional[str] = None


async def get_epo_token(client: httpx.AsyncClient) -> str:
    """Obtém token de acesso EPO"""
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
    
    if response.status_code != 200:
        raise HTTPException(status_code=500, detail="EPO authentication failed")
    
    return response.json()["access_token"]


async def get_pubchem_data(client: httpx.AsyncClient, molecule: str) -> Dict:
    """Obtém dados do PubChem (dev codes, CAS, sinônimos)"""
    try:
        response = await client.get(
            f"https://pubchem.ncbi.nlm.nih.gov/rest/pug/compound/name/{molecule}/synonyms/JSON",
            timeout=30.0
        )
        if response.status_code == 200:
            data = response.json()
            synonyms = data.get("InformationList", {}).get("Information", [{}])[0].get("Synonym", [])
            
            dev_codes = []
            cas = None
            
            for syn in synonyms[:100]:
                if re.match(r'^[A-Z]{2,5}-?\d{3,7}[A-Z]?$', syn, re.I) and len(syn) < 20:
                    if syn not in dev_codes:
                        dev_codes.append(syn)
                if re.match(r'^\d{2,7}-\d{2}-\d$', syn) and not cas:
                    cas = syn
            
            return {
                "dev_codes": dev_codes[:10],
                "cas": cas,
                "synonyms": synonyms[:20]
            }
    except Exception as e:
        logger.warning(f"PubChem error: {e}")
    
    return {"dev_codes": [], "cas": None, "synonyms": []}


def build_search_queries(molecule: str, brand: str, dev_codes: List[str], cas: str = None) -> List[str]:
    """Constrói queries otimizadas para busca EPO - VERSÃO EXPANDIDA"""
    queries = []
    
    # 1. Nome da molécula (múltiplas variações)
    queries.append(f'txt="{molecule}"')
    queries.append(f'ti="{molecule}"')
    queries.append(f'ab="{molecule}"')  # Abstract
    
    # 2. Nome comercial
    if brand:
        queries.append(f'txt="{brand}"')
        queries.append(f'ti="{brand}"')
    
    # 3. Dev codes (expandido para 5)
    for code in dev_codes[:5]:
        queries.append(f'txt="{code}"')
        code_no_hyphen = code.replace("-", "")
        if code_no_hyphen != code:
            queries.append(f'txt="{code_no_hyphen}"')
    
    # 4. CAS number
    if cas:
        queries.append(f'txt="{cas}"')
    
    # 5. Applicants conhecidos + keywords terapêuticas
    applicants = ["Orion", "Bayer", "AstraZeneca", "Pfizer", "Novartis", "Roche", "Merck", "Johnson", "Bristol-Myers"]
    keywords = ["androgen", "receptor", "crystalline", "pharmaceutical", "process", "formulation", 
                "prostate", "cancer", "inhibitor", "modulating", "antagonist"]
    
    for app in applicants[:5]:
        for kw in keywords[:4]:
            queries.append(f'pa="{app}" and ti="{kw}"')
    
    # 6. Queries específicas para classes terapêuticas
    queries.append('txt="nonsteroidal antiandrogen"')
    queries.append('txt="androgen receptor antagonist"')
    queries.append('txt="nmCRPC"')
    queries.append('txt="non-metastatic" and txt="castration-resistant"')
    queries.append('ti="androgen receptor" and ti="inhibitor"')
    
    return queries


async def search_epo(client: httpx.AsyncClient, token: str, query: str) -> List[str]:
    """Executa busca no EPO e retorna lista de WOs"""
    wos = set()
    
    try:
        response = await client.get(
            "https://ops.epo.org/3.2/rest-services/published-data/search",
            params={"q": query, "Range": "1-100"},
            headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
            timeout=30.0
        )
        
        if response.status_code == 200:
            data = response.json()
            pub_refs = data.get("ops:world-patent-data", {}).get("ops:biblio-search", {}).get("ops:search-result", {}).get("ops:publication-reference", [])
            
            if not isinstance(pub_refs, list):
                pub_refs = [pub_refs] if pub_refs else []
            
            for ref in pub_refs:
                doc_id = ref.get("document-id", {})
                if isinstance(doc_id, list):
                    doc_id = doc_id[0] if doc_id else {}
                
                if doc_id.get("@document-id-type") == "docdb":
                    country = doc_id.get("country", {}).get("$", "")
                    number = doc_id.get("doc-number", {}).get("$", "")
                    if country == "WO" and number:
                        wos.add(f"WO{number}")
        
    except Exception as e:
        logger.debug(f"Search error for query '{query}': {e}")
    
    return list(wos)


async def search_citations(client: httpx.AsyncClient, token: str, wo_number: str) -> List[str]:
    """Busca patentes que citam um WO específico"""
    wos = set()
    
    try:
        query = f'ct="{wo_number}"'
        response = await client.get(
            "https://ops.epo.org/3.2/rest-services/published-data/search",
            params={"q": query, "Range": "1-100"},
            headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
            timeout=30.0
        )
        
        if response.status_code == 200:
            data = response.json()
            pub_refs = data.get("ops:world-patent-data", {}).get("ops:biblio-search", {}).get("ops:search-result", {}).get("ops:publication-reference", [])
            
            if not isinstance(pub_refs, list):
                pub_refs = [pub_refs] if pub_refs else []
            
            for ref in pub_refs:
                doc_id = ref.get("document-id", {})
                if isinstance(doc_id, list):
                    doc_id = doc_id[0] if doc_id else {}
                
                if doc_id.get("@document-id-type") == "docdb":
                    country = doc_id.get("country", {}).get("$", "")
                    number = doc_id.get("doc-number", {}).get("$", "")
                    if country == "WO" and number:
                        wos.add(f"WO{number}")
    
    except Exception as e:
        logger.debug(f"Citation search error for {wo_number}: {e}")
    
    return list(wos)


async def search_related_wos(client: httpx.AsyncClient, token: str, found_wos: List[str]) -> List[str]:
    """Busca WOs relacionados via prioridades (para encontrar patentes base)"""
    additional_wos = set()
    
    for wo in found_wos[:10]:
        try:
            response = await client.get(
                f"https://ops.epo.org/3.2/rest-services/family/publication/docdb/{wo}",
                headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
                timeout=30.0
            )
            
            if response.status_code == 200:
                data = response.json()
                family = data.get("ops:world-patent-data", {}).get("ops:patent-family", {})
                
                members = family.get("ops:family-member", [])
                if not isinstance(members, list):
                    members = [members]
                
                for m in members:
                    prio = m.get("priority-claim", [])
                    if not isinstance(prio, list):
                        prio = [prio] if prio else []
                    
                    for p in prio:
                        doc_id = p.get("document-id", {})
                        if isinstance(doc_id, list):
                            doc_id = doc_id[0] if doc_id else {}
                        country = doc_id.get("country", {}).get("$", "")
                        number = doc_id.get("doc-number", {}).get("$", "")
                        if country == "WO" and number:
                            wo_num = f"WO{number}"
                            if wo_num not in found_wos:
                                additional_wos.add(wo_num)
            
            await asyncio.sleep(0.2)
        except Exception as e:
            logger.debug(f"Error searching related WOs for {wo}: {e}")
    
    return list(additional_wos)


async def get_family_patents(client: httpx.AsyncClient, token: str, wo_number: str, 
                            target_countries: List[str]) -> Dict[str, List[Dict]]:
    """Extrai patentes da família de um WO para países alvo"""
    patents = {cc: [] for cc in target_countries}
    
    try:
        # Tentar com biblio primeiro
        response = await client.get(
            f"https://ops.epo.org/3.2/rest-services/family/publication/docdb/{wo_number}/biblio",
            headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
            timeout=30.0
        )
        
        # Se 413 (família muito grande), tentar sem biblio
        if response.status_code == 413:
            response = await client.get(
                f"https://ops.epo.org/3.2/rest-services/family/publication/docdb/{wo_number}",
                headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
                timeout=30.0
            )
        
        if response.status_code != 200:
            return patents
        
        data = response.json()
        family = data.get("ops:world-patent-data", {}).get("ops:patent-family", {})
        
        members = family.get("ops:family-member", [])
        if not isinstance(members, list):
            members = [members]
        
        for member in members:
            pub_ref = member.get("publication-reference", {})
            doc_ids = pub_ref.get("document-id", [])
            
            if isinstance(doc_ids, dict):
                doc_ids = [doc_ids]
            
            for doc_id in doc_ids:
                if doc_id.get("@document-id-type") == "docdb":
                    country = doc_id.get("country", {}).get("$", "")
                    number = doc_id.get("doc-number", {}).get("$", "")
                    kind = doc_id.get("kind", {}).get("$", "")
                    
                    if country in target_countries and number:
                        patent_num = f"{country}{number}"
                        
                        # Extrair dados bibliográficos se disponíveis
                        bib = member.get("exchange-document", {}).get("bibliographic-data", {}) if "exchange-document" in member else {}
                        
                        # Título
                        titles = bib.get("invention-title", [])
                        if isinstance(titles, dict):
                            titles = [titles]
                        title_en = None
                        title_orig = None
                        for t in titles:
                            if t.get("@lang") == "en":
                                title_en = t.get("$")
                            else:
                                title_orig = t.get("$")
                        
                        # Applicants
                        applicants = []
                        parties = bib.get("parties", {}).get("applicants", {}).get("applicant", [])
                        if isinstance(parties, dict):
                            parties = [parties]
                        for p in parties[:5]:
                            name = p.get("applicant-name", {}).get("name", {}).get("$")
                            if name:
                                applicants.append(name)
                        
                        # Data publicação
                        pub_date = doc_id.get("date", {}).get("$", "")
                        
                        patent_data = {
                            "patent_number": patent_num,
                            "country": country,
                            "wo_primary": wo_number,
                            "title": title_en,
                            "title_original": title_orig,
                            "abstract": None,
                            "applicants": applicants,
                            "inventors": [],
                            "ipc_codes": [],
                            "publication_date": pub_date,
                            "filing_date": "",
                            "priority_date": None,
                            "kind": kind
                        }
                        
                        patents[country].append(patent_data)
    
    except Exception as e:
        logger.debug(f"Error getting family for {wo_number}: {e}")
    
    return patents


def generate_links(patent_number: str, country: str) -> Dict[str, str]:
    """Gera links para Espacenet e escritórios nacionais"""
    links = {
        "link_espacenet": f"https://worldwide.espacenet.com/patent/search?q=pn%3D{patent_number}"
    }
    
    national_links = {
        "BR": f"https://busca.inpi.gov.br/pePI/servlet/PatenteServletController?Action=detail&CodPedido={patent_number}",
        "US": f"https://patents.google.com/patent/{patent_number}",
        "MX": f"https://siga.impi.gob.mx/",
        "AR": f"https://portaltramites.inpi.gob.ar/",
    }
    
    if country in national_links:
        links["link_national"] = national_links[country]
    
    return links


@app.get("/")
async def root():
    return {"message": "Pharmyrus v26 - Patent Search API with Citation Discovery", "version": "26.0"}


@app.get("/health")
async def health():
    return {"status": "healthy", "version": "26.0"}


@app.get("/countries")
async def list_countries():
    return {"countries": COUNTRY_CODES}


@app.post("/search")
async def search_patents(request: SearchRequest):
    """Busca patentes para uma molécula em múltiplos países"""
    
    start_time = datetime.now()
    
    molecule = request.nome_molecula.strip()
    brand = (request.nome_comercial or "").strip()
    target_countries = [c.upper() for c in request.paises_alvo if c.upper() in COUNTRY_CODES]
    
    if not target_countries:
        target_countries = ["BR"]
    
    logger.info(f"Search started: {molecule} | Countries: {target_countries}")
    
    async with httpx.AsyncClient() as client:
        # 1. Autenticar EPO
        token = await get_epo_token(client)
        
        # 2. Enriquecer com PubChem
        pubchem = await get_pubchem_data(client, molecule)
        logger.info(f"PubChem: {len(pubchem['dev_codes'])} dev codes, CAS: {pubchem['cas']}")
        
        # 3. Construir e executar queries
        queries = build_search_queries(molecule, brand, pubchem["dev_codes"], pubchem["cas"])
        
        all_wos = set()
        for query in queries:
            wos = await search_epo(client, token, query)
            all_wos.update(wos)
            await asyncio.sleep(0.2)
        
        logger.info(f"Found {len(all_wos)} WOs from text searches")
        
        # 4. Buscar WOs relacionados via prioridades
        if all_wos:
            related_wos = await search_related_wos(client, token, list(all_wos)[:10])
            if related_wos:
                logger.info(f"Found {len(related_wos)} WOs from priority links")
                all_wos.update(related_wos)
        
        # 5. NOVO: Buscar WOs via citações dos principais WOs encontrados
        key_wos = list(all_wos)[:5]  # Top 5 WOs para buscar citações
        citation_wos = set()
        for wo in key_wos:
            citing = await search_citations(client, token, wo)
            citation_wos.update(citing)
            await asyncio.sleep(0.2)
        
        if citation_wos:
            new_from_citations = citation_wos - all_wos
            logger.info(f"Found {len(new_from_citations)} NEW WOs from citations")
            all_wos.update(citation_wos)
        
        logger.info(f"Total: {len(all_wos)} unique WO patents")
        
        # 6. Extrair patentes dos países alvo de cada WO
        patents_by_country = {cc: [] for cc in target_countries}
        seen_patents = set()
        
        for i, wo in enumerate(sorted(all_wos)):
            if i > 0 and i % 20 == 0:
                logger.info(f"Processing WO {i}/{len(all_wos)}...")
            
            family_patents = await get_family_patents(client, token, wo, target_countries)
            
            for country, patents in family_patents.items():
                for p in patents:
                    pnum = p["patent_number"]
                    if pnum not in seen_patents:
                        seen_patents.add(pnum)
                        
                        links = generate_links(pnum, country)
                        p.update(links)
                        p["country_name"] = COUNTRY_CODES.get(country, country)
                        
                        patents_by_country[country].append(p)
            
            await asyncio.sleep(0.3)
        
        # 7. Consolidar resultados
        all_patents = []
        for country, patents in patents_by_country.items():
            all_patents.extend(patents)
        
        all_patents.sort(key=lambda x: x.get("publication_date", "") or "", reverse=True)
        
        elapsed = (datetime.now() - start_time).total_seconds()
        
        return {
            "metadata": {
                "molecule": molecule,
                "brand_name": brand,
                "search_date": datetime.now().isoformat(),
                "target_countries": target_countries,
                "elapsed_seconds": round(elapsed, 2),
                "version": "Pharmyrus v26"
            },
            "summary": {
                "total_wos": len(all_wos),
                "total_patents": len(all_patents),
                "by_country": {c: len(patents_by_country.get(c, [])) for c in target_countries},
                "pubchem_dev_codes": pubchem["dev_codes"],
                "pubchem_cas": pubchem["cas"]
            },
            "wo_patents": sorted(list(all_wos)),
            "patents_by_country": patents_by_country,
            "all_patents": all_patents
        }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)

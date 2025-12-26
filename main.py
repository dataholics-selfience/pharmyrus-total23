"""
Pharmyrus v25 - Multi-Country Patent Search API
Busca patentes em múltiplos países a partir de uma molécula
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

# Country codes mapping
COUNTRY_CODES = {
    "BR": "Brazil",
    "US": "United States",
    "EP": "European Patent",
    "CN": "China",
    "JP": "Japan",
    "KR": "South Korea",
    "IN": "India",
    "MX": "Mexico",
    "AR": "Argentina",
    "CL": "Chile",
    "CO": "Colombia",
    "PE": "Peru",
    "CA": "Canada",
    "AU": "Australia",
    "RU": "Russia",
    "ZA": "South Africa",
}

app = FastAPI(
    title="Pharmyrus Patent Search API",
    description="Multi-country pharmaceutical patent search",
    version="25.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


class SearchRequest(BaseModel):
    nome_molecula: str = Field(..., description="Nome da molécula (ex: darolutamide)")
    nome_comercial: Optional[str] = Field(None, description="Nome comercial (ex: Nubeqa)")
    paises_alvo: List[str] = Field(default=["BR"], description="Lista de códigos de países (ex: ['BR', 'US', 'MX'])")
    incluir_wo: bool = Field(default=True, description="Incluir patentes WO na resposta")
    max_results: int = Field(default=100, description="Máximo de resultados por país")


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


class SearchResponse(BaseModel):
    metadata: Dict[str, Any]
    summary: Dict[str, Any]
    wo_patents: List[str]
    patents_by_country: Dict[str, List[PatentResult]]
    all_patents: List[PatentResult]


async def get_epo_token(client: httpx.AsyncClient) -> str:
    """Obtém token de autenticação do EPO"""
    creds = f"{EPO_KEY}:{EPO_SECRET}"
    b64 = base64.b64encode(creds.encode()).decode()
    
    response = await client.post(
        "https://ops.epo.org/3.2/auth/accesstoken",
        headers={
            "Authorization": f"Basic {b64}",
            "Content-Type": "application/x-www-form-urlencoded"
        },
        data={"grant_type": "client_credentials"}
    )
    response.raise_for_status()
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
                # Dev codes: XX-1234 ou XX1234
                if re.match(r'^[A-Z]{2,5}-?\d{3,7}[A-Z]?$', syn, re.I) and len(syn) < 20:
                    if syn not in dev_codes:
                        dev_codes.append(syn)
                # CAS number
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


def build_search_queries(molecule: str, brand: str, dev_codes: List[str]) -> List[str]:
    """Constrói queries otimizadas para busca EPO"""
    queries = []
    
    # Nome da molécula
    queries.append(f'txt="{molecule}"')
    queries.append(f'ti="{molecule}"')
    
    # Nome comercial
    if brand:
        queries.append(f'txt="{brand}"')
    
    # Dev codes
    for code in dev_codes[:3]:
        queries.append(f'txt="{code}"')
        # Sem hífen
        code_no_hyphen = code.replace("-", "")
        if code_no_hyphen != code:
            queries.append(f'txt="{code_no_hyphen}"')
    
    # Applicants conhecidos + keywords
    applicants = ["Orion", "Bayer", "AstraZeneca", "Pfizer", "Novartis", "Roche", "Merck"]
    keywords = ["androgen", "receptor", "crystalline", "pharmaceutical", "process", "formulation"]
    
    for app in applicants[:4]:
        for kw in keywords[:3]:
            queries.append(f'pa="{app}" and ti="{kw}"')
    
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
                
                country = doc_id.get("country", {})
                if isinstance(country, dict):
                    country = country.get("$", "")
                
                number = doc_id.get("doc-number", {})
                if isinstance(number, dict):
                    number = number.get("$", "")
                
                if country == "WO" and number:
                    wos.add(f"WO{number}")
    
    except Exception as e:
        logger.warning(f"EPO search error for '{query}': {e}")
    
    return list(wos)


async def get_family_patents(
    client: httpx.AsyncClient, 
    token: str, 
    wo: str, 
    target_countries: List[str]
) -> Dict[str, List[Dict]]:
    """Extrai patentes de países específicos da família de um WO"""
    patents_by_country = {cc: [] for cc in target_countries}
    
    try:
        # Tentar com biblio primeiro
        response = await client.get(
            f"https://ops.epo.org/3.2/rest-services/family/publication/docdb/{wo}/biblio",
            headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
            timeout=30.0
        )
        
        # Se família muito grande, tentar sem biblio
        if response.status_code == 413:
            response = await client.get(
                f"https://ops.epo.org/3.2/rest-services/family/publication/docdb/{wo}",
                headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
                timeout=30.0
            )
        
        if response.status_code != 200:
            return patents_by_country
        
        data = response.json()
        family = data.get("ops:world-patent-data", {}).get("ops:patent-family", {})
        members = family.get("ops:family-member", [])
        
        if not isinstance(members, list):
            members = [members] if members else []
        
        seen = set()
        
        for member in members:
            pub_ref = member.get("publication-reference", {})
            doc_ids = pub_ref.get("document-id", [])
            
            if not isinstance(doc_ids, list):
                doc_ids = [doc_ids] if doc_ids else []
            
            for doc_id in doc_ids:
                country = doc_id.get("country", {})
                if isinstance(country, dict):
                    country = country.get("$", "")
                
                if country not in target_countries:
                    continue
                
                number = doc_id.get("doc-number", {})
                if isinstance(number, dict):
                    number = number.get("$", "")
                
                kind = doc_id.get("kind", {})
                if isinstance(kind, dict):
                    kind = kind.get("$", "")
                
                date = doc_id.get("date", {})
                if isinstance(date, dict):
                    date = date.get("$", "")
                
                if not number:
                    continue
                
                patent_num = f"{country}{number}"
                if patent_num in seen:
                    continue
                seen.add(patent_num)
                
                # Extrair dados bibliográficos
                bib = member.get("bibliographic-data", {})
                
                patent_data = {
                    "patent_number": patent_num,
                    "country": country,
                    "wo_primary": wo,
                    "kind": kind,
                    "publication_date": date,
                }
                
                # Títulos
                titles = bib.get("invention-title", [])
                if not isinstance(titles, list):
                    titles = [titles] if titles else []
                for t in titles:
                    lang = t.get("@lang", "")
                    txt = t.get("$", "")
                    if lang == "en":
                        patent_data["title"] = txt
                    elif lang in ["pt", "es", "de", "fr", "ja", "zh", "ko"]:
                        patent_data["title_original"] = txt
                    elif not patent_data.get("title"):
                        patent_data["title"] = txt
                
                # Applicants
                parties = bib.get("parties", {})
                apps = parties.get("applicants", {}).get("applicant", [])
                if not isinstance(apps, list):
                    apps = [apps] if apps else []
                applicants = []
                for a in apps:
                    name = a.get("applicant-name", {}).get("name", {})
                    if isinstance(name, dict):
                        name = name.get("$", "")
                    if name and name not in applicants:
                        applicants.append(name)
                patent_data["applicants"] = applicants
                
                # Inventors
                invs = parties.get("inventors", {}).get("inventor", [])
                if not isinstance(invs, list):
                    invs = [invs] if invs else []
                inventors = []
                for inv in invs:
                    name = inv.get("inventor-name", {}).get("name", {})
                    if isinstance(name, dict):
                        name = name.get("$", "")
                    if name and name not in inventors:
                        inventors.append(name)
                patent_data["inventors"] = inventors
                
                # IPC codes
                class_data = bib.get("classifications-ipcr", {}).get("classification-ipcr", [])
                if not isinstance(class_data, list):
                    class_data = [class_data] if class_data else []
                ipc_codes = []
                for c in class_data[:5]:
                    ipc = c.get("text", {})
                    if isinstance(ipc, dict):
                        ipc = ipc.get("$", "")
                    if ipc:
                        ipc_codes.append(ipc.strip())
                patent_data["ipc_codes"] = ipc_codes
                
                # Filing date
                app_ref = bib.get("application-reference", {})
                app_doc_id = app_ref.get("document-id", {})
                if isinstance(app_doc_id, list):
                    app_doc_id = app_doc_id[0] if app_doc_id else {}
                filing_date = app_doc_id.get("date", {})
                if isinstance(filing_date, dict):
                    filing_date = filing_date.get("$", "")
                patent_data["filing_date"] = filing_date
                
                # Priority date
                prio = bib.get("priority-claims", {}).get("priority-claim", [])
                if not isinstance(prio, list):
                    prio = [prio] if prio else []
                if prio:
                    prio_doc = prio[0].get("document-id", {})
                    if isinstance(prio_doc, list):
                        prio_doc = prio_doc[0] if prio_doc else {}
                    prio_date = prio_doc.get("date", {})
                    if isinstance(prio_date, dict):
                        prio_date = prio_date.get("$", "")
                    patent_data["priority_date"] = prio_date
                
                patents_by_country[country].append(patent_data)
    
    except Exception as e:
        logger.warning(f"Family extraction error for {wo}: {e}")
    
    return patents_by_country


def generate_links(patent_num: str, country: str) -> Dict[str, str]:
    """Gera links para visualização da patente"""
    links = {
        "link_espacenet": f"https://worldwide.espacenet.com/patent/search?q=pn%3D{patent_num}"
    }
    
    # Links nacionais específicos
    if country == "BR":
        links["link_national"] = f"https://busca.inpi.gov.br/pePI/servlet/PatenteServletController?Action=detail&CodPedido={patent_num}"
    elif country == "US":
        num = patent_num.replace("US", "")
        links["link_national"] = f"https://patents.google.com/patent/US{num}"
    elif country == "EP":
        links["link_national"] = f"https://register.epo.org/application?number={patent_num}"
    elif country == "CN":
        links["link_national"] = f"https://patents.google.com/patent/{patent_num}"
    elif country == "JP":
        links["link_national"] = f"https://www.j-platpat.inpit.go.jp/"
    elif country == "MX":
        links["link_national"] = f"https://siga.impi.gob.mx/"
    elif country == "AR":
        links["link_national"] = f"https://portaltramites.inpi.gob.ar/"
    
    return links


@app.post("/search", response_model=SearchResponse)
async def search_patents(request: SearchRequest):
    """
    Busca patentes em múltiplos países para uma molécula farmacêutica
    """
    start_time = datetime.now()
    
    molecule = request.nome_molecula.strip()
    brand = (request.nome_comercial or "").strip()
    target_countries = [c.upper() for c in request.paises_alvo]
    
    logger.info(f"Search started: {molecule} | Countries: {target_countries}")
    
    async with httpx.AsyncClient(timeout=60.0) as client:
        # 1. Obter token EPO
        token = await get_epo_token(client)
        
        # 2. Enriquecer com PubChem
        pubchem = await get_pubchem_data(client, molecule)
        logger.info(f"PubChem: {len(pubchem['dev_codes'])} dev codes, CAS: {pubchem['cas']}")
        
        # 3. Construir e executar queries
        queries = build_search_queries(molecule, brand, pubchem["dev_codes"])
        
        all_wos = set()
        for query in queries:
            wos = await search_epo(client, token, query)
            all_wos.update(wos)
            await asyncio.sleep(0.2)  # Rate limiting
        
        logger.info(f"Found {len(all_wos)} unique WO patents")
        
        # 4. Extrair patentes dos países alvo de cada WO
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
                        
                        # Gerar links
                        links = generate_links(pnum, country)
                        p.update(links)
                        p["country_name"] = COUNTRY_CODES.get(country, country)
                        
                        patents_by_country[country].append(p)
            
            await asyncio.sleep(0.3)  # Rate limiting
        
        # 5. Consolidar resultados
        all_patents = []
        for country, patents in patents_by_country.items():
            all_patents.extend(patents)
        
        # Ordenar por data de publicação
        all_patents.sort(key=lambda x: x.get("publication_date", "") or "", reverse=True)
        
        elapsed = (datetime.now() - start_time).total_seconds()
        
        response = SearchResponse(
            metadata={
                "molecule": molecule,
                "brand_name": brand,
                "search_date": datetime.now().isoformat(),
                "target_countries": target_countries,
                "elapsed_seconds": round(elapsed, 2),
                "version": "Pharmyrus v25"
            },
            summary={
                "total_wos": len(all_wos),
                "total_patents": len(all_patents),
                "by_country": {cc: len(patents_by_country[cc]) for cc in target_countries},
                "pubchem_dev_codes": pubchem["dev_codes"],
                "pubchem_cas": pubchem["cas"]
            },
            wo_patents=sorted(list(all_wos)) if request.incluir_wo else [],
            patents_by_country=patents_by_country,
            all_patents=all_patents
        )
        
        logger.info(f"Search completed in {elapsed:.1f}s: {len(all_patents)} patents found")
        
        return response


@app.get("/health")
async def health():
    return {"status": "ok", "version": "25.0", "timestamp": datetime.now().isoformat()}


@app.get("/countries")
async def list_countries():
    """Lista países suportados"""
    return {"countries": COUNTRY_CODES}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)

import sqlite3
import datetime
import time
import random
import subprocess
import urllib.parse
from playwright.sync_api import sync_playwright

# ================================================================
# CONFIGURAÇÃO — FAGNER PEÇANHA DE OLIVEIRA
# ================================================================
CARGOS = [
    "Analista de Logística",
    "Analista de Estoque",
    "Analista de Inventário",
    "Coordenador de Logística",
    "Líder de Logística",
    "Supervisor de Almoxarifado",
    "Analista de PCP",
    "Supply Chain Analyst"
]

CIDADE          = "São Bernardo do Campo"
CIDADE_UF       = "São Bernardo do Campo, SP"
DB_NAME         = "vagas.db"
LOG_FILE        = "execucao.log"
MAX_VAGAS_CARGO = 8   # máximo de vagas novas por cargo por plataforma

# Palavras que marcam a vaga como VIP 🔥
KEYWORDS_VIP = [
    "JIT", "Lean", "Kaizen", "WMS", "SAP", "ERP",
    "Automotiva", "Scania", "Ford", "Volkswagen", "Mercedes",
    "Kanban", "FIFO", "5S", "inventário", "estoque",
    "Supply Chain", "PCP", "almoxarifado"
]

# ================================================================
# BANCO DE DADOS
# ================================================================
def init_db():
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS vagas (
            id            TEXT PRIMARY KEY,
            titulo        TEXT,
            empresa       TEXT,
            local         TEXT,
            link          TEXT,
            plataforma    TEXT,
            data_encontrada DATETIME,
            match_vip     BOOLEAN DEFAULT 0
        )
    ''')
    # Migração: adiciona coluna plataforma se já existia tabela sem ela
    try:
        cursor.execute("ALTER TABLE vagas ADD COLUMN plataforma TEXT")
    except sqlite3.OperationalError:
        pass  # coluna já existe
    conn.commit()
    conn.close()

def vaga_existe(id_vaga):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute('SELECT 1 FROM vagas WHERE id = ?', (id_vaga,))
    existe = cursor.fetchone() is not None
    conn.close()
    return existe

def salvar_vaga(vaga):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    try:
        cursor.execute('''
            INSERT INTO vagas (id, titulo, empresa, local, link, plataforma, data_encontrada, match_vip)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            vaga['id'], vaga['titulo'], vaga['empresa'], vaga['local'],
            vaga['link'], vaga.get('plataforma', ''), datetime.datetime.now(), vaga['match_vip']
        ))
        conn.commit()
        return True
    except sqlite3.IntegrityError:
        return False
    finally:
        conn.close()

# ================================================================
# UTILITÁRIOS
# ================================================================
def log(mensagem):
    timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    linha = f"[{timestamp}] {mensagem}"
    print(linha)
    with open(LOG_FILE, "a") as f:
        f.write(linha + "\n")

def notificar(qtd_novas, qtd_vip):
    if qtd_novas == 0:
        return
    titulo = "Rastreador de Vagas"
    corpo  = f"{qtd_novas} vagas novas encontradas.\n{qtd_vip} são VIP 🔥"
    urgencia = 'critical' if qtd_vip > 0 else 'normal'
    try:
        subprocess.run(['notify-send', titulo, corpo, '-u', urgencia], timeout=5)
    except Exception:
        pass

def fechar_popups(page):
    """Tenta fechar popups de cookies/consentimento comuns."""
    seletores = [
        'button[id*="onetrust-accept"]',
        'button[id*="accept"]',
        'button:has-text("Aceitar tudo")',
        'button:has-text("Aceitar")',
        'button:has-text("Concordar")',
        'button:has-text("Entendi")',
        'button:has-text("OK")',
        '[aria-label="fechar"]',
        '[aria-label="Fechar"]',
    ]
    for sel in seletores:
        try:
            btn = page.locator(sel).first
            if btn.is_visible(timeout=1500):
                btn.click()
                time.sleep(0.8)
                return
        except Exception:
            pass

def checar_vip(texto):
    return any(kw.lower() in texto.lower() for kw in KEYWORDS_VIP)

def montar_id(titulo, empresa, plataforma):
    raw = f"{plataforma}-{titulo}-{empresa}".lower()
    return urllib.parse.quote(raw)[:200]

def salvar_debug_html(page, nome_arquivo="debug_pagina.html"):
    try:
        with open(nome_arquivo, "w", encoding="utf-8") as f:
            f.write(page.content())
        log(f"   📄 HTML salvo em {nome_arquivo} para análise")
    except Exception:
        pass


# ================================================================
# PLATAFORMA 1 — INDEED BRASIL
# URL: br.indeed.com
# Parâmetros: fromage=7 (7 dias) | radius=10 (10 km) | sort=date
# ================================================================
def buscar_no_indeed(page, cargo):
    plataforma = "Indeed"
    url = (
        "https://br.indeed.com/jobs"
        f"?q={urllib.parse.quote(cargo)}"
        f"&l={urllib.parse.quote(CIDADE_UF)}"
        "&fromage=7&radius=10&sort=date"
    )
    log(f"   [{plataforma}] {cargo}")

    vagas = []
    try:
        page.goto(url, wait_until="domcontentloaded", timeout=30000)
        time.sleep(random.uniform(2, 4))
        fechar_popups(page)

        SELETOR = 'div.job_seen_beacon'
        try:
            page.wait_for_selector(SELETOR, timeout=10000)
        except Exception:
            log(f"   [{plataforma}] ⚠️ Sem cards — salvando debug")
            salvar_debug_html(page, f"debug_{plataforma.lower()}.html")
            return []

        for card in page.locator(SELETOR).all():
            try:
                titulo = ""
                for sel in ['[data-testid="jobTitle"] span', 'h2.jobTitle a span', 'a.jcs-JobTitle span']:
                    try:
                        el = card.locator(sel).first
                        if el.count():
                            titulo = el.inner_text(timeout=1500).strip()
                            if titulo: break
                    except Exception: pass
                if not titulo: continue

                empresa = "Não informada"
                for sel in ['[data-testid="company-name"]', 'span.companyName', '[class*="companyName"]']:
                    try:
                        el = card.locator(sel).first
                        if el.count():
                            t = el.inner_text(timeout=1500).strip()
                            if t: empresa = t; break
                    except Exception: pass

                local_vaga = CIDADE_UF
                try:
                    el = card.locator('[data-testid="text-location"]').first
                    if el.count():
                        t = el.inner_text(timeout=1500).strip()
                        if t: local_vaga = t
                except Exception: pass

                link = url
                for sel in ['h2.jobTitle a', 'a.jcs-JobTitle', '[data-testid="jobTitle"] a']:
                    try:
                        el = card.locator(sel).first
                        if el.count():
                            href = el.get_attribute("href", timeout=1500)
                            if href:
                                link = f"https://br.indeed.com{href}" if href.startswith("/") else href
                                break
                    except Exception: pass

                texto = card.inner_text(timeout=2000)
                vagas.append({
                    'id':         montar_id(titulo, empresa, plataforma),
                    'titulo':     titulo,
                    'empresa':    empresa,
                    'local':      local_vaga,
                    'link':       link,
                    'plataforma': plataforma,
                    'match_vip':  checar_vip(texto)
                })
            except Exception:
                continue
    except Exception as e:
        log(f"   [{plataforma}] ❌ Erro: {e}")

    log(f"   [{plataforma}] {len(vagas)} vagas encontradas")
    return vagas


# ================================================================
# PLATAFORMA 2 — GUPY
# URL: portal.gupy.io
# Usado por: Scania, Mercedes-Benz, VW, grandes indústrias do ABC
# FIX: SPA React — precisa de networkidle para renderizar os cards
# ================================================================
def buscar_no_gupy(page, cargo):
    plataforma = "Gupy"
    url = (
        "https://portal.gupy.io/job-search/term"
        f"?term={urllib.parse.quote(cargo)}"
        f"&jobCity={urllib.parse.quote(CIDADE)}"
    )
    log(f"   [{plataforma}] {cargo}")

    vagas = []
    try:
        # Gupy é SPA React — usa load + networkidle para aguardar renderização
        page.goto(url, wait_until="load", timeout=45000)
        try:
            page.wait_for_load_state("networkidle", timeout=20000)
        except Exception:
            pass  # timeout de networkidle é ok; continua
        time.sleep(random.uniform(2, 4))
        fechar_popups(page)

        # Seletores do Gupy (estrutura Styled Components + data-testid)
        SELETORES_CARD = [
            '[data-testid="job-card"]',
            'li[data-testid*="job"]',
            'div[data-testid*="job"]',
            'a[data-testid*="job-card"]',
            'div[class*="JobCard"]',
            'li[class*="JobCard"]',
            'div[class*="sc-"][class*="job"]',
        ]
        seletor_usado = None
        for sel in SELETORES_CARD:
            try:
                page.wait_for_selector(sel, timeout=6000)
                if page.locator(sel).count() > 0:
                    seletor_usado = sel
                    break
            except Exception:
                pass

        if not seletor_usado:
            log(f"   [{plataforma}] ⚠️ Sem cards — salvando debug")
            salvar_debug_html(page, f"debug_{plataforma.lower()}.html")
            return []

        for card in page.locator(seletor_usado).all():
            try:
                titulo = ""
                # Gupy mostra título em h3 ou elemento com data-testid
                for sel in [
                    '[data-testid="job-name"]', '[data-testid="job-title"]',
                    'h3', 'h2', '[class*="jobName"]', '[class*="JobName"]',
                    '[class*="title"]',
                ]:
                    try:
                        el = card.locator(sel).first
                        if el.count():
                            t = el.inner_text(timeout=1500).strip()
                            if t and len(t) > 3: titulo = t; break
                    except Exception: pass

                if not titulo:
                    # Fallback: primeira linha do texto do card
                    texto_card = card.inner_text(timeout=2000)
                    linhas = [l.strip() for l in texto_card.split('\n') if l.strip()]
                    if linhas: titulo = linhas[0]

                if not titulo: continue

                empresa = "Não informada"
                for sel in [
                    '[data-testid="company-name"]', '[data-testid="job-company"]',
                    '[class*="companyName"]', '[class*="CompanyName"]',
                    '[class*="company"]', 'span[class*="sc-"]',
                ]:
                    try:
                        el = card.locator(sel).first
                        if el.count():
                            t = el.inner_text(timeout=1500).strip()
                            if t and t != titulo: empresa = t; break
                    except Exception: pass

                link = url
                try:
                    el = card.locator('a').first
                    if el.count():
                        href = el.get_attribute("href", timeout=1500)
                        if href:
                            link = f"https://portal.gupy.io{href}" if href.startswith("/") else href
                except Exception: pass

                texto = card.inner_text(timeout=2000)
                vagas.append({
                    'id':         montar_id(titulo, empresa, plataforma),
                    'titulo':     titulo,
                    'empresa':    empresa,
                    'local':      CIDADE_UF,
                    'link':       link,
                    'plataforma': plataforma,
                    'match_vip':  checar_vip(texto)
                })
            except Exception:
                continue
    except Exception as e:
        log(f"   [{plataforma}] ❌ Erro: {e}")

    log(f"   [{plataforma}] {len(vagas)} vagas encontradas")
    return vagas


# ================================================================
# PLATAFORMA 3 — VAGAS.COM
# URL: vagas.com.br
# Forte cobertura regional — Grande ABC Paulista
# FIX: Usar URL de busca com filtro de cidade + checar relevância do título
# ================================================================
def buscar_no_vagas(page, cargo):
    plataforma = "Vagas.com"

    # URL de busca com parâmetros (mais preciso que slug)
    url = (
        "https://www.vagas.com.br/vagas-de-"
        + cargo.lower().replace(" ", "-")
        + "?filtro_cidade=S%C3%A3o+Bernardo+do+Campo"
    )
    log(f"   [{plataforma}] {cargo}")

    # Palavras-chave do cargo para filtrar resultados irrelevantes
    palavras_cargo = [w.lower() for w in cargo.split() if len(w) > 3]

    vagas = []
    try:
        page.goto(url, wait_until="domcontentloaded", timeout=30000)
        time.sleep(random.uniform(2, 4))
        fechar_popups(page)

        SELETOR = 'li.vaga'
        try:
            page.wait_for_selector(SELETOR, timeout=10000)
        except Exception:
            SELETOR = '.opportunity'
            try:
                page.wait_for_selector(SELETOR, timeout=5000)
            except Exception:
                log(f"   [{plataforma}] ⚠️ Sem cards — salvando debug")
                salvar_debug_html(page, "debug_vagascom.html")
                return []

        for card in page.locator(SELETOR).all():
            try:
                titulo = ""
                # Vagas.com: título está no h2.cargo (o texto do link ou direto)
                for sel in ['h2.cargo a', 'h2.cargo', 'a.link-detalhes-vaga', 'h2 a']:
                    try:
                        el = card.locator(sel).first
                        if el.count():
                            titulo = el.inner_text(timeout=1500).strip()
                            if titulo: break
                    except Exception: pass
                if not titulo: continue

                # Filtra resultados que não têm relação com o cargo buscado
                titulo_lower = titulo.lower()
                if palavras_cargo and not any(p in titulo_lower for p in palavras_cargo):
                    continue

                empresa = "Confidencial"
                # Vagas.com: empresa em span.empresa — muitas vezes "Nome Confidencial"
                for sel in ['span.empresa', 'a.empresa', '.empresa', '[class*="empresa"]']:
                    try:
                        el = card.locator(sel).first
                        if el.count():
                            t = el.inner_text(timeout=1500).strip()
                            if t: empresa = t; break
                    except Exception: pass

                local_vaga = CIDADE_UF
                for sel in ['span.localidade', '.localidade', '[class*="localidade"]']:
                    try:
                        el = card.locator(sel).first
                        if el.count():
                            t = el.inner_text(timeout=1500).strip()
                            if t: local_vaga = t; break
                    except Exception: pass

                link = url
                for sel in ['h2.cargo a', 'a.link-detalhes-vaga', 'a']:
                    try:
                        el = card.locator(sel).first
                        if el.count():
                            href = el.get_attribute("href", timeout=1500)
                            if href:
                                link = f"https://www.vagas.com.br{href}" if href.startswith("/") else href
                                break
                    except Exception: pass

                texto = card.inner_text(timeout=2000)
                vagas.append({
                    'id':         montar_id(titulo, empresa, plataforma),
                    'titulo':     titulo,
                    'empresa':    empresa,
                    'local':      local_vaga,
                    'link':       link,
                    'plataforma': plataforma,
                    'match_vip':  checar_vip(texto)
                })
            except Exception:
                continue
    except Exception as e:
        log(f"   [{plataforma}] ❌ Erro: {e}")

    log(f"   [{plataforma}] {len(vagas)} vagas encontradas")
    return vagas


# ================================================================
# PLATAFORMA 4 — CATHO
# URL: catho.com.br
# FIX: timeout aumentado para 60s + networkidle + seletores ampliados
# Nota: Catho tem anti-bot pesado; se bloquear consistentemente, desativar
# ================================================================
def buscar_no_catho(page, cargo):
    plataforma = "Catho"
    url = (
        "https://www.catho.com.br/vagas/"
        f"?q={urllib.parse.quote(cargo)}"
        f"&l={urllib.parse.quote(CIDADE)}"
    )
    log(f"   [{plataforma}] {cargo}")

    vagas = []
    try:
        page.goto(url, wait_until="load", timeout=60000)
        try:
            page.wait_for_load_state("networkidle", timeout=15000)
        except Exception:
            pass
        time.sleep(random.uniform(4, 7))
        fechar_popups(page)

        SELETORES_CARD = [
            '[data-testid="job-card"]',
            'article[class*="JobCard"]',
            'div[class*="JobCard"]',
            'li[class*="job-item"]',
            'div[class*="job-card"]',
            '[class*="sc-"][class*="Card"]',
        ]
        seletor_usado = None
        for sel in SELETORES_CARD:
            try:
                page.wait_for_selector(sel, timeout=8000)
                if page.locator(sel).count() > 0:
                    seletor_usado = sel
                    break
            except Exception:
                pass

        if not seletor_usado:
            log(f"   [{plataforma}] ⚠️ Sem cards — salvando debug")
            salvar_debug_html(page, f"debug_{plataforma.lower()}.html")
            return []

        for card in page.locator(seletor_usado).all():
            try:
                titulo = ""
                for sel in [
                    '[data-testid="job-title"]', 'h2 a', 'h3 a', 'h2', 'h3',
                    '[class*="title"]', '[class*="Title"]',
                ]:
                    try:
                        el = card.locator(sel).first
                        if el.count():
                            titulo = el.inner_text(timeout=1500).strip()
                            if titulo: break
                    except Exception: pass
                if not titulo: continue

                empresa = "Não informada"
                for sel in ['[data-testid="company-name"]', '[class*="company"]', '[class*="Company"]']:
                    try:
                        el = card.locator(sel).first
                        if el.count():
                            t = el.inner_text(timeout=1500).strip()
                            if t: empresa = t; break
                    except Exception: pass

                local_vaga = CIDADE_UF
                for sel in ['[data-testid="job-location"]', '[class*="location"]', '[class*="Location"]']:
                    try:
                        el = card.locator(sel).first
                        if el.count():
                            t = el.inner_text(timeout=1500).strip()
                            if t: local_vaga = t; break
                    except Exception: pass

                link = url
                try:
                    el = card.locator('a').first
                    if el.count():
                        href = el.get_attribute("href", timeout=1500)
                        if href:
                            link = f"https://www.catho.com.br{href}" if href.startswith("/") else href
                except Exception: pass

                texto = card.inner_text(timeout=2000)
                vagas.append({
                    'id':         montar_id(titulo, empresa, plataforma),
                    'titulo':     titulo,
                    'empresa':    empresa,
                    'local':      local_vaga,
                    'link':       link,
                    'plataforma': plataforma,
                    'match_vip':  checar_vip(texto)
                })
            except Exception:
                continue
    except Exception as e:
        log(f"   [{plataforma}] ❌ Erro: {e}")

    log(f"   [{plataforma}] {len(vagas)} vagas encontradas")
    return vagas


# ================================================================
# PLATAFORMA 5 — INFOJOBS
# URL: infojobs.com.br
# FIX: URL corrigida — InfoJobs BR usa /empregos/ (sem .aspx no path atual)
# ================================================================
def buscar_no_infojobs(page, cargo):
    plataforma = "InfoJobs"

    slug = cargo.lower().replace(" ", "-")
    # Tenta URL principal; se não funcionar usa URL alternativa de busca
    url_principal  = f"https://www.infojobs.com.br/empregos-de-{slug}/sao-bernardo-do-campo,sao-paulo.aspx"
    url_alternativa = (
        "https://www.infojobs.com.br/jobsearch/search-results/list.xhtml"
        f"?keyword={urllib.parse.quote(cargo)}&province=sao-paulo"
        "&normalizedProvince=sao-paulo&city=sao-bernardo-do-campo"
        "&normalizedCity=sao-bernardo-do-campo"
    )
    log(f"   [{plataforma}] {cargo}")

    vagas = []
    for url in [url_principal, url_alternativa]:
        try:
            page.goto(url, wait_until="load", timeout=40000)
            try:
                page.wait_for_load_state("networkidle", timeout=12000)
            except Exception:
                pass
            time.sleep(random.uniform(2, 4))
            fechar_popups(page)

            SELETORES_CARD = [
                'li.ij-OfferCardBasic',
                'li[class*="OfferCard"]',
                'li[class*="offer"]',
                'div[class*="OfferCard"]',
                '.boxVaga',
                'li.boxVaga',
                '[class*="offer-item"]',
            ]
            seletor_usado = None
            for sel in SELETORES_CARD:
                try:
                    page.wait_for_selector(sel, timeout=6000)
                    if page.locator(sel).count() > 0:
                        seletor_usado = sel
                        break
                except Exception:
                    pass

            if seletor_usado:
                break  # Encontrou cards, sai do loop de URLs
        except Exception as e:
            log(f"   [{plataforma}] ⚠️ URL falhou: {e}")
            continue

    if not seletor_usado:
        log(f"   [{plataforma}] ⚠️ Sem cards — salvando debug")
        salvar_debug_html(page, f"debug_{plataforma.lower()}.html")
        return []

    for card in page.locator(seletor_usado).all():
        try:
            titulo = ""
            for sel in [
                'h2 a', 'h3 a', 'a[class*="Title"]', 'a[class*="title"]',
                '[class*="title"] a', '[class*="tituloVaga"] a',
                '.tituloVaga a', '.ic1_titulo a',
            ]:
                try:
                    el = card.locator(sel).first
                    if el.count():
                        titulo = el.inner_text(timeout=1500).strip()
                        if titulo: break
                except Exception: pass
            if not titulo: continue

            empresa = "Não informada"
            for sel in [
                '[class*="company"]', '[class*="Company"]',
                '[class*="empresa"]', '.nomeEmpresa', 'span[class*="Employer"]',
            ]:
                try:
                    el = card.locator(sel).first
                    if el.count():
                        t = el.inner_text(timeout=1500).strip()
                        if t: empresa = t; break
                except Exception: pass

            local_vaga = CIDADE_UF
            for sel in ['[class*="location"]', '[class*="cidade"]', '[class*="city"]', '.localVaga']:
                try:
                    el = card.locator(sel).first
                    if el.count():
                        t = el.inner_text(timeout=1500).strip()
                        if t: local_vaga = t; break
                except Exception: pass

            link = url
            try:
                el = card.locator('a').first
                if el.count():
                    href = el.get_attribute("href", timeout=1500)
                    if href:
                        link = f"https://www.infojobs.com.br{href}" if href.startswith("/") else href
            except Exception: pass

            texto = card.inner_text(timeout=2000)
            vagas.append({
                'id':         montar_id(titulo, empresa, plataforma),
                'titulo':     titulo,
                'empresa':    empresa,
                'local':      local_vaga,
                'link':       link,
                'plataforma': plataforma,
                'match_vip':  checar_vip(texto)
            })
        except Exception:
            continue

    log(f"   [{plataforma}] {len(vagas)} vagas encontradas")
    return vagas


# ================================================================
# PLATAFORMA 6 — SINE
# URL: sine.com.br
# FIX: URL corrigida — empregabrasil.mte.gov.br não resolve mais
# ================================================================
def buscar_no_sine(page, cargo):
    plataforma = "SINE"
    slug_cargo  = cargo.lower().replace(" ", "-")
    url = (
        f"https://www.sine.com.br/vagas-emprego-em-sao-bernardo-do-campo-sp"
        f"/{slug_cargo}"
    )
    log(f"   [{plataforma}] {cargo}")

    vagas = []
    try:
        page.goto(url, wait_until="domcontentloaded", timeout=30000)
        time.sleep(random.uniform(2, 4))
        fechar_popups(page)

        # sine.com.br usa cards com classe .vaga-lista ou similar
        SELETORES_CARD = [
            'li.vaga-lista', 'li[class*="vaga"]',
            'div[class*="vaga-item"]', 'article[class*="vaga"]',
            '.resultado-vaga', 'li.resultado',
            '.vaga',
        ]
        seletor_usado = None
        for sel in SELETORES_CARD:
            try:
                page.wait_for_selector(sel, timeout=8000)
                if page.locator(sel).count() > 0:
                    seletor_usado = sel
                    break
            except Exception:
                pass

        if not seletor_usado:
            log(f"   [{plataforma}] ⚠️ Sem cards — salvando debug")
            salvar_debug_html(page, f"debug_{plataforma.lower()}.html")
            return []

        for card in page.locator(seletor_usado).all():
            try:
                titulo = ""
                for sel in ['h2 a', 'h3 a', 'a[class*="title"]', 'a[class*="cargo"]', 'a']:
                    try:
                        el = card.locator(sel).first
                        if el.count():
                            t = el.inner_text(timeout=1500).strip()
                            if t and len(t) > 3: titulo = t; break
                    except Exception: pass

                if not titulo:
                    texto_card = card.inner_text(timeout=2000)
                    linhas = [l.strip() for l in texto_card.split('\n') if l.strip()]
                    if linhas: titulo = linhas[0]
                if not titulo: continue

                empresa = "Não informada"
                for sel in ['[class*="empresa"]', '[class*="company"]', 'span[class*="nome"]']:
                    try:
                        el = card.locator(sel).first
                        if el.count():
                            t = el.inner_text(timeout=1500).strip()
                            if t: empresa = t; break
                    except Exception: pass

                link = url
                try:
                    el = card.locator('a').first
                    if el.count():
                        href = el.get_attribute("href", timeout=1500)
                        if href:
                            link = f"https://www.sine.com.br{href}" if href.startswith("/") else href
                except Exception: pass

                vagas.append({
                    'id':         montar_id(titulo, empresa, plataforma),
                    'titulo':     titulo,
                    'empresa':    empresa,
                    'local':      CIDADE_UF,
                    'link':       link,
                    'plataforma': plataforma,
                    'match_vip':  checar_vip(texto)
                })
            except Exception:
                continue
    except Exception as e:
        log(f"   [{plataforma}] ❌ Erro: {e}")

    log(f"   [{plataforma}] {len(vagas)} vagas encontradas")
    return vagas


# ================================================================
# ORQUESTRADOR PRINCIPAL
# ================================================================

# Registro de todas as plataformas ativas
# Para desativar uma, basta comentar a linha
PLATAFORMAS = [
    buscar_no_indeed,
    buscar_no_gupy,
    buscar_no_vagas,
    buscar_no_catho,
    buscar_no_infojobs,
    buscar_no_sine,
]


def buscar_vagas():
    log("=" * 60)
    log("=== RASTREADOR DE VAGAS — FAGNER PEÇANHA ===")
    log(f"=== {len(PLATAFORMAS)} plataformas | {len(CARGOS)} cargos | Últimos 7 dias ===")
    log("=" * 60)
    init_db()

    novas_total = 0
    novas_vip   = 0
    resumo      = {}  # { plataforma: { 'novas': int, 'vip': int } }

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=False,
            args=["--start-maximized", "--disable-blink-features=AutomationControlled"]
        )
        context = browser.new_context(
            viewport={'width': 1366, 'height': 768},
            user_agent=(
                "Mozilla/5.0 (X11; Linux x86_64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/121.0.0.0 Safari/537.36"
            ),
            locale="pt-BR"
        )
        context.add_init_script(
            "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
        )
        page = context.new_page()

        # Itera: plataforma → cargo
        for fn_plataforma in PLATAFORMAS:
            nome_plataforma = fn_plataforma.__name__.replace("buscar_no_", "").replace("_", " ").title()
            log(f"\n{'─'*60}")
            log(f">>> PLATAFORMA: {nome_plataforma}")
            log(f"{'─'*60}")

            resumo[nome_plataforma] = {'novas': 0, 'vip': 0}

            for cargo in CARGOS:
                vagas = fn_plataforma(page, cargo)

                count = 0
                for vaga in vagas:
                    if count >= MAX_VAGAS_CARGO:
                        break
                    if not vaga_existe(vaga['id']):
                        if salvar_vaga(vaga):
                            novas_total += 1
                            resumo[nome_plataforma]['novas'] += 1
                            if vaga['match_vip']:
                                novas_vip += 1
                                resumo[nome_plataforma]['vip'] += 1
                            prefixo = "🔥 VIP" if vaga['match_vip'] else "✅ Nova"
                            log(f"   {prefixo}: {vaga['titulo']} | {vaga['empresa']}")
                            count += 1

                # Pausa entre cargos (comportamento humano)
                time.sleep(random.uniform(3, 6))

            # Pausa maior entre plataformas
            time.sleep(random.uniform(4, 7))

        browser.close()

    # ── RELATÓRIO FINAL ──
    log(f"\n{'='*60}")
    log("RELATÓRIO FINAL DA VARREDURA")
    log(f"{'='*60}")
    for plataforma, dados in resumo.items():
        log(f"  {plataforma:15s} → {dados['novas']:3d} novas  |  {dados['vip']:3d} VIP 🔥")
    log(f"{'─'*60}")
    log(f"  TOTAL          → {novas_total:3d} novas  |  {novas_vip:3d} VIP 🔥")
    log(f"{'='*60}")

    if novas_total > 0:
        notificar(novas_total, novas_vip)
    else:
        log("Nenhuma vaga nova encontrada nesta varredura.")


if __name__ == "__main__":
    buscar_vagas()

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
        page.goto(url, wait_until="domcontentloaded", timeout=30000)
        time.sleep(random.uniform(3, 5))
        fechar_popups(page)

        # Gupy é React — aguarda os cards renderizarem
        SELETORES_CARD = [
            '[data-testid="job-card"]',
            'div[class*="JobCard"]',
            'li[class*="JobCard"]',
            'article[class*="job"]',
        ]
        seletor_usado = None
        for sel in SELETORES_CARD:
            try:
                page.wait_for_selector(sel, timeout=8000)
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
                texto = card.inner_text(timeout=2000)
                linhas = [l.strip() for l in texto.split('\n') if l.strip()]
                if len(linhas) < 2: continue

                titulo  = linhas[0]
                empresa = linhas[1] if len(linhas) > 1 else "Não informada"

                # Tenta pegar link direto da vaga
                link = url
                try:
                    el = card.locator('a').first
                    if el.count():
                        href = el.get_attribute("href", timeout=1500)
                        if href:
                            link = f"https://portal.gupy.io{href}" if href.startswith("/") else href
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
# PLATAFORMA 3 — VAGAS.COM
# URL: vagas.com.br
# Forte cobertura regional — Grande ABC Paulista
# ================================================================
def buscar_no_vagas(page, cargo):
    plataforma = "Vagas.com"

    # Vagas.com usa slug no path: "analista-de-logistica"
    slug_cargo = urllib.parse.quote(cargo.lower().replace(" ", "-"))
    slug_cidade = "sao-bernardo-do-campo"

    url = f"https://www.vagas.com.br/vagas-de-{slug_cargo}-em-{slug_cidade}"
    log(f"   [{plataforma}] {cargo}")

    vagas = []
    try:
        page.goto(url, wait_until="domcontentloaded", timeout=30000)
        time.sleep(random.uniform(2, 4))
        fechar_popups(page)

        SELETOR = 'li.vaga'
        try:
            page.wait_for_selector(SELETOR, timeout=10000)
        except Exception:
            # Tenta seletor alternativo
            SELETOR = '.opportunity'
            try:
                page.wait_for_selector(SELETOR, timeout=5000)
            except Exception:
                log(f"   [{plataforma}] ⚠️ Sem cards — salvando debug")
                salvar_debug_html(page, f"debug_vagascom.html")
                return []

        for card in page.locator(SELETOR).all():
            try:
                titulo = ""
                for sel in ['h2.cargo a', 'a.link-detalhes-vaga', 'h2 a', '.cargo a']:
                    try:
                        el = card.locator(sel).first
                        if el.count():
                            titulo = el.inner_text(timeout=1500).strip()
                            if titulo: break
                    except Exception: pass
                if not titulo: continue

                empresa = "Não informada"
                for sel in ['span.empresa', '.empresa', '[class*="empresa"]']:
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
                try:
                    el = card.locator('a').first
                    if el.count():
                        href = el.get_attribute("href", timeout=1500)
                        if href:
                            link = f"https://www.vagas.com.br{href}" if href.startswith("/") else href
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
# Uma das maiores plataformas de empregos do Brasil
# ================================================================
def buscar_no_catho(page, cargo):
    plataforma = "Catho"
    url = (
        "https://www.catho.com.br/vagas/"
        f"?q={urllib.parse.quote(cargo)}"
        f"&l={urllib.parse.quote(CIDADE_UF)}"
        "&periodo=7"
    )
    log(f"   [{plataforma}] {cargo}")

    vagas = []
    try:
        page.goto(url, wait_until="domcontentloaded", timeout=30000)
        time.sleep(random.uniform(3, 5))
        fechar_popups(page)

        SELETORES_CARD = [
            '[data-testid="job-card"]',
            'article[class*="JobCard"]',
            'div[class*="JobCard"]',
            'li[class*="job-item"]',
            '.sc-job-listing',
        ]
        seletor_usado = None
        for sel in SELETORES_CARD:
            try:
                page.wait_for_selector(sel, timeout=8000)
                seletor_usado = sel
                break
            except Exception:
                pass

        if not seletor_usado:
            log(f"   [{plataforma}] ⚠️ Sem cards (pode precisar de login) — salvando debug")
            salvar_debug_html(page, f"debug_{plataforma.lower()}.html")
            return []

        for card in page.locator(seletor_usado).all():
            try:
                titulo = ""
                for sel in [
                    '[data-testid="job-title"]', 'h2 a', 'h3 a',
                    '[class*="title"] a', '[class*="Title"] a'
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
# ================================================================
def buscar_no_infojobs(page, cargo):
    plataforma = "InfoJobs"

    # InfoJobs usa slug no path
    slug = cargo.lower().replace(" ", "-")
    cidade_slug = "sao-bernardo-do-campo-sp"
    url = f"https://www.infojobs.com.br/vagas-de-emprego-{slug}-em-{cidade_slug}.aspx"
    log(f"   [{plataforma}] {cargo}")

    vagas = []
    try:
        page.goto(url, wait_until="domcontentloaded", timeout=30000)
        time.sleep(random.uniform(2, 4))
        fechar_popups(page)

        SELETORES_CARD = [
            'li[class*="offer"]',
            'li.offer-list-item',
            'article[class*="offer"]',
            '[class*="offer-item"]',
            '.vaga-item',
        ]
        seletor_usado = None
        for sel in SELETORES_CARD:
            try:
                page.wait_for_selector(sel, timeout=8000)
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
                for sel in ['h2 a', 'h3 a', '[class*="title"] a', 'a[class*="Title"]']:
                    try:
                        el = card.locator(sel).first
                        if el.count():
                            titulo = el.inner_text(timeout=1500).strip()
                            if titulo: break
                    except Exception: pass
                if not titulo: continue

                empresa = "Não informada"
                for sel in ['[class*="company"]', '[class*="empresa"]', 'span[class*="Company"]']:
                    try:
                        el = card.locator(sel).first
                        if el.count():
                            t = el.inner_text(timeout=1500).strip()
                            if t: empresa = t; break
                    except Exception: pass

                local_vaga = CIDADE_UF
                for sel in ['[class*="location"]', '[class*="localidade"]', '[class*="city"]']:
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
    except Exception as e:
        log(f"   [{plataforma}] ❌ Erro: {e}")

    log(f"   [{plataforma}] {len(vagas)} vagas encontradas")
    return vagas


# ================================================================
# PLATAFORMA 6 — SINE / EMPREGA BRASIL
# URL: empregabrasil.mte.gov.br
# Portal do Governo Federal — vagas formais registradas
# ================================================================
def buscar_no_sine(page, cargo):
    plataforma = "SINE"
    url = (
        "https://www.empregabrasil.mte.gov.br/76/procurar-emprego/"
        f"?q={urllib.parse.quote(cargo)}"
        "&municipio=sao-bernardo-do-campo&uf=SP"
    )
    log(f"   [{plataforma}] {cargo}")

    vagas = []
    try:
        page.goto(url, wait_until="domcontentloaded", timeout=30000)
        time.sleep(random.uniform(2, 4))
        fechar_popups(page)

        SELETORES_CARD = [
            '.vaga', 'li.resultado', 'div[class*="vaga"]',
            'article[class*="vaga"]', 'tr[class*="vaga"]',
        ]
        seletor_usado = None
        for sel in SELETORES_CARD:
            try:
                page.wait_for_selector(sel, timeout=8000)
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
                texto = card.inner_text(timeout=2000)
                linhas = [l.strip() for l in texto.split('\n') if l.strip()]
                if len(linhas) < 2: continue

                titulo  = linhas[0]
                empresa = linhas[1] if len(linhas) > 1 else "Não informada"

                link = url
                try:
                    el = card.locator('a').first
                    if el.count():
                        href = el.get_attribute("href", timeout=1500)
                        if href:
                            link = f"https://www.empregabrasil.mte.gov.br{href}" if href.startswith("/") else href
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

import sqlite3
import datetime
import time
import random
import subprocess
import urllib.parse
from playwright.sync_api import sync_playwright

# --- CONFIGURAÇÃO ESTRATÉGICA (FAGNER PEÇANHA) ---
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

LOCALIZACAO = "São Bernardo do Campo, SP"
DB_NAME = "vagas.db"
LOG_FILE = "execucao.log"

# Palavras que, se encontradas, marcam a vaga com fogo 🔥
KEYWORDS_VIP = [
    "JIT", "Lean", "Kaizen", "WMS", "SAP",
    "Automotiva", "Scania", "Ford", "Volkswagen", "Mercedes",
    "Kanban", "FIFO", "5S", "inventário", "estoque"
]

def init_db():
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS vagas (
            id TEXT PRIMARY KEY,
            titulo TEXT,
            empresa TEXT,
            local TEXT,
            link TEXT,
            data_encontrada DATETIME,
            match_vip BOOLEAN DEFAULT 0
        )
    ''')
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
            INSERT INTO vagas (id, titulo, empresa, local, link, data_encontrada, match_vip)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        ''', (
            vaga['id'], vaga['titulo'], vaga['empresa'], vaga['local'],
            vaga['link'], datetime.datetime.now(), vaga['match_vip']
        ))
        conn.commit()
        return True
    except sqlite3.IntegrityError:
        return False
    finally:
        conn.close()

def notificar(qtd_novas, qtd_vip):
    if qtd_novas == 0:
        return
    msg_titulo = "Rastreador de Vagas"
    msg_corpo = f"{qtd_novas} vagas recentes encontradas.\n{qtd_vip} são VIP!"
    urgencia = 'critical' if qtd_vip > 0 else 'normal'
    try:
        subprocess.run(['notify-send', msg_titulo, msg_corpo, '-u', urgencia], timeout=5)
    except Exception:
        pass  # notificação não é crítica

def log(mensagem):
    timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    linha = f"[{timestamp}] {mensagem}"
    print(linha)
    with open(LOG_FILE, "a") as f:
        f.write(linha + "\n")

# ============================================================
# ENGINE DE BUSCA — Indeed Brasil
# Fonte: br.indeed.com
# Motivo da troca: Google Jobs ativa anti-bot contra automação
# e o seletor div[role="treeitem"] captura filtros, não vagas.
# Indeed tem estrutura HTML estável + filtros de data e raio.
# ============================================================
def buscar_no_indeed(page, cargo):
    """
    Busca vagas no Indeed Brasil.
    - fromage=7  → últimos 7 dias
    - radius=10  → raio de 10km
    - sort=date  → mais recentes primeiro
    """
    vagas_encontradas = []

    # Codifica o cargo e localização corretamente para URL
    cargo_encoded = urllib.parse.quote(cargo)
    local_encoded = urllib.parse.quote(LOCALIZACAO)

    url = (
        f"https://br.indeed.com/jobs"
        f"?q={cargo_encoded}"
        f"&l={local_encoded}"
        f"&fromage=7"
        f"&radius=10"
        f"&sort=date"
    )

    log(f"🔎 Buscando: {cargo}")
    log(f"   URL: {url}")

    try:
        page.goto(url, wait_until="domcontentloaded", timeout=30000)
        time.sleep(random.uniform(3, 5))

        # Fecha popup de cookies/consentimento se aparecer
        for seletor_fechar in [
            'button[id*="onetrust-accept"]',
            'button[aria-label="fechar"]',
            'button:has-text("Aceitar")',
            'button:has-text("Concordar")',
        ]:
            try:
                btn = page.locator(seletor_fechar).first
                if btn.is_visible(timeout=2000):
                    btn.click()
                    time.sleep(1)
                    break
            except Exception:
                pass

        # Aguarda os cards de vagas carregarem
        # Seletores principais do Indeed Brasil (2025/2026)
        SELETOR_CARD = 'div.job_seen_beacon'
        SELETOR_CARD_ALT = 'li[class*="css-5lfssm"]'

        try:
            page.wait_for_selector(SELETOR_CARD, timeout=10000)
        except Exception:
            log(f"   ⚠️ Seletor principal não encontrou cards, tentando alternativo...")
            try:
                page.wait_for_selector(SELETOR_CARD_ALT, timeout=5000)
                SELETOR_CARD = SELETOR_CARD_ALT
            except Exception:
                log(f"   ❌ Nenhum card de vaga encontrado para: {cargo}")
                # Debug: salva o HTML da página para análise
                try:
                    html_debug = page.content()
                    with open("debug_pagina.html", "w", encoding="utf-8") as f:
                        f.write(html_debug)
                    log("   📄 HTML da página salvo em debug_pagina.html para análise")
                except Exception:
                    pass
                return []

        cards = page.locator(SELETOR_CARD).all()
        log(f"   Encontrados {len(cards)} cards de vagas na página")

        for card in cards:
            try:
                # --- Extrai TÍTULO ---
                titulo = ""
                for sel_titulo in [
                    '[data-testid="jobTitle"] span',
                    'h2.jobTitle span[title]',
                    'h2.jobTitle a span',
                    'a.jcs-JobTitle span',
                ]:
                    try:
                        el = card.locator(sel_titulo).first
                        if el.count() > 0:
                            titulo = el.inner_text(timeout=2000).strip()
                            if titulo:
                                break
                    except Exception:
                        pass

                if not titulo:
                    continue

                # --- Extrai EMPRESA ---
                empresa = "Empresa não informada"
                for sel_empresa in [
                    '[data-testid="company-name"]',
                    'span.companyName',
                    '[class*="companyName"]',
                ]:
                    try:
                        el = card.locator(sel_empresa).first
                        if el.count() > 0:
                            texto = el.inner_text(timeout=2000).strip()
                            if texto:
                                empresa = texto
                                break
                    except Exception:
                        pass

                # --- Extrai LOCALIZAÇÃO ---
                local_vaga = LOCALIZACAO
                for sel_local in [
                    '[data-testid="text-location"]',
                    'div.companyLocation',
                    '[class*="companyLocation"]',
                ]:
                    try:
                        el = card.locator(sel_local).first
                        if el.count() > 0:
                            texto = el.inner_text(timeout=2000).strip()
                            if texto:
                                local_vaga = texto
                                break
                    except Exception:
                        pass

                # --- Extrai LINK da vaga ---
                link_vaga = url
                for sel_link in [
                    'h2.jobTitle a',
                    'a.jcs-JobTitle',
                    '[data-testid="jobTitle"] a',
                ]:
                    try:
                        el = card.locator(sel_link).first
                        if el.count() > 0:
                            href = el.get_attribute("href", timeout=2000)
                            if href:
                                if href.startswith("/"):
                                    link_vaga = f"https://br.indeed.com{href}"
                                else:
                                    link_vaga = href
                                break
                    except Exception:
                        pass

                # --- Verifica palavras-chave VIP ---
                texto_completo = card.inner_text(timeout=3000).lower()
                match_vip = any(kw.lower() in texto_completo for kw in KEYWORDS_VIP)

                # ID único baseado em título + empresa (evita duplicatas)
                id_vaga = urllib.parse.quote(f"{titulo}-{empresa}".lower())[:200]

                vagas_encontradas.append({
                    'id': id_vaga,
                    'titulo': titulo,
                    'empresa': empresa,
                    'local': local_vaga,
                    'link': link_vaga,
                    'match_vip': match_vip
                })

            except Exception as e:
                # Silencia erros de card individual para não parar o loop
                continue

    except Exception as e:
        log(f"   ❌ Erro ao acessar Indeed para {cargo}: {e}")

    return vagas_encontradas


def buscar_vagas():
    log("=" * 55)
    log("=== INICIANDO VARREDURA (Indeed Brasil — 7 dias) ===")
    log("=" * 55)
    init_db()
    novas_total = 0
    novas_vip = 0

    with sync_playwright() as p:
        # headless=False: modo visual para evitar bloqueios anti-bot
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
        # Remove a flag "webdriver" que delata automação
        context.add_init_script(
            "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
        )
        page = context.new_page()

        for cargo in CARGOS:
            vagas = buscar_no_indeed(page, cargo)

            count_cargo = 0
            for vaga in vagas:
                if count_cargo >= 8:
                    break
                if not vaga_existe(vaga['id']):
                    if salvar_vaga(vaga):
                        novas_total += 1
                        if vaga['match_vip']:
                            novas_vip += 1
                        prefixo = "🔥 VIP" if vaga['match_vip'] else "✅ Nova"
                        log(f"   {prefixo}: {vaga['titulo']} | {vaga['empresa']}")
                        count_cargo += 1

            if count_cargo == 0 and vagas:
                log(f"   ℹ️  {len(vagas)} vagas encontradas, mas já estavam no banco.")

            # Pausa aleatória entre buscas (comportamento humano)
            pausa = random.uniform(5, 9)
            log(f"   ⏳ Aguardando {pausa:.1f}s antes da próxima busca...")
            time.sleep(pausa)

        browser.close()

    log("=" * 55)
    if novas_total > 0:
        notificar(novas_total, novas_vip)
        log(f"RESULTADO: {novas_total} vagas novas | {novas_vip} são VIP 🔥")
    else:
        log("RESULTADO: Nenhuma vaga nova encontrada.")
    log("=" * 55)


if __name__ == "__main__":
    buscar_vagas()

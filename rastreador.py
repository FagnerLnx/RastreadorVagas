import sqlite3
import datetime
import time
import random
import subprocess
import os
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

LOCALIZACAO = "São Bernardo do Campo"
DB_NAME = "vagas.db"
LOG_FILE = "execucao.log"

# Palavras que, se encontradas, marcam a vaga com fogo 🔥
KEYWORDS_VIP = ["JIT", "Lean", "Kaizen", "WMS", "SAP", "Automotiva", "Scania", "Ford", "Volkswagen", "Mercedes"]

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
        ''', (vaga['id'], vaga['titulo'], vaga['empresa'], vaga['local'], vaga['link'], datetime.datetime.now(), vaga['match_vip']))
        conn.commit()
        return True
    except sqlite3.IntegrityError:
        return False
    finally:
        conn.close()

def notificar(qtd_novas, qtd_vip):
    if qtd_novas == 0: return
    msg_titulo = "Rastreador de Vagas"
    msg_corpo = f"{qtd_novas} vagas recentes encontradas.\n{qtd_vip} são VIP!"
    urgencia = 'critical' if qtd_vip > 0 else 'normal'
    subprocess.run(['notify-send', msg_titulo, msg_corpo, '-u', urgencia])

def log(mensagem):
    timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{timestamp}] {mensagem}")
    with open(LOG_FILE, "a") as f:
        f.write(f"[{timestamp}] {mensagem}\n")

# --- ENGINE DE BUSCA ---
def buscar_vagas():
    log("=== INICIANDO VARREDURA (Últimos 7 dias) ===")
    init_db()
    novas_total = 0
    novas_vip = 0

    with sync_playwright() as p:
        # MODO VISUAL LIGADO PARA DEBUG
        browser = p.chromium.launch(headless=False, args=["--start-maximized"])
        context = browser.new_context(viewport={'width': 1920, 'height': 1080})
        page = context.new_page()

        for cargo in CARGOS:
            termo = f"{cargo} vagas {LOCALIZACAO}"
            
            # --- SEGREDO DA URL: ---
            # ibp=htl;jobs -> Ativa interface de jobs
            # htichips=date_posted:week -> Filtra últimos 7 dias
            url = f"https://www.google.com/search?q={termo}&ibp=htl;jobs&htichips=date_posted:week"
            
            log(f"🔎 Buscando: {cargo} (Recentes)")
            
            try:
                page.goto(url)
                
                # Delay inicial para você ver a página carregando
                time.sleep(5)

                # Tenta fechar popup de Login/Cookies se aparecer
                try:
                    botao_recusar = page.get_by_role("button", name="Agora não")
                    if botao_recusar.is_visible(): botao_recusar.click()
                except: pass

                # VERIFICAÇÃO VISUAL:
                # O Google Jobs carrega uma lista lateral esquerda.
                # Se não carregou, damos um tempo extra para você rolar a página ou clicar
                try:
                    page.wait_for_selector('div[role="treeitem"]', timeout=8000)
                except:
                    log(f"⚠️ A lista não carregou automático para {cargo}.")
                    log("👉 Se você ver um botão 'Vagas' ou 'Jobs', clique nele agora! Esperando 10s...")
                    time.sleep(10) # Tempo para intervenção humana

                # Coleta os blocos de vagas (role treeitem é o padrão atual do Google Jobs)
                elementos = page.locator('div[role="treeitem"]').all()

                if not elementos:
                    # Tenta seletor alternativo (lista simples)
                    elementos = page.locator("li").all()

                log(f"   Encontrados {len(elementos)} elementos potenciais na tela.")

                count_cargo = 0
                for el in elementos:
                    try:
                        texto = el.inner_text()
                        linhas = texto.split('\n')
                        
                        if len(linhas) < 2: continue

                        titulo = linhas[0]
                        # Tenta pegar empresa na segunda linha ou terceira
                        empresa = linhas[1] if len(linhas) > 1 else "Empresa Desconhecida"
                        
                        # Limpa lixo (ex: "há 2 dias" não é empresa)
                        if "há " in empresa or "via " in empresa:
                            if len(linhas) > 2: empresa = linhas[2]

                        match_vip = any(kw.lower() in texto.lower() for kw in KEYWORDS_VIP)
                        
                        id_vaga = f"{titulo}-{empresa}-{LOCALIZACAO}".replace(" ", "").lower()
                        
                        vaga = {
                            'id': id_vaga,
                            'titulo': titulo,
                            'empresa': empresa,
                            'local': LOCALIZACAO,
                            'link': url, # Salva o link da busca filtrada
                            'match_vip': match_vip
                        }

                        if not vaga_existe(id_vaga):
                            if salvar_vaga(vaga):
                                novas_total += 1
                                if match_vip: novas_vip += 1
                                prefixo = "🔥 VIP" if match_vip else "✅ Nova"
                                log(f"   {prefixo}: {titulo} | {empresa}")
                                count_cargo += 1
                        
                        if count_cargo >= 6: break # Top 6 por cargo

                    except Exception as e:
                        continue
            
            except Exception as e:
                log(f"❌ Erro em {cargo}: {e}")
            
            # Pausa aleatória entre pesquisas
            time.sleep(random.uniform(4, 7))

        browser.close()

    if novas_total > 0:
        notificar(novas_total, novas_vip)
        log(f"FIM: {novas_total} vagas novas adicionadas ao banco.")
    else:
        log("FIM: Nenhuma vaga nova (nos últimos 7 dias).")

if __name__ == "__main__":
    buscar_vagas()
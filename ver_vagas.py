import sqlite3
import datetime
import os
import sys
import pandas as pd

DB_NAME   = "vagas.db"
HTML_FILE = "vagas_exportadas.html"

# ================================================================
# QUERY BASE
# ================================================================
QUERY_COMPLETA = """
SELECT
    titulo      as 'Cargo',
    empresa     as 'Empresa',
    local       as 'Local',
    COALESCE(plataforma, '') as 'Fonte',
    link        as 'Link',
    match_vip   as 'VIP',
    datetime(data_encontrada, 'localtime') as 'Encontrada em'
FROM vagas
ORDER BY match_vip DESC, data_encontrada DESC
"""


def get_vagas(limit=100):
    conn = sqlite3.connect(DB_NAME)
    try:
        df = pd.read_sql_query(QUERY_COMPLETA + f"LIMIT {limit}", conn)
        return df
    finally:
        conn.close()


# ================================================================
# MODO 1 — Tabela resumida no terminal (padrão)
# ================================================================
def mostrar_relatorio():
    df = get_vagas(50)

    if df.empty:
        print("\n Nenhuma vaga encontrada no banco de dados ainda.")
        print("Execute: python rastreador.py")
        return

    total     = len(df)
    vip_count = df['VIP'].sum()

    print("\n" + "=" * 80)
    print(f"  RASTREADOR DE VAGAS — FAGNER PEÇANHA  |  {total} vagas  |  {vip_count} VIP")
    print("=" * 80)

    df_exibir = df[['Cargo', 'Empresa', 'Local', 'Fonte', 'Encontrada em']].copy()
    df_exibir.insert(0, '', df['VIP'].apply(lambda x: '>> VIP' if x else ''))

    pd.set_option('display.max_rows', None)
    pd.set_option('display.max_columns', None)
    pd.set_option('display.width', 220)
    pd.set_option('display.max_colwidth', 45)
    print(df_exibir.to_string(index=False))

    print("\n" + "─" * 80)

    if df['Fonte'].str.strip().any():
        print("\n  VAGAS POR PLATAFORMA:")
        resumo = df.groupby('Fonte').size().sort_values(ascending=False)
        for fonte, qtd in resumo.items():
            if fonte:
                print(f"    {fonte:15s} -> {qtd} vagas")

    print("\n  COMANDOS DISPONÍVEIS:")
    print("  python ver_vagas.py --links      → lista com links no terminal")
    print("  python ver_vagas.py --exportar   → gera vagas_exportadas.html (clicável)")
    print("  python ver_vagas.py --csv        → gera vagas_exportadas.csv (planilha)")
    print("=" * 80 + "\n")


# ================================================================
# MODO 2 — Links no terminal
# ================================================================
def mostrar_com_links():
    df = get_vagas(50)

    if df.empty:
        print("\n Nenhuma vaga no banco ainda. Execute: python rastreador.py")
        return

    total     = len(df)
    vip_count = df['VIP'].sum()

    print("\n" + "=" * 80)
    print(f"  VAGAS COM LINKS  |  {total} vagas  |  {vip_count} VIP")
    print("=" * 80)

    for _, row in df.iterrows():
        vip = "  [VIP]" if row['VIP'] else ""
        print(f"\n  {row['Cargo']}{vip}")
        print(f"  Empresa : {row['Empresa']}")
        print(f"  Fonte   : {row['Fonte']}")
        print(f"  Link    : {row['Link']}")
        print("  " + "─" * 60)

    print(f"\n  Total: {total} vagas  |  Para exportar: python ver_vagas.py --exportar\n")


# ================================================================
# MODO 3 — Exportar HTML com links clicáveis
# ================================================================
def exportar_html():
    df = get_vagas(200)

    if df.empty:
        print("\n Nenhuma vaga no banco. Execute: python rastreador.py")
        return

    total     = len(df)
    vip_count = int(df['VIP'].sum())
    gerado_em = datetime.datetime.now().strftime("%d/%m/%Y %H:%M")

    linhas_html = ""
    for _, row in df.iterrows():
        vip_class  = ' class="vip"' if row['VIP'] else ''
        vip_badge  = '<span class="badge">VIP</span> ' if row['VIP'] else ''
        empresa    = row['Empresa'] if row['Empresa'] else "Confidencial"
        fonte      = row['Fonte']   if row['Fonte']   else "—"
        local      = row['Local']   if row['Local']   else "—"
        link       = row['Link']    if row['Link']    else "#"
        encontrada = row['Encontrada em'] if row['Encontrada em'] else "—"

        linhas_html += f"""
        <tr{vip_class}>
            <td>{vip_badge}<a href="{link}" target="_blank">{row['Cargo']}</a></td>
            <td>{empresa}</td>
            <td>{local}</td>
            <td><span class="fonte">{fonte}</span></td>
            <td>{encontrada}</td>
            <td><a href="{link}" target="_blank" class="btn-candidatar">Candidatar</a></td>
        </tr>"""

    html = f"""<!DOCTYPE html>
<html lang="pt-BR">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Vagas — Fagner Peçanha</title>
<style>
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
         background: #0f172a; color: #e2e8f0; padding: 24px; }}
  h1   {{ font-size: 1.5rem; color: #f8fafc; margin-bottom: 4px; }}
  .sub {{ color: #94a3b8; font-size: 0.9rem; margin-bottom: 24px; }}
  .stats {{ display: flex; gap: 16px; margin-bottom: 20px; }}
  .stat {{ background: #1e293b; border-radius: 8px; padding: 12px 20px;
           border: 1px solid #334155; }}
  .stat .num {{ font-size: 1.6rem; font-weight: 700; color: #38bdf8; }}
  .stat .label {{ font-size: 0.75rem; color: #94a3b8; text-transform: uppercase; }}
  .stat.vip-stat .num {{ color: #f97316; }}
  table  {{ width: 100%; border-collapse: collapse; background: #1e293b;
            border-radius: 10px; overflow: hidden; }}
  thead  {{ background: #0f172a; }}
  th     {{ padding: 12px 14px; text-align: left; font-size: 0.75rem;
            color: #94a3b8; text-transform: uppercase; letter-spacing: 0.05em; }}
  td     {{ padding: 11px 14px; font-size: 0.875rem; border-bottom: 1px solid #1e3a5f20; }}
  tr:hover td {{ background: #263348; }}
  tr.vip td  {{ background: #1c1407; border-left: 3px solid #f97316; }}
  tr.vip:hover td {{ background: #2a1d0a; }}
  .badge {{ background: #f97316; color: #fff; font-size: 0.65rem; font-weight: 700;
            padding: 2px 6px; border-radius: 4px; margin-right: 4px;
            text-transform: uppercase; vertical-align: middle; }}
  a      {{ color: #38bdf8; text-decoration: none; }}
  a:hover {{ text-decoration: underline; }}
  .fonte {{ background: #1e3a5f; color: #7dd3fc; font-size: 0.75rem;
            padding: 2px 8px; border-radius: 12px; white-space: nowrap; }}
  .btn-candidatar {{ background: #0284c7; color: #fff !important; padding: 5px 12px;
                     border-radius: 6px; font-size: 0.8rem; white-space: nowrap; }}
  .btn-candidatar:hover {{ background: #0369a1; text-decoration: none !important; }}
  footer {{ text-align: center; margin-top: 20px; color: #475569; font-size: 0.8rem; }}
</style>
</head>
<body>
<h1>Rastreador de Vagas — Fagner Peçanha</h1>
<p class="sub">São Bernardo do Campo, SP &nbsp;·&nbsp; Gerado em {gerado_em}</p>

<div class="stats">
  <div class="stat">
    <div class="num">{total}</div>
    <div class="label">Vagas encontradas</div>
  </div>
  <div class="stat vip-stat">
    <div class="num">{vip_count}</div>
    <div class="label">Vagas VIP</div>
  </div>
</div>

<table>
  <thead>
    <tr>
      <th>Cargo</th>
      <th>Empresa</th>
      <th>Local</th>
      <th>Fonte</th>
      <th>Encontrada em</th>
      <th>Ação</th>
    </tr>
  </thead>
  <tbody>
    {linhas_html}
  </tbody>
</table>
<footer>Gerado automaticamente · python ver_vagas.py --exportar</footer>
</body>
</html>"""

    with open(HTML_FILE, "w", encoding="utf-8") as f:
        f.write(html)

    caminho = os.path.abspath(HTML_FILE)
    print(f"\n  HTML gerado com sucesso!")
    print(f"  Arquivo : {caminho}")
    print(f"  Vagas   : {total}  |  VIP: {vip_count}")
    print(f"\n  Abra no navegador:")
    print(f"  xdg-open {HTML_FILE}\n")


# ================================================================
# MODO 4 — Exportar CSV (planilha)
# ================================================================
def exportar_csv():
    df = get_vagas(200)

    if df.empty:
        print("\n Nenhuma vaga no banco. Execute: python rastreador.py")
        return

    csv_file = "vagas_exportadas.csv"
    df_csv = df[['Cargo', 'Empresa', 'Local', 'Fonte', 'Link', 'VIP', 'Encontrada em']].copy()
    df_csv['VIP'] = df_csv['VIP'].apply(lambda x: 'SIM' if x else '')
    df_csv.to_csv(csv_file, index=False, encoding='utf-8-sig')  # utf-8-sig para Excel/LibreOffice

    caminho = os.path.abspath(csv_file)
    print(f"\n  CSV gerado!")
    print(f"  Arquivo : {caminho}")
    print(f"  Vagas   : {len(df_csv)}")
    print(f"\n  Abra com:")
    print(f"  libreoffice --calc {csv_file}\n")


# ================================================================
# ENTRADA
# ================================================================
if __name__ == "__main__":
    args = sys.argv[1:]

    if "--exportar" in args or "--html" in args:
        exportar_html()
    elif "--csv" in args:
        exportar_csv()
    elif "--links" in args:
        mostrar_com_links()
    else:
        mostrar_relatorio()

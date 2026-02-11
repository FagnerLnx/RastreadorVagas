import sqlite3
import pandas as pd

DB_NAME = "vagas.db"

def mostrar_relatorio():
    conn = sqlite3.connect(DB_NAME)

    query = """
    SELECT
        CASE WHEN match_vip = 1 THEN '🔥' ELSE '  ' END as '',
        titulo      as 'Cargo',
        empresa     as 'Empresa',
        local       as 'Local',
        COALESCE(plataforma, '') as 'Fonte',
        datetime(data_encontrada, 'localtime') as 'Encontrada em'
    FROM vagas
    ORDER BY match_vip DESC, data_encontrada DESC
    LIMIT 50
    """

    try:
        df = pd.read_sql_query(query, conn)

        if df.empty:
            print("\n📭 Nenhuma vaga encontrada no banco de dados ainda.")
            print("Execute: python rastreador.py")
            return

        total     = len(df)
        vip_count = df[''].str.strip().eq('🔥').sum()

        print("\n" + "=" * 80)
        print(f"  RASTREADOR DE VAGAS — FAGNER PEÇANHA  |  {total} vagas  |  {vip_count} VIP 🔥")
        print("=" * 80)

        pd.set_option('display.max_rows', None)
        pd.set_option('display.max_columns', None)
        pd.set_option('display.width', 200)
        pd.set_option('display.max_colwidth', 45)
        print(df.to_string(index=False))

        print("\n" + "─" * 80)

        # Resumo por plataforma
        if 'Fonte' in df.columns and df['Fonte'].str.strip().any():
            print("\n  VAGAS POR PLATAFORMA:")
            resumo = df.groupby('Fonte').size().sort_values(ascending=False)
            for fonte, qtd in resumo.items():
                if fonte:
                    print(f"    {fonte:15s} → {qtd} vagas")

        print("\n  Para abrir o link de uma vaga, execute:")
        print("  python ver_vagas.py --links")
        print("=" * 80 + "\n")

    except Exception as e:
        print(f"Erro ao ler banco: {e}")
    finally:
        conn.close()


def mostrar_com_links():
    """Exibe as vagas com os links completos para candidatura."""
    conn = sqlite3.connect(DB_NAME)

    query = """
    SELECT
        titulo      as 'Cargo',
        empresa     as 'Empresa',
        COALESCE(plataforma, '') as 'Fonte',
        link        as 'Link',
        CASE WHEN match_vip = 1 THEN 'SIM' ELSE '' END as 'VIP'
    FROM vagas
    ORDER BY match_vip DESC, data_encontrada DESC
    LIMIT 50
    """

    try:
        df = pd.read_sql_query(query, conn)

        if df.empty:
            print("\n📭 Nenhuma vaga no banco ainda. Execute: python rastreador.py")
            return

        print("\n" + "=" * 80)
        print(f"  VAGAS COM LINKS — FAGNER PEÇANHA")
        print("=" * 80)

        for _, row in df.iterrows():
            vip = " 🔥 VIP" if row['VIP'] == 'SIM' else ""
            print(f"\n  {row['Cargo']}{vip}")
            print(f"  Empresa : {row['Empresa']}")
            print(f"  Fonte   : {row['Fonte']}")
            print(f"  Link    : {row['Link']}")
            print("  " + "─" * 60)

    except Exception as e:
        print(f"Erro ao ler banco: {e}")
    finally:
        conn.close()


if __name__ == "__main__":
    import sys
    if "--links" in sys.argv:
        mostrar_com_links()
    else:
        mostrar_relatorio()

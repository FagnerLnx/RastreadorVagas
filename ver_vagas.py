import sqlite3
import pandas as pd
import os

DB_NAME = "vagas.db"

def mostrar_relatorio():
    conn = sqlite3.connect(DB_NAME)
    
    # Query inteligente: Traz as vagas VIPs primeiro, depois as mais recentes
    query = """
    SELECT 
        titulo as 'Cargo', 
        empresa as 'Empresa', 
        CASE WHEN match_vip = 1 THEN 'SIM' ELSE '' END as 'CV Match',
        datetime(data_encontrada, 'localtime') as 'Data/Hora'
    FROM vagas 
    ORDER BY match_vip DESC, data_encontrada DESC 
    LIMIT 30
    """
    
    try:
        df = pd.read_sql_query(query, conn)
        
        if df.empty:
            print("\n📭 Nenhuma vaga encontrada no banco de dados ainda.")
            print("Execute: python rastreador.py")
        else:
            print("\n" + "="*60)
            print(f" RELATÓRIO DE VAGAS - FAGNER PEÇANHA (Top {len(df)})")
            print("="*60)
            # Formatação para caber na tela
            pd.set_option('display.max_rows', None)
            pd.set_option('display.max_columns', None)
            pd.set_option('display.width', 1000)
            print(df.to_string(index=False))
            print("\n" + "="*60 + "\n")
            
    except Exception as e:
        print(f"Erro ao ler banco: {e}")
    finally:
        conn.close()

if __name__ == "__main__":
    mostrar_relatorio()
import os
import glob
import random
import subprocess
import sys

# Configuração
BENCH_BINARY_PATH = "../../src/build/bench" 
SAMPLE_SIZE = 100

# Setup de diretório
debug_dir = "../job_join_trees"

# Carregamento de dados
def load_ground_truth(filename):
    lookup = {}
    name_to_mask = {}
    try:
        with open(filename, 'r') as f:
            lines = f.readlines()
        names = lines[1].strip().split()
        name_to_mask = {name: (1 << i) for i, name in enumerate(names)}
        for line in lines[3:]:
            parts = line.strip().split()
            if len(parts) >= 2:
                try:
                    lookup[int(parts[0])] = int(parts[1])
                except ValueError: continue
    except Exception:
        return None, None
    return name_to_mask, lookup

# Cálculo de custos
def calculate_costs(tree_str, name_to_mask, lookup):
    clean_str = tree_str.strip()
    if '|' not in clean_str:
        name = clean_str.replace('(', '').replace(')', '').strip()
        mask = name_to_mask.get(name, 0)
        card = lookup.get(mask, 1000)
        return card, 0, mask

    balance = 0
    split_idx = -1
    inner = clean_str[1:-1]
    for i, char in enumerate(inner):
        if char == '(': balance += 1
        elif char == ')': balance -= 1
        elif char == '|' and balance == 0:
            split_idx = i
            break
    
    if split_idx == -1: return 1000, 0, 0

    left = inner[:split_idx].strip()
    right = inner[split_idx+1:].strip()
    
    c_L, h_L, m_L = calculate_costs(left, name_to_mask, lookup)
    c_R, h_R, m_R = calculate_costs(right, name_to_mask, lookup)
    
    curr_mask = m_L | m_R
    curr_card = lookup.get(curr_mask, (c_L * c_R) * 0.01)
    curr_hash_cost = (1.2 * min(c_L, c_R)) + max(c_L, c_R)
    total_hash = h_L + h_R + curr_hash_cost
    
    return curr_card, total_hash, curr_mask

# Função de busca de arquivo robusta
def find_and_read_tree(filename_in_log):
    fname = os.path.basename(filename_in_log)
    
    # Lista de lugares onde ele pode estar
    candidates = [
        os.path.join(debug_dir, fname),           # Onde configuramos
        os.path.join("../job_join_trees", fname), # Vizinho
        os.path.join("../../job_join_trees", fname), # Raiz
        filename_in_log                           # Caminho original do log
    ]
    
    for path in candidates:
        if os.path.exists(path):
            try:
                with open(path, 'r') as f:
                    return f.read().strip()
            except: continue
            
    return None

# Motor de benchmark
def run_benchmark():
    all_files = glob.glob("*.csv")
    csv_files = [f for f in all_files if "validate" not in f and "bench" not in f and "cap-cout" not in f]
    
    if not csv_files:
        print("ERRO: Nenhum arquivo .csv encontrado na pasta atual.")
        return

    if not os.path.exists(BENCH_BINARY_PATH):
        print(f"ERRO CRÍTICO: Executável não encontrado em: {BENCH_BINARY_PATH}")
        return

    sample_files = random.sample(csv_files, min(SAMPLE_SIZE, len(csv_files)))
    print(f"--- Benchmark Comparativo Iniciado ({len(sample_files)} amostras) ---")
    
    results = []

    for i, csv_file in enumerate(sample_files):
        print(f"[{i+1}/{len(sample_files)}] Query: {csv_file}...", end=" ")
        
        name_map, lookup = load_ground_truth(csv_file)
        if not lookup: 
            print("Erro Metadados.")
            continue

        try:
            result = subprocess.run(
                [BENCH_BINARY_PATH, csv_file], 
                capture_output=True, 
                text=True, 
                timeout=30
            )
            output = result.stdout
        except:
            print("Timeout/Erro.")
            continue

        tree_cout = None
        tree_dpccp = None
        
        # Procura linhas com "Debug filename:"
        for line in output.split('\n'):
            if "Debug filename:" in line:
                path_in_log = line.split("Debug filename:")[1].strip()
                
                # Tenta achar o arquivo em qualquer lugar
                content = find_and_read_tree(path_in_log)
                
                if content:
                    if "cout" in path_in_log: tree_cout = content
                    elif "dpccp" in path_in_log: tree_dpccp = content
                    elif "cmax" in path_in_log and tree_dpccp is None: tree_dpccp = content

        if not tree_cout or not tree_dpccp:
            print("FALHA (Arquivos de árvore não encontrados)")
            continue

        _, cost_hash_dpconv, _ = calculate_costs(tree_cout, name_map, lookup)
        _, cost_hash_real, _ = calculate_costs(tree_dpccp, name_map, lookup)

        if cost_hash_real == 0: cost_hash_real = 1 
        diff_pct = ((cost_hash_dpconv - cost_hash_real) / cost_hash_real) * 100

        results.append({
            "Query": csv_file,
            "DPconv": cost_hash_dpconv,
            "DPccp": cost_hash_real,
            "Diff%": diff_pct
        })
        
        print(f"OK! Diff: {diff_pct:.2f}%")

    if not results: 
        print("\nNenhum resultado.")
        return

    print("\n" + "="*80)
    print(f"{'QUERY':<25} | {'DPconv(Aprox)':>15} | {'DPccp(Real)':>15} | {'PIORA %':>10}")
    print("-" * 80)
    
    wins = 0
    total_diff = 0
    for r in results:
        if r['Diff%'] <= 5.0: wins += 1
        total_diff += r['Diff%']
        print(f"{r['Query']:<25} | {r['DPconv']:>15,.0f} | {r['DPccp']:>15,.0f} | {r['Diff%']:>9.2f}%")
    
    print("="*80)
    print(f"RESUMO: A aproximação foi eficaz (<5% piora) em {wins}/{len(results)} casos.")
    print(f"Média Geral de Piora: {total_diff / len(results):.2f}%")

if __name__ == "__main__":
    run_benchmark()
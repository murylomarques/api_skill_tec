import requests
import logging
import urllib.parse
from typing import Dict, Optional, Any, List

# from sf_auth import get_salesforce_token, get_auth_headers

# Configuração do logging
logger = logging.getLogger("salesforce_api")

def execute_soql_query(
    instance_url: str,
    auth_headers: Dict,
    query: str,
    api_version: str = "v55.0",
    batch_size: Optional[int] = None
) -> Optional[Dict[str, Any]]:
    """
    Executa uma consulta SOQL no Salesforce.
    
    Args:
        instance_url: URL da instância do Salesforce (obtida após autenticação)
        auth_headers: Cabeçalhos de autorização (obtidos com get_auth_headers)
        query: Consulta SOQL a ser executada
        api_version: Versão da API do Salesforce
        batch_size: Tamanho do lote de resultados (opcional)
        
    Returns:
        Dicionário com os resultados da consulta ou None em caso de falha
    """
    try:
        # Codifica a consulta SOQL para URL
        encoded_query = urllib.parse.quote(query)
        
        # Constrói a URL da requisição
        url = f"{instance_url}/services/data/{api_version}/query/?q={encoded_query}"
        
        # Adiciona o cabeçalho de opções de consulta se batch_size for especificado
        headers = auth_headers.copy()
        if batch_size:
            headers["Sforce-Query-Options"] = f"batchSize={batch_size}"
        
        logger.info(f"Executando consulta SOQL: {query}")
        response = requests.get(url, headers=headers)
        
        if response.status_code == 200:
            result = response.json()
            logger.info(f"Consulta executada com sucesso. Total de registros: {result.get('totalSize', 0)}")
            return result
        else:
            logger.error(f"Falha na consulta: {response.status_code} - {response.text}")
            return None
            
    except Exception as e:
        logger.error(f"Erro ao executar consulta SOQL: {str(e)}")
        return None

def query_more_results(
    instance_url: str,
    auth_headers: Dict,
    next_records_url: str
) -> Optional[Dict[str, Any]]:
    """
    Obtém o próximo lote de resultados de uma consulta SOQL.
    
    Args:
        instance_url: URL da instância do Salesforce (obtida após autenticação)
        auth_headers: Cabeçalhos de autorização (obtidos com get_auth_headers)
        next_records_url: URL para o próximo lote de resultados (obtido do campo nextRecordsUrl)
        
    Returns:
        Dicionário com o próximo lote de resultados ou None em caso de falha
    """
    try:
        # Constrói a URL completa para o próximo lote
        url = f"{instance_url}{next_records_url}"
        
        logger.info("Obtendo próximo lote de resultados")
        response = requests.get(url, headers=auth_headers)
        
        if response.status_code == 200:
            result = response.json()
            logger.info(f"Próximo lote obtido com sucesso. Registros neste lote: {len(result.get('records', []))}")
            return result
        else:
            logger.error(f"Falha ao obter próximo lote: {response.status_code} - {response.text}")
            return None
            
    except Exception as e:
        logger.error(f"Erro ao obter próximo lote de resultados: {str(e)}")
        return None

def get_all_query_results(
    instance_url: str,
    auth_headers: Dict,
    query: str,
    api_version: str = "v55.0",
    batch_size: Optional[int] = None
) -> List[Dict[str, Any]]:
    """
    Executa uma consulta SOQL e obtém todos os resultados, lidando automaticamente com paginação.
    
    Args:
        instance_url: URL da instância do Salesforce (obtida após autenticação)
        auth_headers: Cabeçalhos de autorização (obtidos com get_auth_headers)
        query: Consulta SOQL a ser executada
        api_version: Versão da API do Salesforce
        batch_size: Tamanho do lote de resultados (opcional)
        
    Returns:
        Lista com todos os registros retornados pela consulta
    """
    all_records = []
    
    # Executa a consulta inicial
    result = execute_soql_query(instance_url, auth_headers, query, api_version, batch_size)
    
    if not result:
        logger.error("Falha ao executar consulta inicial")
        return all_records
    
    # Adiciona os registros do primeiro lote
    all_records.extend(result.get("records", []))
    
    # Continua obtendo resultados enquanto houver mais lotes
    while not result.get("done", True):
        next_records_url = result.get("nextRecordsUrl")
        if not next_records_url:
            logger.warning("Campo nextRecordsUrl não encontrado, mas done=False")
            break
            
        result = query_more_results(instance_url, auth_headers, next_records_url)
        
        if not result:
            logger.error("Falha ao obter próximo lote de resultados")
            break
            
        all_records.extend(result.get("records", []))
    
    logger.info(f"Consulta completa. Total de registros obtidos: {len(all_records)}")
    return all_records

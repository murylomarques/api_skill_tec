import requests
import logging
from typing import Dict, Optional

# Configuração do logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger("salesforce_api")

def get_salesforce_token(
    domain: str,
    client_id: str,
    client_secret: str,
    username: str,
    password: str,
    grant_type: str = "password"
) -> Optional[Dict]:
    """
    Obtém um token OAuth2 do Salesforce usando o fluxo de senha.
    
    Args:
        domain: Domínio do Salesforce (ex: https://login.salesforce.com)
        client_id: ID do cliente (Consumer Key)
        client_secret: Secret do cliente (Consumer Secret)
        username: Nome de usuário do Salesforce
        password: Senha do Salesforce
        grant_type: Tipo de concessão OAuth2 (padrão: password)
        
    Returns:
        Dicionário contendo o token de acesso e outras informações, ou None em caso de falha
    """
    try:
        url = f"{domain}/services/oauth2/token"
        
        payload = {
            'grant_type': grant_type,
            'client_id': client_id,
            'client_secret': client_secret,
            'username': username,
            'password': password
        }
        
        headers = {
            'Content-Type': 'application/x-www-form-urlencoded'
        }
        
        logger.info(f"Realizando autenticação no Salesforce: {domain}")
        response = requests.post(url, data=payload, headers=headers, verify=False)
        
        if response.status_code == 200:
            token_data = response.json()
            logger.info("Autenticação realizada com sucesso")
            return token_data
        else:
            logger.error(f"Falha na autenticação: {response.status_code} - {response.text}")
            return None
            
    except Exception as e:
        logger.error(f"Erro ao obter token: {str(e)}")
        return None

def get_auth_headers(token_data: Dict) -> Dict:
    """
    Cria os cabeçalhos de autorização para as requisições à API do Salesforce.
    
    Args:
        token_data: Dados do token retornados pela função get_salesforce_token
        
    Returns:
        Dicionário com os cabeçalhos de autorização
    """
    if not token_data or 'access_token' not in token_data:
        logger.error("Dados do token inválidos")
        return {}
        
    headers = {
        'Authorization': f"Bearer {token_data['access_token']}"
    }
    return headers


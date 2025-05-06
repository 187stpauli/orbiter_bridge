import json
import aiohttp
import asyncio
from eth_utils import to_checksum_address
from client.client import Client
from utils.logger import logger
from utils.error_handler import handle_errors, safe_request


@safe_request(max_attempts=3)
async def get_quote(client, from_chain_id, to_chain_id, amount):
    """
    Получает котировку для обмена токенов через Orbiter Finance.
    
    Args:
        client: Web3 клиент для взаимодействия с блокчейном
        from_chain_id: ID исходной сети
        to_chain_id: ID целевой сети
        amount: Количество токенов в wei для обмена
        
    Returns:
        dict: Данные о котировке и параметрах транзакции
        
    Raises:
        Exception: При ошибке получения котировки
    """
    try:
        async def find_in_list(key, value, _list):
            for _dict in _list:
                if _dict[key] == str(value):
                    return _dict
            return None

        with open("abi/chains.json", "r", encoding="utf-8") as f:
            networks = json.load(f)
        networks = networks["result"]

        from_data = await find_in_list("chainId", from_chain_id, networks)
        to_data = await find_in_list("chainId", to_chain_id, networks)
        
        if not from_data:
            raise ValueError(f"Сеть с chainId {from_chain_id} не найдена в списке поддерживаемых")
        if not to_data:
            raise ValueError(f"Сеть с chainId {to_chain_id} не найдена в списке поддерживаемых")
            
        tokens = to_data["tokens"]
        dest_token = await find_in_list("symbol", "DAI", tokens)
        
        if not dest_token:
            dest_token = tokens[0]  # Берем первый доступный токен если DAI не найден
            logger.warning(f"DAI не найден в сети назначения, используем {dest_token['symbol']} вместо него")
            
        dest_token = dest_token["address"]

        url = "https://api.orbiter.finance/sdk/swap/quote"

        headers = {
            "Accept": "*/*",
            "Content-Type": "application/json",
            "Origin": "https://www.orbiter.finance",
            "Referer": "https://www.orbiter.finance/",
            "priority": "u=1,i",
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/135.0.0.0 Safari/537.36"
            ),
            "Host": "api.orbiter.finance"
        }

        payload = {
            "sourceChainId": str(from_chain_id),
            "destChainId": str(to_chain_id),
            "sourceToken": str(from_data['nativeCurrency']['address']),
            "destToken": str(to_checksum_address(dest_token)),
            "amount": str(amount),
            "userAddress": str(client.address),
            "targetRecipient": str(client.address),
            "slippage": 0.001
        }

        cache_key = f"{from_chain_id}_{to_chain_id}_{amount}_{client.address}"
        if hasattr(get_quote, "cache") and cache_key in get_quote.cache:
            logger.info("Используем кэшированные данные для котировки")
            return get_quote.cache[cache_key]

        async with aiohttp.ClientSession(headers=headers) as session:
            async with session.post(url, json=payload) as response:
                if response.status != 200:
                    error_text = await response.text()
                    raise Exception(f"API вернул ошибку: {response.status}, {error_text}")
                
                response_data = await response.json()
                
                if not hasattr(get_quote, "cache"):
                    get_quote.cache = {}
                get_quote.cache[cache_key] = response_data
                
                return response_data
                
    except Exception as e:
        logger.error(f"Ошибка при получении котировки: {e}")
        raise


@handle_errors(retry_count=12, sleep_time=10, backoff_factor=1.0, log_prefix="Orbiter status")
async def wait_orbiter_status(tx_hash: str, timeout: int = 120, interval: int = 10) -> bool:
    """
    Ожидает завершения транзакции бриджинга на стороне Orbiter Finance.
    
    Args:
        tx_hash: Хеш транзакции
        timeout: Максимальное время ожидания в секундах
        interval: Интервал между проверками в секундах
        
    Returns:
        bool: True если транзакция успешно выполнена, False в противном случае
    """
    url = f"https://api.orbiter.finance/sdk/transaction/status/{tx_hash}"
    headers = {
        "x-forwarded-for": "127.0.0.1",
        "x-real-ip": "127.0.0.1",
        "client": "Python Script",
        "Accept": "*/*",
    }

    elapsed = 0

    async with aiohttp.ClientSession() as session:
        async with session.get(url, headers=headers) as response:
            if response.status != 200:
                logger.warning(f"Orbiter API вернул статус {response.status}")
                text = await response.text()
                logger.debug(f"Ответ API: {text}")
                raise Exception(f"Ошибка API: {response.status}")
            
            data = await response.json()
            status = data.get("status")

            if status == "success":
                logger.info("✅ Средства успешно доставлены в целевую сеть!\n")
                return True
            elif status == "pending":
                logger.info("⏳ Транзакция все еще в процессе обработки...")
                raise Exception("Транзакция в статусе pending")
            elif status == "failed":
                logger.error(f"❌ Транзакция не удалась: {data.get('message', 'Неизвестная ошибка')}")
                return False
            else:
                logger.warning(f"⚠️ Неизвестный статус транзакции: {status}")
                raise Exception(f"Неизвестный статус: {status}")


async def execute_bridge(client: Client, amount_in: int, from_network: dict, to_network: dict) -> bool:
    """
    Выполняет бридж токенов через Orbiter Finance.
    
    Args:
        client: Web3 клиент для взаимодействия с блокчейном
        amount_in: Количество нативных токенов в wei для отправки
        from_network: Информация о сети отправления
        to_network: Информация о сети получения
        
    Returns:
        bool: True если бридж успешен, False в случае ошибки
    """
    try:
        logger.info(f"🔄 Выполняем бридж {await client.from_wei_main(amount_in)} ETH из сети {from_network['name']} в сеть {to_network['name']}...")
        
        logger.info("🔍 Получаем котировку от Orbiter Finance...")
        quote = await get_quote(client, from_network["chain_id"], to_network["chain_id"], amount_in)
        
        if not quote or "result" not in quote:
            logger.error(f"❌ Не удалось получить котировку от Orbiter Finance: {quote}")
            return False
            
        if "error" in quote and quote["error"]:
            logger.error(f"❌ Orbiter вернул ошибку: {quote['error']}")
            return False

        data = quote["result"]["steps"][0]["tx"]["data"]
        to = to_checksum_address(quote["result"]["steps"][0]["tx"]["to"])
        gas_limit = int(quote["result"]["steps"][0]["tx"]["gasLimit"])
        
        logger.info(f"💸 Подготовка транзакции бриджа с amount_in={await client.from_wei_main(amount_in)} ETH, gas_limit={gas_limit}")

        tx = await client.prepare_tx(amount_in, to, data)
        tx_hash = await client.sign_and_send_tx(tx, external_gas=gas_limit)
        
        if not tx_hash:
            logger.error("❌ Не удалось отправить транзакцию")
            return False
            
        tx_success = await client.wait_tx(tx_hash, client.explorer_url)
        if not tx_success:
            logger.error("❌ Транзакция не подтверждена в блокчейне")
            return False
        
        logger.info("🔍 Проверяем статус бриджа на стороне Orbiter...")
        bridge_success = await wait_orbiter_status(tx_hash)
        
        return bridge_success

    except Exception as e:
        logger.error(f"❌ Ошибка при выполнении бриджа: {e}")
        return False

import json
import aiohttp
from eth_utils import to_checksum_address
from client.client import Client
from utils.logger import logger


async def extract_extdata(data: str) -> bytes:
    # Убираем "0x"
    clean_data = data[2:] if data.startswith("0x") else data

    # Ищем начало строковой части extData (обычно b7743d или просто 743d)

    index = clean_data.find("743d")
    if index == -1:
        raise ValueError("extData string part не найдена!")

    string_data_hex = clean_data[index:]

    # Теперь конвертируем только строковую часть
    string_data_bytes = bytes.fromhex(string_data_hex)
    string_data = string_data_bytes.decode("utf-8").rstrip("\x00")

    # Возвращаем как bytes (чистая строка в байтах)
    return string_data.encode("utf-8")


async def get_quote(client, from_chain_id, to_chain_id, amount):
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
        tokens = to_data["tokens"]
        dest_token = await find_in_list("symbol", "DAI", tokens)
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

        async with aiohttp.ClientSession(headers=headers) as session:
            async with session.post(url, json=payload) as response:
                response_data = await response.json()
                return response_data, from_data
    except Exception as e:
        logger.error(f"{e}")


async def execute_bridge(client: Client, service_address: str, amount_in: int, from_network: dict, to_network: dict,
                         aggregator_abi):
    logger.info("⚙️ Подготовка транзакции...\n")
    try:
        quote, from_data = await get_quote(client, from_network["chain_id"], to_network["chain_id"], amount_in)
        data = quote["result"]["steps"][0]["tx"]
        ext_data = data["data"]
        ext_data = await extract_extdata(ext_data)

        params = (
            service_address,  # recipient
            str(from_data['nativeCurrency']['address']),  # inputToken
            int(amount_in),  # inputAmount
            "Orbiter",  # dApp
            ext_data,  # extData
            False  # unwrapped
        )
        print(params)
        aggregator = to_checksum_address(data["to"])

        contract = client.w3.eth.contract(aggregator, abi=aggregator_abi)
        # Симуляция call
        tx = await contract.functions.executeBridge(params).build_transaction(await client.prepare_tx(amount_in))
        print("Result:", tx)
        exit(1)
        # tx = contract.functions.executeBridge(bridge_data)
    except Exception as e:
        logger.error(f"{e}")

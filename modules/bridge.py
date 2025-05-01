import json
import aiohttp
import asyncio
from eth_utils import to_checksum_address
from client.client import Client
from utils.logger import logger


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
                return response_data
    except Exception as e:
        logger.error(f"{e}")


async def wait_orbiter_status(tx_hash: str, timeout: int = 120, interval: int = 10) -> bool:
    url = f"https://api.orbiter.finance/sdk/transaction/status/{tx_hash}"
    headers = {
        "x-forwarded-for": "127.0.0.1",
        "x-real-ip": "127.0.0.1",
        "client": "Python Script",
        "Accept": "*/*",
    }

    elapsed = 0

    while elapsed < timeout:
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, headers=headers) as response:
                    if response.status != 200:
                        logger.warning(f"Orbiter API вернул статус {response.status}")
                    else:
                        data = await response.json()
                        status = data.get("status")

                        if status == "success":
                            logger.info("✅ Средства успешно доставлены в целевую сеть!\n")
                            return True

        except Exception as e:
            logger.error(f"❗️ Ошибка при запросе статуса Orbiter: {e}")

        # Ждём перед следующей проверкой
        await asyncio.sleep(interval)
        elapsed += interval

    # Если сюда дошли → значит таймаут
    logger.error("❌ Средства не дошли в целевую сеть за отведённое время (2 минуты)")
    return False


async def execute_bridge(client: Client, amount_in: int, from_network: dict, to_network: dict):

    try:
        quote = await get_quote(client, from_network["chain_id"], to_network["chain_id"], amount_in)

        data = quote["result"]["steps"][0]["tx"]["data"]
        to = to_checksum_address(quote["result"]["steps"][0]["tx"]["to"])
        gas_limit = int(quote["result"]["steps"][0]["tx"]["gasLimit"])

        tx = await client.prepare_tx(amount_in, to, data)
        tx_hash = await client.sign_and_send_tx(tx, external_gas=gas_limit)
        await client.wait_tx(tx_hash, client.explorer_url)
        await wait_orbiter_status(tx_hash)

    except Exception as e:
        logger.error(f"{e}")

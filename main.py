from eth_utils import to_checksum_address
from config.configvalidator import ConfigValidator
from client.client import Client
from modules.bridge import execute_bridge
from utils.logger import logger
import asyncio
import json

with open("abi/aggregator_abi.json", "r", encoding="utf-8") as f:
    AGGREGATOR_ABI = json.load(f)

with open("abi/erc20_abi.json", "r", encoding="utf-8") as f:
    ERC20_ABI = json.load(f)

SERVICE_ADDRESS = "0xa383A72e000C056ccEaa9305B7B5d2D90887fbFd"

ZERO_ADDRESS = "0x0000000000000000000000000000000000000000"


async def main():
    try:
        logger.info("🚀 Запуск скрипта...\n")
        # Загрузка параметров
        logger.info("⚙️ Загрузка и валидация параметров...\n")
        validator = ConfigValidator("config/settings.json")
        settings = await validator.validate_config()

        with open("constants/networks_data.json", "r", encoding="utf-8") as file:
            networks_data = json.load(file)

        from_network = networks_data[settings["from_network"]]
        to_network = networks_data[settings["to_network"]]

        client = Client(
            proxy=settings["proxy"],
            rpc_url=from_network["rpc_url"],
            chain_id=from_network["chain_id"],
            amount=float(settings["amount"]),
            private_key=settings["private_key"],
            internal_id=to_network["internal_id"],
            explorer_url=from_network["explorer_url"]
        )

        # Проверка баланса
        amount_in = await client.to_wei_main(client.amount)
        native_balance = await client.get_native_balance()
        gas = await client.get_tx_fee()
        total_cost = amount_in + gas
        if total_cost > native_balance:
            logger.error(f"Недостаточно баланса! Требуется: {await client.from_wei_main(amount_in):.8f}"
                         f" фактический баланс: {await client.from_wei_main(native_balance):.8f}\n")
            exit(1)

        await execute_bridge(client, SERVICE_ADDRESS, amount_in, from_network, to_network, AGGREGATOR_ABI)
        exit(1)
        logger.info("⚙️ Собираем и подписываем транзакцию...\n")
        tx = await router.functions.transfer(to_checksum_address(SERVICE_ADDRESS), b'').build_transaction(
            await client.prepare_tx(0))

        tx_hash = await client.sign_and_send_tx(tx)

        await client.wait_tx(tx_hash, client.explorer_url)

    except Exception as e:
        logger.error(f"Произошла ошибка в основном пути: {e}")


if __name__ == "__main__":
    asyncio.run(main())

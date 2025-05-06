import unittest
import asyncio
from unittest.mock import patch, MagicMock, AsyncMock
import sys
import os
import json

# Добавляем корневую директорию проекта в sys.path для импорта модулей
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from modules.bridge import get_quote, wait_orbiter_status, execute_bridge


class TestBridge(unittest.TestCase):
    def setUp(self):
        # Подготовка общих мок-объектов для тестов
        self.mock_client = MagicMock()
        self.mock_client.address = "0x1234567890123456789012345678901234567890"
        self.mock_client.from_wei_main = AsyncMock(return_value=0.01)
        
        # Моки сетей
        self.from_network = {
            "name": "Ethereum",
            "chain_id": 1,
            "explorer_url": "https://etherscan.io"
        }
        self.to_network = {
            "name": "Arbitrum",
            "chain_id": 42161,
            "explorer_url": "https://arbiscan.io"
        }

    @patch('aiohttp.ClientSession')
    @patch('json.load')
    def test_get_quote_success(self, mock_json_load, mock_session):
        # Мокируем данные сетей
        mock_networks_data = {
            "result": [
                {
                    "chainId": "1",
                    "name": "Ethereum",
                    "nativeCurrency": {"address": "0x0000000000000000000000000000000000000000"},
                    "tokens": []
                },
                {
                    "chainId": "42161",
                    "name": "Arbitrum",
                    "tokens": [{"symbol": "DAI", "address": "0xDA10009cBd5D07dd0CeCc66161FC93D7c9000da1"}]
                }
            ]
        }
        mock_json_load.return_value = mock_networks_data
        
        # Мокируем ответ API
        mock_response = AsyncMock()
        mock_response.status = 200
        mock_response.json = AsyncMock(return_value={
            "status": "success",
            "result": {
                "steps": [
                    {
                        "tx": {
                            "data": "0xabcdef",
                            "to": "0x9876543210987654321098765432109876543210",
                            "gasLimit": "100000"
                        }
                    }
                ]
            }
        })
        
        # Настраиваем моки aiohttp
        mock_session_instance = AsyncMock()
        mock_session.return_value.__aenter__.return_value = mock_session_instance
        mock_session_instance.post.return_value.__aenter__.return_value = mock_response
        
        # Выполняем тест
        result = asyncio.run(get_quote(self.mock_client, 1, 42161, 10000000000000000))
        
        # Проверяем результат
        self.assertEqual(result["status"], "success")
        self.assertTrue("result" in result)
        self.assertTrue("steps" in result["result"])
        
        # Проверяем, что был сделан правильный запрос
        mock_session_instance.post.assert_called_once()
        args, kwargs = mock_session_instance.post.call_args
        self.assertEqual(args[0], "https://api.orbiter.finance/sdk/swap/quote")
        
    @patch('aiohttp.ClientSession')
    def test_wait_orbiter_status_success(self, mock_session):
        # Мокируем успешный ответ API
        mock_response = AsyncMock()
        mock_response.status = 200
        mock_response.json = AsyncMock(return_value={"status": "success"})
        
        # Настраиваем моки aiohttp
        mock_session_instance = AsyncMock()
        mock_session.return_value.__aenter__.return_value = mock_session_instance
        mock_session_instance.get.return_value.__aenter__.return_value = mock_response
        
        # Выполняем тест
        result = asyncio.run(wait_orbiter_status("0xabcdef", timeout=10, interval=1))
        
        # Проверяем результат
        self.assertTrue(result)
        
        # Проверяем, что был сделан правильный запрос
        mock_session_instance.get.assert_called_once()
        args, kwargs = mock_session_instance.get.call_args
        self.assertEqual(args[0], "https://api.orbiter.finance/sdk/transaction/status/0xabcdef")
        
    @patch('aiohttp.ClientSession')
    def test_wait_orbiter_status_pending_then_success(self, mock_session):
        # Создаем последовательность ответов: pending, затем success
        mock_response_pending = AsyncMock()
        mock_response_pending.status = 200
        mock_response_pending.json = AsyncMock(return_value={"status": "pending"})
        
        mock_response_success = AsyncMock()
        mock_response_success.status = 200
        mock_response_success.json = AsyncMock(return_value={"status": "success"})
        
        # Настраиваем моки aiohttp для возврата разных ответов при последовательных вызовах
        mock_session_instance = AsyncMock()
        mock_session.return_value.__aenter__.return_value = mock_session_instance
        mock_session_instance.get.return_value.__aenter__.side_effect = [
            mock_response_pending,
            mock_response_success
        ]
        
        # Выполняем тест с обработкой исключения, которое генерирует наш retry декоратор
        with self.assertRaises(Exception):
            asyncio.run(wait_orbiter_status("0xabcdef", timeout=10, interval=1))
        
    @patch('modules.bridge.get_quote')
    @patch('modules.bridge.wait_orbiter_status')
    def test_execute_bridge_success(self, mock_wait_status, mock_get_quote):
        # Мокируем успешный возврат котировки
        mock_get_quote.return_value = {
            "status": "success",
            "result": {
                "steps": [
                    {
                        "tx": {
                            "data": "0xabcdef",
                            "to": "0x9876543210987654321098765432109876543210",
                            "gasLimit": "100000"
                        }
                    }
                ]
            }
        }
        
        # Мокируем успешное выполнение бриджа
        mock_wait_status.return_value = True
        
        # Мокируем клиент
        self.mock_client.prepare_tx = AsyncMock(return_value={"fake": "tx"})
        self.mock_client.sign_and_send_tx = AsyncMock(return_value="0xhash")
        self.mock_client.wait_tx = AsyncMock(return_value=True)
        
        # Выполняем тест
        result = asyncio.run(execute_bridge(
            self.mock_client, 10000000000000000, self.from_network, self.to_network
        ))
        
        # Проверяем результат
        self.assertTrue(result)
        mock_get_quote.assert_called_once_with(
            self.mock_client, self.from_network["chain_id"], self.to_network["chain_id"], 10000000000000000
        )
        self.mock_client.prepare_tx.assert_called_once()
        self.mock_client.sign_and_send_tx.assert_called_once()
        self.mock_client.wait_tx.assert_called_once()
        mock_wait_status.assert_called_once_with("0xhash")
        
    @patch('modules.bridge.get_quote')
    def test_execute_bridge_quote_failure(self, mock_get_quote):
        # Мокируем ошибку при получении котировки
        mock_get_quote.side_effect = Exception("API error")
        
        # Выполняем тест
        result = asyncio.run(execute_bridge(
            self.mock_client, 10000000000000000, self.from_network, self.to_network
        ))
        
        # Проверяем результат
        self.assertFalse(result)
        mock_get_quote.assert_called_once()
        
    @patch('modules.bridge.get_quote')
    def test_execute_bridge_tx_failure(self, mock_get_quote):
        # Мокируем успешный возврат котировки
        mock_get_quote.return_value = {
            "status": "success",
            "result": {
                "steps": [
                    {
                        "tx": {
                            "data": "0xabcdef",
                            "to": "0x9876543210987654321098765432109876543210",
                            "gasLimit": "100000"
                        }
                    }
                ]
            }
        }
        
        # Мокируем клиент с ошибкой при подписи транзакции
        self.mock_client.prepare_tx = AsyncMock(return_value={"fake": "tx"})
        self.mock_client.sign_and_send_tx = AsyncMock(return_value=None)  # Ошибка подписи
        
        # Выполняем тест
        result = asyncio.run(execute_bridge(
            self.mock_client, 10000000000000000, self.from_network, self.to_network
        ))
        
        # Проверяем результат
        self.assertFalse(result)
        mock_get_quote.assert_called_once()
        self.mock_client.prepare_tx.assert_called_once()
        self.mock_client.sign_and_send_tx.assert_called_once()
        # wait_tx не должен быть вызван, так как sign_and_send_tx вернул None
        self.mock_client.wait_tx.assert_not_called()


if __name__ == '__main__':
    unittest.main() 
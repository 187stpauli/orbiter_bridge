import asyncio
import logging
from functools import wraps
from typing import Type, Optional, Callable, Any, Union, List, Tuple

logger = logging.getLogger(__name__)


def handle_errors(
    exceptions: Union[Type[Exception], List[Type[Exception]]] = Exception,
    retry_count: int = 3,
    sleep_time: float = 1.0,
    backoff_factor: float = 1.5,
    fallback_function: Optional[Callable] = None,
    log_prefix: str = ""
):
    """
    Декоратор для обработки исключений с механизмом повторных попыток.
    
    Args:
        exceptions: Тип исключения или список типов исключений для перехвата
        retry_count: Максимальное количество повторных попыток
        sleep_time: Начальное время ожидания между попытками в секундах
        backoff_factor: Множитель увеличения времени ожидания между попытками
        fallback_function: Функция, которая будет вызвана если все попытки не удались
        log_prefix: Префикс для сообщений логгера
    
    Returns:
        Декоратор, который оборачивает функцию механизмом обработки ошибок
    """
    
    if isinstance(exceptions, type) and issubclass(exceptions, Exception):
        exceptions = [exceptions]
    
    def decorator(func):
        @wraps(func)
        async def async_wrapper(*args, **kwargs):
            attempt = 0
            current_sleep = sleep_time
            last_exception = None
            
            while attempt < retry_count:
                try:
                    return await func(*args, **kwargs)
                except tuple(exceptions) as e:
                    attempt += 1
                    last_exception = e
                    
                    prefix = f"{log_prefix} " if log_prefix else ""
                    if attempt < retry_count:
                        logger.warning(
                            f"{prefix}Попытка {attempt}/{retry_count} не удалась: {e}. "
                            f"Повторная попытка через {current_sleep:.1f} сек..."
                        )
                        await asyncio.sleep(current_sleep)
                        current_sleep *= backoff_factor
                    else:
                        logger.error(f"{prefix}Все {retry_count} попыток не удались: {e}")
            
            # Все попытки не удались
            if fallback_function:
                logger.info(f"{log_prefix} Выполнение резервной функции...")
                return await fallback_function(*args, **kwargs, error=last_exception)
            raise last_exception
            
        @wraps(func)
        def sync_wrapper(*args, **kwargs):
            attempt = 0
            current_sleep = sleep_time
            last_exception = None
            
            while attempt < retry_count:
                try:
                    return func(*args, **kwargs)
                except tuple(exceptions) as e:
                    attempt += 1
                    last_exception = e
                    
                    prefix = f"{log_prefix} " if log_prefix else ""
                    if attempt < retry_count:
                        logger.warning(
                            f"{prefix}Попытка {attempt}/{retry_count} не удалась: {e}. "
                            f"Повторная попытка через {current_sleep:.1f} сек..."
                        )
                        asyncio.sleep(current_sleep)
                        current_sleep *= backoff_factor
                    else:
                        logger.error(f"{prefix}Все {retry_count} попыток не удались: {e}")
            
            # Все попытки не удались
            if fallback_function:
                logger.info(f"{log_prefix} Выполнение резервной функции...")
                return fallback_function(*args, **kwargs, error=last_exception)
            raise last_exception
        
        # Возвращаем правильный враппер в зависимости от типа функции
        if asyncio.iscoroutinefunction(func):
            return async_wrapper
        return sync_wrapper
    
    return decorator


def safe_request(max_attempts=3):
    """
    Декоратор для HTTP запросов с обработкой сетевых ошибок.
    Специально для работы с aiohttp.
    """
    import aiohttp
    
    network_errors = [
        aiohttp.ClientError,
        aiohttp.ClientConnectorError, 
        aiohttp.ClientOSError,
        aiohttp.ServerDisconnectedError,
        aiohttp.ContentTypeError,
        asyncio.TimeoutError
    ]
    
    return handle_errors(
        exceptions=network_errors,
        retry_count=max_attempts,
        sleep_time=2.0,
        backoff_factor=2.0,
        log_prefix="API запрос"
    ) 
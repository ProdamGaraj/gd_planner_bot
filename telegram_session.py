from aiogram.client.session.aiohttp import AiohttpSession


class TelegramSession(AiohttpSession):
    """aiohttp-сессия aiogram с возможностью отключить проверку SSL-сертификата.

    Отключение касается только запросов бота к Telegram API (включая скачивание
    файлов), а не всего процесса — в отличие от dks_bot.
    """

    def __init__(self, *, verify_ssl: bool = True, proxy: str | None = None, **kwargs):
        # Должно быть задано до super().__init__: там вызывается _setup_proxy_connector
        self._verify_ssl = verify_ssl
        super().__init__(proxy=proxy, **kwargs)
        self._apply_ssl()

    def _setup_proxy_connector(self, proxy) -> None:
        super()._setup_proxy_connector(proxy)
        self._apply_ssl()

    def _apply_ssl(self) -> None:
        if not self._verify_ssl:
            self._connector_init["ssl"] = False

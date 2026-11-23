import ssl

from telegram_session import TelegramSession


def test_ssl_verification_off():
    assert TelegramSession(verify_ssl=False)._connector_init["ssl"] is False


def test_ssl_verification_on_by_request():
    ctx = TelegramSession(verify_ssl=True)._connector_init["ssl"]
    assert isinstance(ctx, ssl.SSLContext) and ctx.verify_mode == ssl.CERT_REQUIRED


async def test_connector_really_skips_verification():
    session = TelegramSession(verify_ssl=False)
    client = await session.create_session()
    try:
        assert client.connector._ssl is False
    finally:
        await session.close()

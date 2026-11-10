from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.orm import DeclarativeBase
from app.core.config import get_settings

settings = get_settings()


def sembunyikan_parameter(app_env: str) -> bool:
    """`hide_parameters` engine: di luar `development`, pesan galat SQL (dan log SQL) tidak memuat nilai parameter.
    Galat kueri yang tak tertangani masuk journal sebagai traceback; tanpa ini pesannya berisi parameter kueri,
    mis. alamat email saat login atau keterangan transaksi."""
    return app_env != "development"


engine = create_async_engine(
    settings.DATABASE_URL,
    echo=settings.APP_ENV == "development",
    hide_parameters=sembunyikan_parameter(settings.APP_ENV),
    pool_size=5,
    max_overflow=10,
    pool_pre_ping=True,
)

AsyncSessionLocal = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


async def get_db():
    async with AsyncSessionLocal() as session:
        try:
            yield session
        finally:
            await session.close()

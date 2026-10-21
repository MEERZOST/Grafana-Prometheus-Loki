import os
import time
import logging
import asyncpg
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from prometheus_client import Counter, Histogram, make_asgi_app
from pythonjsonlogger import jsonlogger

# Настраиваем логирование
logger = logging.getLogger("app_logger")
log_handler = logging.StreamHandler()
formatter = jsonlogger.JsonFormatter('%(asctime)s %(levelname)s %(message)s')
log_handler.setFormatter(formatter)
logger.addHandler(log_handler)
logger.setLevel(logging.INFO)

# Метрики Prometheus
REQUEST_COUNT = Counter('app_requests_total', 'Total requests', ['method', 'endpoint', 'http_status'])
REQUEST_LATENCY = Histogram('app_request_latency_seconds', 'Request latency', ['method', 'endpoint'])

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://postgres_user:postgres_password@postgres:5432/devops_db")

# Глобальный объект пула, но теперь мы будем безопасно управлять им через state приложения
@asynccontextmanager
async def lifespan(app: FastAPI):
    # --- Код при старте (Startup) ---
    logger.info("Connecting to database...")
    pool = None
    
    # Делаем 15 попыток дождаться СУБД (ей нужно время на старт файлов на диске)
    for i in range(15):
        try:
            pool = await asyncpg.create_pool(DATABASE_URL)
            logger.info("Successfully connected to PostgreSQL!")
            
            # Сразу создаем таблицу
            async with pool.acquire() as conn:
                await conn.execute('''
                    CREATE TABLE IF NOT EXISTS visits (
                        id SERIAL PRIMARY KEY,
                        ts TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    );
                ''')
            break
        except Exception as e:
            logger.warning(f"Database not ready yet (attempt {i+1}/15). Error: {e}")
            time.sleep(2)
            
    if pool is None:
        logger.error("Could not connect to PostgreSQL. Crashing application.")
        raise RuntimeError("Database connection failed")

    # Передаем пул в состояние приложения, чтобы эндпоинты имели к нему доступ
    yield {"db_pool": pool}
    
    # --- Код при выключении (Shutdown) ---
    logger.info("Closing database connection...")
    await pool.close()

# Инициализируем FastAPI с новым lifespan
app = FastAPI(title="DevOps Practice App with Postgres", lifespan=lifespan)

metrics_app = make_asgi_app()
app.mount("/metrics", metrics_app)

@app.middleware("http")
async def log_and_metric_middleware(request: Request, call_next):
    start_time = time.time()
    endpoint = request.url.path
    method = request.method
    
    if endpoint == "/metrics" or endpoint == "/metrics/":
        return await call_next(request)

    response = await call_next(request)
    process_time = time.time() - start_time
    status_code = response.status_code

    REQUEST_COUNT.labels(method=method, endpoint=endpoint, http_status=status_code).inc()
    REQUEST_LATENCY.labels(method=method, endpoint=endpoint).observe(process_time)

    logger.info("Request processed", extra={
        "http_method": method, "endpoint": endpoint, "status_code": status_code, "latency_seconds": round(process_time, 4)
    })
    return response

@app.get("/")
async def read_root(request: Request):
    # Безопасно забираем пул подключений из состояния приложения
    pool = request.state.db_pool
    
    async with pool.acquire() as conn:
        await conn.execute("INSERT INTO visits DEFAULT VALUES;")
        count = await conn.fetchval("SELECT COUNT(*) FROM visits;")
    
    return {"message": "Hello, DevOps World!", "total_visits_in_db": count}

@app.get("/items/{item_id}")
def read_item(item_id: int):
    if item_id == 13:
        logger.error(f"Unlucky item requested: {item_id}")
        return {"error": "Bad luck!"}, 400
    return {"item_id": item_id, "status": "active"}

@app.get("/force-error")
async def force_error():
    # Намеренно вызываем деление на ноль, что вернет статус 500
    return 1 / 0


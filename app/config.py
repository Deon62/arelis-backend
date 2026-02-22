import os
from dotenv import load_dotenv

load_dotenv()

SECRET_KEY = os.getenv("SECRET_KEY", "foundry-africa-dev-secret-change-in-production")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 24  # 24 hours

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./foundry.db")

DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY", "")

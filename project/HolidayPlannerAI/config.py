from dotenv import load_dotenv, find_dotenv
from starlette.config import Config

ENV_FILE = find_dotenv()
if ENV_FILE:
    load_dotenv(ENV_FILE)

config = Config(ENV_FILE)

HF_TOKEN = config("HF_TOKEN")
SYSTEM_PROMPT = config("SYSTEM_PROMPT")
AMADEUS_CLIENT_ID = config("AMADEUS_CLIENT_ID")
AMADEUS_SECRET_ID = config("AMADEUS_SECRET_ID")
OPENAI_API_KEY = config("OPENAI_API_KEY")
MAPBOX_API_KEY = config("MAPBOX_API_KEY")
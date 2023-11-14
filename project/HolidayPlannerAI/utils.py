from langchain.chains import LLMChain
from langchain.prompts import PromptTemplate
from config import OPENAI_API_KEY, AMADEUS_CLIENT_ID, AMADEUS_SECRET_ID, SYSTEM_PROMPT
import os
from langchain.schema.runnable import RunnablePassthrough
from langchain.chat_models import ChatOpenAI
from langchain.prompts import ChatPromptTemplate
from langchain.tools.render import format_tool_to_openai_function
from langchain.agents.output_parsers import OpenAIFunctionsAgentOutputParser
from langchain.prompts import MessagesPlaceholder
from langchain.agents.format_scratchpad import format_to_openai_functions
from langchain.memory import ConversationBufferMemory
import wikipedia
from langchain.tools import tool
from langchain.agents import AgentExecutor
import requests
from pydantic import BaseModel, Field
import datetime
from typing import Dict
from amadeus import Client, ResponseError
from hotel_list import HotelList

os.environ["AMADEUS_CLIENT_ID"] = AMADEUS_CLIENT_ID
os.environ["AMADEUS_CLIENT_SECRET"] = AMADEUS_SECRET_ID
os.environ["OPENAI_API_KEY"] = OPENAI_API_KEY

amadeus = Client(
    client_id=AMADEUS_CLIENT_ID,
    client_secret=AMADEUS_SECRET_ID
)


class OpenMeteoInput(BaseModel):
    latitude: float = Field(..., description="Latitude of the location to fetch weather data for")
    longitude: float = Field(..., description="Longitude of the location to fetch weather data for")

@tool(args_schema=OpenMeteoInput)
def get_current_temperature(latitude: float, longitude: float) -> dict:
    """Fetch current temperature for given coordinates."""
    
    BASE_URL = "https://api.open-meteo.com/v1/forecast"
    
    # Parameters for the request
    params = {
        'latitude': latitude,
        'longitude': longitude,
        'hourly': ['temperature_2m', 'wind_speed_10m', 'relative_humidity_2m'],
        'forecast_days': 1,
    }

    # Make the request
    response = requests.get(BASE_URL, params=params)
    #print(response.json())
    
    if response.status_code == 200:
        results = response.json()
    else:
        raise Exception(f"API Request failed with status code: {response.status_code}")

    current_utc_time = datetime.datetime.utcnow()
    time_list = [datetime.datetime.fromisoformat(time_str.replace('Z', '+00:00')) for time_str in results['hourly']['time']]
    temperature_list = results['hourly']['temperature_2m']
    wind_speed_list = results['hourly']['wind_speed_10m']
    humidity_list = results['hourly']['relative_humidity_2m']
    
    closest_time_index = min(range(len(time_list)), key=lambda i: abs(time_list[i] - current_utc_time))
    current_temperature = temperature_list[closest_time_index]
    current_humidity = humidity_list[closest_time_index]
    current_wind_speed = wind_speed_list[closest_time_index]
    return f'The current temperature is {current_temperature}°C the current humidity is {current_humidity}% and the current wind speed is {current_wind_speed}km/h'

@tool
def search_wikipedia(query: str) -> str:
    """Run Wikipedia search and get page summaries."""
    page_titles = wikipedia.search(query)
    summaries = []
    for page_title in page_titles[: 3]:
        try:
            wiki_page =  wikipedia.page(title=page_title, auto_suggest=False)
            summaries.append(f"Page: {page_title}\nSummary: {wiki_page.summary}")
        except (
            self.wiki_client.exceptions.PageError,
            self.wiki_client.exceptions.DisambiguationError,
        ):
            pass
    if not summaries:
        return "No good Wikipedia Search Result was found"
    return "\n\n".join(summaries)

class NearestAirportInput(BaseModel):
    latitude: float = Field(..., description="Latitude of the location to fetch the nearest airport for")
    longitude: float = Field(..., description="Longitude of the location to fetch the nearest airport for")

@tool(args_schema=NearestAirportInput) 
def nearest_relevant_airport(latitude: float, longitude: float)-> Dict:
    """Fetch the nearest airport for given coordinates."""
    try:
        response = amadeus.reference_data.locations.airports.get(
            latitude=latitude,
            longitude=longitude
        )
        print(response.data)
        return response.data

    except ResponseError as error:
        return str(error)

class TravelRecommendationsInput(BaseModel):
    city_code: str = Field(..., description="City code to fetch travel recommendations for")

@tool(args_schema=TravelRecommendationsInput)
def travel_recommendations(city_code: str )-> str:
    """Fetch travel recommendations of other cities for given city code."""
    try:
        response = amadeus.reference_data.locations.points_of_interest.get(
            cityCode=city_code
        )
        return response.data
    except ResponseError as error:
        return str(error)

class SearchPointOfInterestInput(BaseModel):
    latitude: float = Field(..., description="Latitude of the location to fetch the nearest points of interest")
    longitude: float = Field(..., description="Longitude of the location to fetch the nearest points of interest")

@tool(args_schema=SearchPointOfInterestInput)
def search_point_of_interest(latitude: float, longitude: float)-> Dict:
    """Fetch the nearest points of interest for given coordinates."""
    try:
        response = amadeus.reference_data.locations.points_of_interest.get(
            latitude=latitude,
            longitude=longitude
        )
        return response.data
    except ResponseError as error:
        return str(error)

class SearchHotels(BaseModel):
    city_code: str = Field(..., description="City code to fetch hotels for")

@tool(args_schema=SearchHotels)
def search_hotels(city_code: str)-> Dict:
    """Fetch hotels for given city code."""
    try:
        response = amadeus.reference_data.locations.hotels.by_city.get(
            cityCode=city_code
        )
        hotel_offers = []
        for hotel in response.data[:10]:
            list_offer = HotelList(hotel).construct_hotel_list()
            hotel_offers.append(list_offer)
        return hotel_offers
    except ResponseError as error:
        return str(error)

def run_agent_with_executor(user_input: str) -> Dict:

    tools = [get_current_temperature, search_wikipedia, nearest_relevant_airport,
              travel_recommendations, search_point_of_interest, search_hotels]
    functions = [format_tool_to_openai_function(f) for f in tools]

    model = ChatOpenAI(temperature=0, model="gpt-4-1106-preview").bind(functions=functions)
    prompt = ChatPromptTemplate.from_messages([
        ("system", SYSTEM_PROMPT),
        MessagesPlaceholder(variable_name="chat_history"),
        ("user", "{input}"),
        MessagesPlaceholder(variable_name="agent_scratchpad")
    ])

    agent_chain = RunnablePassthrough.assign(
        agent_scratchpad=lambda x: format_to_openai_functions(x["intermediate_steps"])
    ) | prompt | model | OpenAIFunctionsAgentOutputParser()
    memory = ConversationBufferMemory(return_messages=True, memory_key="chat_history")
    agent_executor = AgentExecutor(agent=agent_chain, tools=tools, verbose=True, memory=memory)

    return agent_executor.invoke({"input": user_input})


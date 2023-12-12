import json
import os
import time
from pathlib import Path
from ipyleaflet import Map, Marker, Popup, Icon, basemaps, TileLayer
import ipyleaflet
from ipywidgets import HTML, widgets
from openai import NotFoundError, OpenAI
from openai.types.beta import Thread
import solara
from config import OPENAI_API_KEY, AMADEUS_CLIENT_ID, AMADEUS_SECRET_ID, OPENAI_ASSISTANT_ID
from typing import Dict
from amadeus import Client, ResponseError
from hotel_list import HotelList
import requests
import wikipedia
import datetime
import sounddevice as sd
import tempfile
import wave
import sys

os.environ["AMADEUS_CLIENT_ID"] = AMADEUS_CLIENT_ID
os.environ["AMADEUS_CLIENT_SECRET"] = AMADEUS_SECRET_ID

amadeus = Client(
    client_id=AMADEUS_CLIENT_ID,
    client_secret=AMADEUS_SECRET_ID
)


HERE = Path(__file__).parent
print(HERE)
center_default = (0, 0)
zoom_default = 2

recording = False
audio_file_path = None
messages = solara.reactive([])
zoom_level = solara.reactive(zoom_default)
center = solara.reactive(center_default)
markers = solara.reactive([])


url = ipyleaflet.basemaps.OpenStreetMap.Mapnik.build_url()
openai = OpenAI(api_key=OPENAI_API_KEY)
model = "gpt-4-1106-preview"
app_style = (HERE / "style.css").read_text()


# Declare tools for openai assistant to use
TOOLS=[
    {
        "type": "function",
        "function": {
            "name": "update_map",
            "description": "Update map to center on a particular location",
            "parameters": {
                "type": "object",
                "properties": {
                    "longitude": {
                        "type": "number",
                        "description": "Longitude of the location to center the map on"
                    },
                    "latitude": {
                        "type": "number",
                        "description": "Latitude of the location to center the map on"
                    },
                    "zoom": {
                        "type": "integer",
                        "description": "Zoom level of the map"
                    }
                },
                "required": ["longitude", "latitude", "zoom"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "add_marker",
            "description": "Add marker to the map",
            "parameters": {
                "type": "object",
                "properties": {
                    "longitude": {
                        "type": "number",
                        "description": "Longitude of the location to the marker"
                    },
                    "latitude": {
                        "type": "number",
                        "description": "Latitude of the location to the marker"
                    },
                    "label": {
                        "type": "string",
                        "description": "Text to display on the marker"
                    }
                },
                "required": ["longitude", "latitude", "label"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_current_temperature",
            "description": "get_current_temperature(latitude: float, longitude: float) -> dict - Fetch current temperature for given coordinates.",
            "parameters": {
                "type": "object",
                "properties": {
                    "latitude": {
                        "type": "number",
                        "description": "Latitude of the location"
                    },
                    "longitude": {
                        "type": "number",
                        "description": "Longitude of the location"
                    }
                },
                "required": ["latitude", "longitude"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "search_wikipedia",
            "description": "search_wikipedia(query: str) -> str - Run Wikipedia search and get page summaries.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "The query to search Wikipedia"
                    }
                },
                "required": ["query"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "nearest_relevant_airport",
            "description": "nearest_relevant_airport(latitude: float, longitude: float) -> Dict - Fetch the nearest airport for given coordinates.",
            "parameters": {
                "type": "object",
                "properties": {
                    "latitude": {
                        "description": "Latitude of the location to fetch the nearest airport for",
                        "type": "number"
                    },
                    "longitude": {
                        "description": "Longitude of the location to fetch the nearest airport for",
                        "type": "number"
                    }
                },
                "required": ["latitude", "longitude"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "search_point_of_interest",
            "description": "search_point_of_interest(latitude: float, longitude: float) -> Dict - Fetch the nearest points of interest for given coordinates.",
            "parameters": {
                "type": "object",
                "properties": {
                    "latitude": {
                        "description": "Latitude of the location to fetch the nearest points of interest",
                        "type": "number"
                    },
                    "longitude": {
                        "description": "Longitude of the location to fetch the nearest points of interest",
                        "type": "number"
                    }
                },
                "required": ["latitude", "longitude"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "search_hotels",
            "description": "search_hotels(city_code: str) -> Dict - Fetch hotels for given city code.",
            "parameters": {
                "type": "object",
                "properties": {
                    "city_code": {
                        "description": "City code to fetch hotels for",
                        "type": "string"
                    }
                },
                "required": ["city_code"]
            }
        }
    }
]


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
    update_map(longitude, latitude, zoom=15)
    #add_marker(longitude, latitude, "Current Location")
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
    return f"Current temperature: {current_temperature}°C\nCurrent humidity: {current_humidity}%\nCurrent wind speed: {current_wind_speed}m/s"

def search_wikipedia(query: str) -> str:
    """Run Wikipedia search and get page summaries."""
    page_titles = wikipedia.search(query)
    summaries = []
    for page_title in page_titles[: 2]:
        try:
            wiki_page =  wikipedia.page(title=page_title, auto_suggest=False)
            summaries.append(f"Page: {page_title}\nSummary: {wiki_page.summary}")
        except (
            wikipedia.exceptions.PageError,
            wikipedia.exceptions.DisambiguationError,
        ):
            pass
    if not summaries:
        return "No good Wikipedia Search Result was found"
    return "\n\n".join(summaries)

def nearest_relevant_airport(latitude: float, longitude: float)-> str:
    """Fetch the nearest airport for given coordinates."""
    try:
        response = amadeus.reference_data.locations.airports.get(
            latitude=latitude,
            longitude=longitude
        )
        #print(response.data)
        airport_data = [(airport['name'], airport['geoCode']['latitude'], airport['geoCode']['longitude']) for airport in response.data[:2]]
        initial_location = airport_data[0]
        update_map(initial_location[2], initial_location[1], zoom=10)
        for name, latitude, longitude in airport_data:
            add_marker(longitude, latitude, name, "airport")
        return f"{airport_data}"
    except ResponseError as error:
        return str(error)


def search_point_of_interest(latitude: float, longitude: float)-> str:
    """Fetch the nearest points of interest for given coordinates."""
    try:
        response = amadeus.reference_data.locations.points_of_interest.get(
            latitude=latitude,
            longitude=longitude
        )
        extracted_data = [(loc['name'], loc['geoCode']['latitude'], loc['geoCode']['longitude']) for loc in response.data[:5]]
        initial_location = extracted_data[0]
        update_map(initial_location[2], initial_location[1], zoom=10)

        # Add markers for each location
        for name, latitude, longitude in extracted_data:
            add_marker(longitude, latitude, name, "point_of_interest")
        return f"{extracted_data}"
    except ResponseError as error:
        return str(error)

def search_hotels(city_code: str)-> str:
    """Fetch hotels for given city code."""
    try:
        response = amadeus.reference_data.locations.hotels.by_city.get(
            cityCode=city_code
        )
        hotel_offers = []
        for hotel in response.data[:5]:
            list_offer = HotelList(hotel).construct_hotel_list()
            hotel_offers.append(list_offer)
        for hotel_offer in hotel_offers:
            add_marker(hotel_offer["longitude"], hotel_offer["latitude"], hotel_offer["name"], "hotel")
        update_map(hotel_offers[0]["longitude"], hotel_offers[0]["latitude"], zoom=10)
        return f"{hotel_offers}"

    except ResponseError as error:
        return str(error)

def update_map(longitude, latitude, zoom):
    center.set((latitude, longitude))
    zoom_level.set(zoom)
    return "Map updated"


# def add_marker(longitude, latitude, label):
#     markers.set(markers.value + [{"location": (latitude, longitude), "label": label}])
#     return "Marker added"
def add_marker(longitude, latitude, label, location_type):
    new_marker = {
        "location": (latitude, longitude),
        "label": label,
        "type": location_type  # Add the type attribute here
    }
    markers.set(markers.value + [new_marker])
    return "Marker added"

functions = {
    "update_map": update_map,
    "add_marker": add_marker,
    "get_current_temperature": get_current_temperature,
    "search_wikipedia": search_wikipedia,
    "nearest_relevant_airport": nearest_relevant_airport,
    "search_point_of_interest": search_point_of_interest,
    "search_hotels": search_hotels,
}


def assistant_tool_call(tool_call):
    # actually executes the tool call the OpenAI assistant wants to perform
    function = tool_call.function
    name = function.name
    arguments = json.loads(function.arguments)
    return_value = functions[name](**arguments)
    tool_outputs = {
        "tool_call_id": tool_call.id,
        "output": return_value,
    }
    return tool_outputs


@solara.component
def Map():
    # ipyleaflet.Map.element(  # type: ignore
    #     zoom=zoom_level.value,
    #     center=center.value,
    #     scroll_wheel_zoom=True,
    #     layers=[
    #         ipyleaflet.TileLayer.element(url=url),
    #         *[
    #             ipyleaflet.Marker.element(location=k["location"], draggable=False)
    #             for k in markers.value
    #         ],
    #     ],
    # )
    icons = {
    "hotel": {"icon_url": "/static/public/hotel_2.png", "icon_size": [25, 25]},
    "airport": {"icon_url": "/static/public/airport.png", "icon_size": [25, 25]},
    "point_of_interest": {"icon_url": "/static/public/point-of-interest.png", "icon_size": [25, 25]},
    }


    marker_elements = []
    for location in markers.value:
        icon_info = icons.get(location.get("type"), None)
        #print(icon_info)
        if icon_info:
            # Ensure the icon URL is correct and accessible
            icon = Icon(**icon_info)
            #print(icon)
        else:
            icon = None

        popup_widget = widgets.HTML(value=location["label"])
        popup = Popup(
            location=location["location"], 
            child=popup_widget, 
            close_button=False, 
            auto_close=False
        )

        marker = Marker(
            location=location["location"], 
            icon=icon, 
            draggable=False, 
            title=location["label"], 
            popup=popup
        )
        marker_elements.append(marker)
    #print(marker_elements)

    # Include the markers in the layers of the map
    return ipyleaflet.Map.element(
        center=center.value,
        zoom=zoom_level.value,
        scroll_wheel_zoom=True,
        layers=[
            ipyleaflet.TileLayer.element(url=url),
            *marker_elements
        ]
    )

marker_message_shown = False  

@solara.component
def ChatMessage(message):
    global recording, audio_file_path, marker_message_shown

    with solara.Row(style={"align-items": "flex-start"}):
        # Handle recording status
        if recording:
            solara.v.Icon(children=["mdi-microphone"], style_="padding-top:10px;")
            solara.Markdown("Recording...")

        # Process different types of messages
        if isinstance(message, dict):
            # Handle map updates separately
            if message["output"] == "Map updated":
                solara.v.Icon(children=["mdi-map"], style_="padding-top: 10px;")
                solara.Markdown(message["output"])
            # Display "Marker added" message only once
            elif message["output"] == "Marker added" and not marker_message_shown:
                solara.Markdown("Markers have been added to the map.")
                marker_message_shown = True  # Set the flag to True after displaying the message
        elif message.role == "user":
            # Display user messages
            solara.Text(message.content[0].text.value, style={"font-weight": "bold;"})
        elif message.role == "assistant":
            # Display assistant messages
            if message.content[0].text.value:
                solara.v.Icon(
                    children=["mdi-compass-outline"], style_="padding-top: 10px;"
                )
                solara.Markdown(message.content[0].text.value)
            elif message.content.tool_calls:
                # Display tool call messages
                solara.v.Icon(children=["mdi-map"], style_="padding-top: 10px;")
                solara.Markdown("*Calling map functions*")
            else:
                solara.v.Icon(
                    children=["mdi-compass-outline"], style_="padding-top: 10px;"
                )
                solara.Preformatted(repr(message))
        else:
            # Handle other types of messages
            solara.v.Icon(children=["mdi-compass-outline"], style_="padding-top: 10px;")
            solara.Preformatted(repr(message))



def VoiceRecordingButton():
    global audio_file_path

    recording = solara.use_reactive(False)  # Reactive variable to track recording state
    audio_frames = solara.use_reactive([])  # Reactive variable to store audio frames

    def start_stop_recording(event=None):  # Accept an argument, even if it's not used
        global audio_file_path

        if recording.value:
            # Stop recording
            recording.set(False)  # Set recording state to False

            # Save the audio file
            if audio_file_path:
                save_audio(audio_file_path, audio_frames.value)  # Pass audio_frames.value
                transcript = transcribe_audio(audio_file_path)
                os.remove(audio_file_path)
                audio_file_path = None

                # Add the transcript to the user's message
                solara.state.ChatMessage.input(message={"role": "user", "content": transcript})
                audio_frames.set([])  # Clear audio frames
        else:
            # Start recording
            recording.set(True)  # Set recording state to True
            audio_file_path = tempfile.mktemp(suffix=".wav")
            fs = 44100  # Sample rate (you can adjust this)
            duration = 10  # Recording duration in seconds (you can adjust this)
            audio_frames.set([])  # Clear audio frames

            with sd.OutputStream(samplerate=fs, channels=1, callback=callback):
                sd.sleep(int(duration * 1000))

    def callback(indata, frames, time, status):
        if status:
            print(status, file=sys.stderr)
        if recording.value:  # Check the .value attribute of the reactive variable
            audio_frames.append(indata.copy())

    def save_audio(file_path, frames):  # Accept frames as an argument
        with wave.open(file_path, 'wb') as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(44100)
            wf.writeframes(b''.join(frames))  # Use the frames argument

    def transcribe_audio(file_path):
        with open(file_path, "rb") as audio_file:
            transcript = openai.audio.transcriptions.create(
                model="whisper-1", 
                file=audio_file
            )
            if transcript.status_code == 200:
                return transcript["text"]
            else:
                return f"Transcription error: {transcript.status_code}"

    with solara.Row():
        solara.Switch(
            label="Record Voice",
            value=recording.value,
            style="margin-right: 10px;",
            on_value=start_stop_recording,  # Toggle recording when the switch value changes
        )

@solara.component
def ChatBox(children=[]):
    # this uses a flexbox with column-reverse to reverse the order of the messages
    # if we now also reverse the order of the messages, we get the correct order
    # but the scroll position is at the bottom of the container automatically
    with solara.Column(style={"flex-grow": "1"}):
        solara.Style(
            """
            .chat-box > :last-child{
                padding-top: 7.5vh;
            }
            """
        )
        # The height works effectively as `min-height`, since flex will grow the container to fill the available space
        solara.Column(
            style={
                "flex-grow": "1",
                "overflow-y": "auto",
                "height": "100px",
                "flex-direction": "column-reverse",
            },
            classes=["chat-box"],
            children=list(reversed(children)),
        )


@solara.component
def ChatInterface():
    prompt = solara.use_reactive("")
    run_id: solara.Reactive[str] = solara.use_reactive(None)

    # Create a thread to hold the conversation only once when this component is created
    thread: Thread = solara.use_memo(openai.beta.threads.create, dependencies=[])

    def add_message(value: str):
        if value == "":
            return
        prompt.set("")
        new_message = openai.beta.threads.messages.create(
            thread_id=thread.id, content=value, role="user"
        )
        messages.set([*messages.value, new_message])
        # this creates a new run for the thread
        # also also triggers a rerender (since run_id.value changes)
        # which will trigger the poll function blow to start in a thread
        run_id.value = openai.beta.threads.runs.create(
            thread_id=thread.id,
            assistant_id=OPENAI_ASSISTANT_ID,
            tools=TOOLS,
        ).id

    def poll():
        if not run_id.value:
            return
        completed = False
        while not completed:
            try:
                run = openai.beta.threads.runs.retrieve(
                    run_id.value, thread_id=thread.id
                )
            # Above will raise NotFoundError when run creation is still in progress
            except NotFoundError:
                continue
            if run.status == "requires_action":
                tool_outputs = []
                for tool_call in run.required_action.submit_tool_outputs.tool_calls:
                    tool_output = assistant_tool_call(tool_call)
                    tool_outputs.append(tool_output)
                    messages.set([*messages.value, tool_output])
                openai.beta.threads.runs.submit_tool_outputs(
                    thread_id=thread.id,
                    run_id=run_id.value,
                    tool_outputs=tool_outputs,
                )
            if run.status == "completed":
                messages.set(
                    [
                        *messages.value,
                        openai.beta.threads.messages.list(thread.id).data[0],
                    ]
                )
                run_id.set(None)
                completed = True
            time.sleep(0.1)

    # run/restart a thread any time the run_id changes
    result = solara.use_thread(poll, dependencies=[run_id.value])

    # Create DOM for chat interface
    with solara.Column(classes=["chat-interface"]):
        if len(messages.value) > 0:
            with ChatBox():
                for message in messages.value:
                    ChatMessage(message)

        with solara.Column():
            solara.InputText(
                label="Where do you want to go?"
                if len(messages.value) == 0
                else "What else would you want to know?",
                value=prompt,
                style={"flex-grow": "1"},
                on_value=add_message,
                disabled=result.state == solara.ResultState.RUNNING,
            )

            VoiceRecordingButton()
            solara.ProgressLinear(result.state == solara.ResultState.RUNNING)
            if result.state == solara.ResultState.ERROR:
                solara.Error(repr(result.error))


@solara.component
def Page():
    with solara.Column(
        classes=["ui-container"],
        gap="5vh",
    ):
        with solara.Row(justify="space-between"):
            with solara.Row(gap="10px", style={"align-items": "center"}):
                solara.v.Icon(children=["mdi-compass-rose"], size="36px")
                solara.HTML(
                    tag="h2",
                    unsafe_innerHTML="HolidayPlannerAI <span style='font-size: 0.5em;'></span>",
                    style={"display": "inline-block"},
                )
            with solara.Row(
                gap="30px",
                style={"align-items": "center"},
                classes=["link-container"],
                justify="end",
            ):
                with solara.Row(gap="5px", style={"align-items": "center"}):
                    solara.Text("Source Code:", style="font-weight: bold;")
                    with solara.v.Btn(
                        icon=True,
                        tag="a",
                        attributes={
                            "href": "https://github.com/LauraDiosan-CS/projects-holidayplanner2023",
                            "title": "TravelAI Source Code",
                            "target": "_blank",
                        },
                    ):
                        solara.v.Icon(children=["mdi-github-circle"])
                with solara.Row(gap="5px", style={"align-items": "center"}):
                    solara.Text("Powered by Solara:", style="font-weight: bold;")
                    with solara.v.Btn(
                        icon=True,
                        tag="a",
                        attributes={
                            "href": "https://solara.dev/",
                            "title": "Solara",
                            "target": "_blank",
                        },
                    ):
                        solara.HTML(
                            tag="img",
                            attributes={
                                "src": "https://solara.dev/static/public/logo.svg",
                                "width": "24px",
                            },
                        )

        with solara.Row(
            justify="space-between", style={"flex-grow": "1"}, classes=["container-row"]
        ):
            ChatInterface()
            with solara.Column(classes=["map-container"]):
                Map()

        solara.Style(app_style)
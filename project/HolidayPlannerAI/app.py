import streamlit as st
from langchain.memory import ConversationBufferMemory
from langchain.memory.chat_message_histories import StreamlitChatMessageHistory
from utils import run_agent_with_executor
from audiorecorder import audiorecorder

st.set_page_config(page_title="StreamlitChatMessageHistory", page_icon="🧑‍✈️", layout="wide", initial_sidebar_state="collapsed")
st.title("TravelAI 🧑‍✈️")

#left_col, right_col = st.columns(2)

# with left_col:
#     with st.container():
#         for role, message in st.session_state[conversation_state]:
#             with st.chat_message(role):
#                 st.write(message)
#     status_placeholder = st.empty()

msgs = StreamlitChatMessageHistory(key="langchain_messages")
memory = ConversationBufferMemory(chat_memory=msgs)
#audio = audiorecorder("Click to record", "Click to stop recording")
if len(msgs.messages) == 0:
    msgs.add_ai_message("How can I help you?")

view_messages = st.expander("View the message contents in session state")

for msg in msgs.messages:
    st.chat_message(msg.type).write(msg.content)

# If user inputs a new prompt, generate and draw a new response
if prompt := st.chat_input():
    st.chat_message("human").write(prompt)
    # Note: new messages are saved to history automatically by Langchain during run
    response = run_agent_with_executor(prompt)["output"]
    st.chat_message("assistant").write(response)

# Draw the messages at the end, so newly generated ones show up immediately
with view_messages:
    """
    Memory initialized with:
    ```python
    msgs = StreamlitChatMessageHistory(key="langchain_messages")
    memory = ConversationBufferMemory(chat_memory=msgs)
    ```

    Contents of `st.session_state.langchain_messages`:
    """
    view_messages.json(st.session_state.langchain_messages)
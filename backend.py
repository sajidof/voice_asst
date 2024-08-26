from fastapi import FastAPI, WebSocket
from pydub import AudioSegment
from io import BytesIO
import speech_recognition as sr
import anthropic
from gtts import gTTS
from pydub.playback import play
import os


anthropic_api_key = os.getenv('CLAUDE_API_KEY')
app = FastAPI()
client = anthropic.Client(api_key=anthropic_api_key)
conversation_history = []
MAX_CONV_HIST_SIZE = 6
SYSTEM_PROMPT = "You are a helpful and loyal voice assistant who assists the user with their day-to-day life."

# Takes in audio bytes from client and returns transcription
def audio_bytes_to_text(audio_bytes):
    audio = AudioSegment.from_file(BytesIO(audio_bytes), format="webm")

    # Load audio bytes into buffer as wav
    audio_buffer = BytesIO()
    audio.export(audio_buffer, format='wav')
    audio_buffer.seek(0)

    # Transcribe
    recognizer = sr.Recognizer()
    with sr.AudioFile(audio_buffer) as source:
        audio_data = recognizer.record(source)
    try:
        # Perform the transcription
        transcription = recognizer.recognize_google(audio_data)
        return transcription
    except sr.UnknownValueError:
        return "Unable to recognize speech."
    except sr.RequestError as e:
        return f"Could not request results; {e}"

# Takes transcription and returns LLM response
def get_llm_response(conversation_history):
    message = client.messages.create(
        model="claude-3-haiku-20240307",
        max_tokens=50,
        temperature=0.5,
        system=SYSTEM_PROMPT,
        messages=conversation_history
    )
    return message.content[0].text

# Takes LLM response, generates voice synthesis using Google TTS, returns audio bytes
def text_to_audio_bytes(text):
    # Voice synthesis
    tts = gTTS(text=text, lang='en')

    # Save speech audio to buffer
    audio_file = BytesIO()
    tts.write_to_fp(audio_file)
    audio_file.seek(0)

    return audio_file.read()


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    print("A connection has been established with the client!!!")
    try:
        while True:
            audio_bytes = await websocket.receive_bytes()
            print(f"Bytes received: {len(audio_bytes)} bytes")

            # Transcribe the input audio
            transcription = audio_bytes_to_text(audio_bytes)
            print("Transcription is complete. It is: ", transcription)

            # Get LLM response
            conversation_history.append({"role": "user", "content": transcription})
            response_text = get_llm_response(conversation_history)

            # Update conversation history and prune if it gets too long
            conversation_history.append({"role": "assistant", "content": response_text})
            if len(conversation_history) > MAX_CONV_HIST_SIZE:
                conversation_history.pop(0)
                conversation_history.pop(0)
            print("LLM response generation is complete. It is: ", response_text)

            # Generate speech response
            response_audio = text_to_audio_bytes(response_text)

            # Send back response audio bytes
            await websocket.send_bytes(response_audio)

    except Exception as e:
        print(f"Error: {e}")
    finally:
        if not websocket.client_state.closed:
            await websocket.close()
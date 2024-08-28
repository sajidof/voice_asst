import asyncio
from fastapi import FastAPI, WebSocket
from pydub import AudioSegment
from io import BytesIO
import speech_recognition as sr
import anthropic
from gtts import gTTS
from pydub.playback import play
import os
import sendgrid
from sendgrid.helpers.mail import Mail, Email, To, Content


anthropic_api_key = os.getenv('CLAUDE_API_KEY')
sendgrid_api_key = os.getenv('SENDGRID_API_KEY')
email_sender_addr = "assistantvoiceai@gmail.com"  # Use email verified with your sendgrid

app = FastAPI()
client = anthropic.Client(api_key=anthropic_api_key)
conversation_history = []
MAX_CONV_HIST_SIZE = 6
with open('system_prompt.txt', 'r') as file:
    SYSTEM_PROMPT = file.read()

tools=[
    {
        "name": "send_email",
        "description": "Send an email to the user. Use this when the user asks to send an email or a reminder to themselves. Do not use this tool if the user is trying to send an email to someone else, only if they want to send an email to themselves, for instance to remind themself of something that came up during the prior conversation. Do not use this tool if the user has not provided you with email address of the recipient and the subject line. Do not use this tool if the user has not already provided additional confirmation that the email you received is indeed correct. Once you repeat the email back to the user and the user then confirms that it is correct AND the user has supplied you with a subject line, THEN use this tool.",
        "input_schema": {
            "type": "object",
            "properties": {
                "to_addr": {
                    "type": "string",
                    "description": "The email address of the recipient of the email. It should contain an '@' followed by some domain as email addresses usually do. The user is likely to spell out this parameter to avoid transcription errors, but the function will only accept a valid email address without spaces between characters - make sure you delete any space between characters and replace 'at' with the symbol '@' for the input.",
                },
                "subject": {
                    "type": "string",
                    "description": "The subject line of the email. This should be fairly concise",
                },
                "content": {
                    "type": "string",
                    "description": "The content of the email.",
                }
            },
            "required": ["to_addr", "subject"],
        },
    }
]


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
        max_tokens=300,
        temperature=0.5,
        system=SYSTEM_PROMPT,
        tools=tools,
        messages=conversation_history
    )
    return message

# Send an email
def send_email(to_addr, subject, content):
    sg = sendgrid.SendGridAPIClient(api_key=sendgrid_api_key)
    from_email = Email(email_sender_addr)  # Change to your verified sender
    to_email = To(to_addr)  # Change to your recipient
    subject = subject
    content = Content("text/plain", content)
    mail = Mail(from_email, to_email, subject, content)

    # Get a JSON-ready representation of the Mail object
    mail_json = mail.get()

    # Send an HTTP POST request to /mail/send
    response = sg.client.mail.send.post(request_body=mail_json)
    return response.status_code, response.headers


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
            print("Transcription is complete. It is: ", transcription, ". Getting LLM response.")

            # Get LLM response
            conversation_history.append({"role": "user", "content": transcription})
            response_block = get_llm_response(conversation_history)


            # If response includes a function call:
            if response_block.stop_reason == "tool_use":
                print("Identified the need for tool use")

                conversation_history.append({"role": "assistant", "content": response_block.content})  # Update convo history
                for c in response_block.content:
                    if c.type == 'text':
                        print(f"Sending bytes for {c.text}")
                        response_audio = text_to_audio_bytes(c.text)
                        print(f"Sending initial response of {c.text}")
                        await websocket.send_bytes(response_audio)
                        await asyncio.sleep(5)  # Temporary fix for overlapping audio - will pause for 5 seconds before continuing with function call

        
                    elif c.type == 'tool_use':
                        to_addr = c.input['to_addr']
                        subject = c.input['subject']
                        content = c.input['content']
                        email_result = send_email(to_addr, subject, content)
                        email_response = "The email was sent successfully" if email_result[0] == 202 else "There was some issue sending the email"
                        print(f"Status of the email: {email_response}")
                        function_result = [
                            {
                                "type":"tool_result",
                                "tool_use_id":c.id,
                                "content":email_response
                            }
                        ]
                        conversation_history.append({"role": "user", "content": function_result})
                        response_to_fn_call = get_llm_response(conversation_history)
                        conversation_history.append({"role": "assistant", "content": response_to_fn_call.content[0].text})
                        
                        response_audio = text_to_audio_bytes(response_to_fn_call.content[0].text)
                        print(f"Sending bytes for {response_to_fn_call.content[0].text}")
                        await websocket.send_bytes(response_audio)

            # If it doesnt 
            else:
                conversation_history.append({"role": "assistant", "content": response_block.content[0].text})  # Update convo history
                response_audio = text_to_audio_bytes(response_block.content[0].text)
                await websocket.send_bytes(response_audio)

            
            # Update conversation history and prune if it gets too long
            while len(conversation_history) > MAX_CONV_HIST_SIZE:
                conversation_history.pop(0)
                conversation_history.pop(0)

            

    except Exception as e:
        print(f"Error: {e}")
    finally:
        if not websocket.client_state.closed:
            await websocket.close()
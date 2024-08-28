# Voice Assistant Project
Web app + FastAPI Websocket voice assistant

# Instructions to run:
- Clone repository
- Install dependencies with `pip install -r requirements.txt`
- Ensure you have CLAUDE_API_KEY environment variable set up
- Ensure you have SENDGRID_API_KEY environment variable set-up and replace line 16 (email_sender_addr) with an email address verified with the Sendgrid API key
- Run `uvicorn backend:app` to set up FastAPI server locally
- Open index.html file in a web browser
- Try speaking with the assistant :)

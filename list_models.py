import os
from google import genai
from dotenv import load_dotenv

load_dotenv()

def list_gemini_models():
    api_key = os.getenv('GEMINI_API_KEY_COLOR') or os.getenv('GEMINI_API_KEY')
    if not api_key:
        print("No API Key found.")
        return
        
    client = genai.Client(api_key=api_key)
    print("Available Gemini Models:")
    print("------------------------")
    try:
        # Use the list_models method if available in the SDK
        # Note: Depending on the SDK version, the method might vary.
        # For 'google-genai' it is client.models.list()
        for m in client.models.list():
            if 'generateContent' in getattr(m, 'supported_actions', []):
                print(f"ID: {m.name} | Display: {m.display_name}")
    except Exception as e:
        print(f"Error listing models: {e}")

if __name__ == "__main__":
    list_gemini_models()

import os
from openai import OpenAI
from app.settings import OPENAI_API_KEY


class LinkedInAgent:
    def __init__(self, deployment: str = "OpenAI"):
        if deployment == "local_llm":
            self.api_key = "llama3"
            self.client = OpenAI(
                base_url='http://localhost:11434/v1/',
                api_key=self.api_key
            )
        elif deployment == "OpenAI":
            self.api_key = OPENAI_API_KEY
            self.client = OpenAI(api_key=self.api_key)

        self.conversation = [
            {
                "role": "system", 
                "content": "You are a professional LinkedIn assistant. Always reply in a polite and concise way, considering the full context of the conversation."
            }
        ]

    async def receive_message(self, text: str):
        """Add new LinkedIn message from the other person."""
        self.conversation.append({"role": "user", "content": text})

    async def generate_reply(self) -> str:
        """Generate and store the assistant’s reply based on full context."""
        response = await self.client.chat.completions.create(
            model="gpt-4o-mini",
            messages=self.conversation
        )
        reply = response.choices[0].message.content
        self.conversation.append({"role": "assistant", "content": reply})
        return reply

















# import requests
# import json
# from abc import ABC, abstractmethod
# from typing import List, Dict


# # === Abstract LLM backend ===
# class BaseLLM(ABC):
#     @abstractmethod
#     def generate_response(self, messages: List[Dict[str, str]]) -> str:
#         """
#         messages is a list of dicts like:
#         [{"role": "user", "content": "Hi"}, {"role": "assistant", "content": "Hello!"}]
#         """
#         pass


# # === OpenAI backend ===
# class OpenAIBackend(BaseLLM):
#     def __init__(self, api_key: str, model: str = "gpt-4o-mini"):
#         from openai import OpenAI
#         self.client = OpenAI(api_key=api_key)
#         self.model = model

#     def generate_response(self, messages: List[Dict[str, str]]) -> str:
#         response = self.client.chat.completions.create(
#             model=self.model,
#             messages=messages,
#         )
#         return response.choices[0].message.content.strip()


# # === Local LLM backend (example with Ollama) ===
# class LocalLLMBackend(BaseLLM):
#     def __init__(self, model: str = "llama3"):
#         self.model = model
#         self.endpoint = "http://localhost:11434/api/chat"  # Ollama default

#     def generate_response(self, messages: list[dict]) -> str:
#         # Combine messages into a conversation string for Ollama
#         prompt = "\n".join(
#             f"{m['role'].capitalize()}: {m['content']}" for m in messages
#         ) + "\nAssistant:"

#         payload = {"model": self.model, "prompt": prompt, "stream": False}

#         r = requests.post(self.endpoint, json=payload, stream=False)
#         r.raise_for_status()

#         full_reply = []
#         for line in r.iter_lines():
#             if not line:
#                 continue
#             data = json.loads(line.decode("utf-8"))
#             if "response" in data:
#                 full_reply.append(data["response"])
#             if data.get("done"):
#                 break

#         return "".join(full_reply).strip()


# # === The AI Agent ===
# class ChatAgent:
#     def __init__(self, backend: BaseLLM, persona: str = "You are a helpful assistant."):
#         self.backend = backend
#         self.persona = persona
#         self.chat_history: List[Dict[str, str]] = [{"role": "system", "content": persona}]

#     def add_user_message(self, content: str):
#         self.chat_history.append({"role": "user", "content": content})

#     def add_assistant_message(self, content: str):
#         self.chat_history.append({"role": "assistant", "content": content})

#     def generate_reply(self) -> str:
#         reply = self.backend.generate_response(self.chat_history)
#         self.add_assistant_message(reply)
#         return reply

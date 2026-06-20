import json
from typing import List, Optional, Dict, Any
from openai import OpenAI

class AIGenerator:
    """Handles interactions with DeepSeek's (OpenAI-compatible) API for generating responses"""

    # Static system prompt to avoid rebuilding on each call
    SYSTEM_PROMPT = """ You are an AI assistant specialized in course materials and educational content with access to a comprehensive search tool for course information.

Search Tool Usage:
- Use the search tool for questions about specific course content or detailed educational materials
- You may search **more than once** when a question needs it — e.g. comparing two courses, or refining after a first result. Keep each search focused and stop searching as soon as you can answer.
- Synthesize search results into accurate, fact-based responses
- If search yields no results, state this clearly without offering alternatives

Response Protocol:
- **General knowledge questions**: Answer using existing knowledge without searching
- **Course-specific questions**: Search first, then answer
- **No meta-commentary**:
 - Provide direct answers only — no reasoning process, search explanations, or question-type analysis
 - Do not mention "based on the search results"


All responses must be:
1. **Brief, Concise and focused** - Get to the point quickly
2. **Educational** - Maintain instructional value
3. **Clear** - Use accessible language
4. **Example-supported** - Include relevant examples when they aid understanding
Provide only the direct answer to what was asked.
"""

    def __init__(self, api_key: str, model: str, base_url: str = "https://api.deepseek.com",
                 max_tool_rounds: int = 5):
        # The OpenAI client raises if api_key is empty, which would crash server
        # startup. Use a placeholder so construction succeeds; the app-level guard
        # (and DeepSeek auth) reject actual calls made without a real key.
        self.client = OpenAI(api_key=api_key or "not-configured", base_url=base_url)
        self.model = model
        # Upper bound on sequential tool-call rounds before we force a final answer.
        self.max_tool_rounds = max_tool_rounds

        # Pre-build base API parameters
        self.base_params = {
            "model": self.model,
            "temperature": 0,
            "max_tokens": 800
        }

    @staticmethod
    def _to_openai_tools(tools: Optional[List[Dict[str, Any]]]) -> Optional[List[Dict[str, Any]]]:
        """
        Convert Anthropic-style tool definitions (name/description/input_schema)
        into OpenAI/DeepSeek function-calling format. This keeps search_tools.py
        unchanged while talking to the OpenAI-compatible DeepSeek API.
        """
        if not tools:
            return None
        converted = []
        for tool in tools:
            converted.append({
                "type": "function",
                "function": {
                    "name": tool["name"],
                    "description": tool.get("description", ""),
                    # Anthropic calls it "input_schema"; OpenAI calls it "parameters"
                    "parameters": tool.get("input_schema", {}),
                }
            })
        return converted

    def generate_response(self, query: str,
                         conversation_history: Optional[str] = None,
                         tools: Optional[List] = None,
                         tool_manager=None) -> str:
        """
        Generate AI response with optional tool usage and conversation context.

        Args:
            query: The user's question or request
            conversation_history: Previous messages for context
            tools: Available tools the AI can use (Anthropic-style definitions)
            tool_manager: Manager to execute tools

        Returns:
            Generated response as string
        """

        # Build system content efficiently - avoid string ops when possible
        system_content = (
            f"{self.SYSTEM_PROMPT}\n\nPrevious conversation:\n{conversation_history}"
            if conversation_history
            else self.SYSTEM_PROMPT
        )

        # OpenAI-compatible format: system prompt is the first message
        messages = [
            {"role": "system", "content": system_content},
            {"role": "user", "content": query},
        ]

        openai_tools = self._to_openai_tools(tools)

        # No tools available: a single completion call.
        if not (openai_tools and tool_manager):
            response = self.client.chat.completions.create(
                **self.base_params, messages=messages
            )
            return response.choices[0].message.content

        # Tool loop: let the model search and refine across multiple rounds
        # (e.g. comparing two courses) until it answers or we hit the cap.
        for _ in range(self.max_tool_rounds):
            response = self.client.chat.completions.create(
                **self.base_params,
                messages=messages,
                tools=openai_tools,
                tool_choice="auto",
            )
            message = response.choices[0].message
            if not message.tool_calls:
                return message.content
            # Record the assistant's tool-call message, then each tool's result.
            messages.append(message)
            self._execute_tool_calls(message, messages, tool_manager)

        # Rounds exhausted while the model still wants to search: force a final
        # answer with no tools so we always return synthesized text.
        final_response = self.client.chat.completions.create(
            **self.base_params, messages=messages
        )
        return final_response.choices[0].message.content

    def _execute_tool_calls(self, message, messages, tool_manager):
        """Run every tool call on `message` and append each result to `messages`."""
        for tool_call in message.tool_calls:
            # OpenAI/DeepSeek pass arguments as a JSON string.
            try:
                tool_args = json.loads(tool_call.function.arguments or "{}")
            except json.JSONDecodeError:
                tool_args = {}

            tool_result = tool_manager.execute_tool(
                tool_call.function.name,
                **tool_args
            )

            messages.append({
                "role": "tool",
                "tool_call_id": tool_call.id,
                "content": tool_result,
            })

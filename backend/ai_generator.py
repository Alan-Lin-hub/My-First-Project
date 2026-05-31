import json
from typing import List, Optional, Dict, Any
from openai import OpenAI

class AIGenerator:
    """Handles interactions with DeepSeek's (OpenAI-compatible) API for generating responses"""

    # Static system prompt to avoid rebuilding on each call
    SYSTEM_PROMPT = """ You are an AI assistant specialized in course materials and educational content with access to a comprehensive search tool for course information.

Search Tool Usage:
- Use the search tool **only** for questions about specific course content or detailed educational materials
- **One search per query maximum**
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

    def __init__(self, api_key: str, model: str, base_url: str = "https://api.deepseek.com"):
        # The OpenAI client raises if api_key is empty, which would crash server
        # startup. Use a placeholder so construction succeeds; the app-level guard
        # (and DeepSeek auth) reject actual calls made without a real key.
        self.client = OpenAI(api_key=api_key or "not-configured", base_url=base_url)
        self.model = model

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

        # Prepare API call parameters
        api_params = {
            **self.base_params,
            "messages": messages,
        }

        # Add tools if available
        openai_tools = self._to_openai_tools(tools)
        if openai_tools:
            api_params["tools"] = openai_tools
            api_params["tool_choice"] = "auto"

        # Get response from DeepSeek
        response = self.client.chat.completions.create(**api_params)
        message = response.choices[0].message

        # Handle tool execution if needed
        if message.tool_calls and tool_manager:
            return self._handle_tool_execution(message, api_params, tool_manager)

        # Return direct response
        return message.content

    def _handle_tool_execution(self, initial_message, base_params: Dict[str, Any], tool_manager):
        """
        Handle execution of tool calls and get follow-up response.

        Args:
            initial_message: The assistant message containing tool_calls
            base_params: Base API parameters (includes the original messages)
            tool_manager: Manager to execute tools

        Returns:
            Final response text after tool execution
        """
        # Start with existing messages
        messages = list(base_params["messages"])

        # Add the assistant's tool-call message verbatim so tool results can reference it
        messages.append(initial_message)

        # Execute all tool calls and append their results
        for tool_call in initial_message.tool_calls:
            # OpenAI/DeepSeek pass arguments as a JSON string
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

        # Prepare final API call without tools (synthesis step)
        final_params = {
            **self.base_params,
            "messages": messages,
        }

        # Get final response
        final_response = self.client.chat.completions.create(**final_params)
        return final_response.choices[0].message.content

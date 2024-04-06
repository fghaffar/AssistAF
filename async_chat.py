import asyncio

from agentforge.utils.function_utils import Functions
from agentforge.utils.functions.Logger import Logger
from agentforge.utils.storage_interface import StorageInterface

from customagents.ChooseAgent import ChooseAgent
from customagents.GenerateAgent import GenerateAgent
from customagents.ReflectAgent import ReflectAgent
from customagents.TheoryAgent import TheoryAgent
from customagents.ThoughtAgent import ThoughtAgent
from modules.discord_client import DiscordClient
from Utilities.Parsers import MessageParser
from Utilities.Memory import Memory
from Utilities.UI import UI


class Chatbot:
    parsed_data = None
    memories = None
    chat_response = None
    cat = None
    categories = None

    def __init__(self, client):
        self.ui = UI(client)
        self.memory = Memory()
        self.storage = StorageInterface().storage_utils
        self.parser = MessageParser
        self.chat_history = None
        self.choice_parsed = None
        self.formatted_messages: str = ''
        self.functions = Functions()
        self.memories = []
        self.logger = Logger('AsyncChat')
        self.processing_lock = asyncio.Lock()

        self.channel_messages = {}
        self.user_history = None
        self.result = None

        # Grouping agent-related instances into a dictionary
        self.agents = {
            "choose": ChooseAgent(),
            "reflection": ReflectAgent(),
            "theory": TheoryAgent(),
            "generate": GenerateAgent(),
            "thought": ThoughtAgent()
        }

        self.cognition = {
            "choose": dict,
            "reflection": dict,
            "theory": dict,
            "generate": str,
            "thought": dict
        }

        self.messages: dict = {}
        self.message = None

    async def run_batch(self, messages):
        self.logger.log(f"Running Batch Loop...", 'info', 'Trinity')
        async with self.processing_lock:
            self.messages = messages
            self.formatted_messages = self.parser.prepare_message_format(messages=self.messages)
            self.choose_message()
            await self.process_chosen_message()

    def choose_message(self):
        key_count = len(self.messages)
        if key_count > 1:
            self.result = self.agents["choose"].run(messages=self.formatted_messages)
            try:
                choice = self.parser.parse_lines(self.result)
                self.choice_parsed = int(choice["message_id"])
            except Exception as e:
                self.logger.log(f"Choice Agent - Parse error: {e}\nResponse:{self.result}", 'info', 'Trinity')
                self.choice_parsed = 0  # Default to first message if error occurs
        else:
            self.choice_parsed = 0

        self.message = self.messages[self.choice_parsed]
        self.logger.log(f"Choice Agent Selection: {self.message['message']}", 'info', 'Trinity')

    async def process_chosen_message(self):
        self.ui.channel_id_layer_0 = self.message["channel_id"]

        history, user_history = await self.chat_manager()

        # Run thought agent
        await self.interact_with_agent('thought', self.message['message'], history, user_history)

        # Run theory agent
        await self.interact_with_agent('theory', self.message['message'], history, user_history)

        # Run generate agent
        await self.interact_with_agent('generate', self.message['message'], history, user_history)

        # Run reflection agent
        await self.interact_with_agent('reflection', self.message['message'], history, user_history)

        await self.handle_reflect_agent_decision()

        self.memories = []

    async def interact_with_agent(self, agent_key, message, history, user_history, additional_params=None):
        self.logger.log(f"Running {agent_key.capitalize()} Agent... Message:{message}", 'info', 'Trinity')

        def get_value_or_none(value):
            # If the value is a non-empty string, return it as is
            if isinstance(value, str) and value.strip():
                return value
            # Check for other non-empty values (including False as a meaningful boolean value)
            elif value or value is False:
                return value
            # Return None for empty strings, None values, empty lists, and empty dicts
            return None

        agent_params = {
            "user_message": get_value_or_none(message),
            "history": get_value_or_none(history),
            "user_history": get_value_or_none(user_history),
            "username": get_value_or_none(self.message.get("author")),
            "new_messages": get_value_or_none(self.formatted_messages),
            "memories": get_value_or_none(self.memories),
            # Safeguarded access to nested dict values with get_value_or_none for each nested property
            "emotion": get_value_or_none(self.cognition["thought"].get("Emotion")) if isinstance(
                self.cognition.get("thought"), dict) else None,
            "reason": get_value_or_none(self.cognition["thought"].get("Reason")) if isinstance(
                self.cognition.get("thought"), dict) else None,
            "thought": get_value_or_none(self.cognition["thought"].get("Inner Thought")) if isinstance(
                self.cognition.get("thought"), dict) else None,
            "what": get_value_or_none(self.cognition["theory"].get("What")) if isinstance(self.cognition.get("theory"),
                                                                                          dict) else None,
            "why": get_value_or_none(self.cognition["theory"].get("Why")) if isinstance(self.cognition.get("theory"),
                                                                                        dict) else None,
            "response": get_value_or_none(self.result),
        }

        if additional_params:
            agent_params.update(additional_params)

        self.logger.log(f"{agent_key.capitalize()} Agent Parameters:{agent_params}", 'debug', 'Trinity')

        self.result = self.agents[agent_key].run(**agent_params)
        if agent_key == 'thought':
            self.categories = self.parser.parse_lines(self.result)["Categories"].split(",")

        response_log = f"{agent_key.capitalize()} Agent:\n```{self.result}```\n"
        self.logger.log(response_log, 'info', 'Trinity')
        await self.ui.send_message(1, response_log)

        try:
            if agent_key == 'generate':
                self.cognition[agent_key] = self.result
                return

            self.cognition[agent_key] = self.parser.parse_lines(self.result)
        except Exception as e:
            self.logger.parsing_error(self.result, e)
            # return None

    async def handle_reflect_agent_decision(self):
        cognition = self.cognition['reflection']
        response = self.cognition['generate']
        self.logger.log(f"Handle Reflection:{cognition}", 'debug', 'Trinity')
        if self.cognition['reflection'] and "Choice" in self.cognition['reflection']:
            if cognition["Choice"] == "respond":
                # Log the decision to respond and send the generated response
                response_log = f"Generated Response:\n{response}\n"
                self.logger.log(response_log, 'debug', 'Trinity')
                await self.ui.send_message(0, response)
                # Save the response for memory
                self.save_memory(response)
            elif cognition["Choice"] == "nothing":
                # Log the decision to not respond and the reason
                self.logger.log(f"Reason for not responding:\n{cognition['Reason']}\n", 'info', 'Trinity')
                await self.ui.send_message(0, f"...\n")
                # Save the reason for not responding for memory
                self.save_memory(cognition["Reason"])
            else:
                # Handle other cases, such as possibly generating a new response based on feedback
                new_response_params = {
                    "memories": self.memories,
                    "emotion": cognition.get("Emotion", ""),
                    "reason": cognition.get("Reason", ""),
                    "thought": cognition.get("InnerThought", ""),
                    "what": cognition.get("What", ""),
                    "why": cognition.get("Why", ""),
                    "feedback": cognition.get("Reason", ""),  # Assuming feedback is based on the reason
                }
                new_response = self.agents["generate"].run(
                    user_message=self.message['message'],
                    history=cognition.get("history", ""),  # Assuming we need to pass some history
                    user_history=cognition.get("user_history", ""),  # And user history
                    response=response,
                    new_messages=self.formatted_messages,
                    **new_response_params
                )
                self.logger.log(f"Sending New Response: {new_response}", 'info', 'Trinity')
                await self.ui.send_message(0, f"{new_response}")
                self.save_memories(new_response)

    def save_memories(self, bot_response):
        self.memory.set_memory_info(self.messages, self.choice_parsed, self.cognition, bot_response)
        self.memory.save_all_memory()

    async def chat_manager(self):
        chat_log = self.memory.fetch_history(self.message['channel'])
        user_log = self.memory.fetch_history(self.message['author'],
                                             query=self.message['message'],
                                             is_user_specific=True)

        self.logger.log(f"User Message: {self.message['message']}\n", 'Info', 'Trinity')
        return chat_log, user_log

    async def process_channel_messages(self):
        self.logger.log(f"Process Channel Messages Running...", 'debug', 'Trinity')
        while True:
            self.logger.log(f"Process Channel Messages - New Loop!", 'debug', 'Trinity')
            if self.channel_messages:
                for channel_layer_id in sorted(self.channel_messages.keys()):
                    messages = self.channel_messages.pop(channel_layer_id, None)
                    self.logger.log(f"Messages in Channel {channel_layer_id}: {messages}", 'debug', 'Trinity')
                    if messages:
                        # await self.run_batch(**channel_data)
                        await self.run_batch(messages)
                        self.logger.log(f"Run Batch Should Run Here, if i had any", 'debug', 'Trinity')
            else:
                self.logger.log(f"No Messages - Sleep Cycle", 'debug', 'Trinity')
                await asyncio.sleep(5)


async def on_message(content, author_name, channel, formatted_mentions, channel_id, timestamp):
    message_data = {
        "channel": channel,
        "channel_id": channel_id,
        "message": content,
        "author": author_name,
        "formatted_mentions": formatted_mentions,
        "timestamp": timestamp
    }
    bot.logger.log(f"Async on_message: {message_data}", 'debug', 'Trinity')
    if channel_id not in bot.channel_messages:
        bot.channel_messages[channel_id] = []

    bot.channel_messages[channel_id].append(message_data)
    bot.logger.log(f"Async on_message: done!", 'debug', 'Trinity')


if __name__ == '__main__':
    print("Starting")
    discord_client = DiscordClient([], on_message_callback=on_message)
    bot = Chatbot(discord_client)
    discord_client.bot = bot  # Set the Chatbot instance reference
    bot.ui = UI(discord_client)

    # Now, when DiscordClient's on_ready triggers, it will start process_channel_messages
    discord_client.client.run(discord_client.token)

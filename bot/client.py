import asyncio
import ctypes
import logging
import re
from datetime import datetime
from typing import Optional, Tuple

import discord
from discord.ext.tasks import loop

from bot import constants, parsers, timings
from bot.constants import PlayOptions

logger = logging.getLogger(__file__)
logger.setLevel(constants.LOGGING_LEVEL)


class UnbelievaClient(discord.Client):
    def __init__(self, bot_id: int, channel_id: int, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.last_message = -1

        self.bot_id, self.channel_id = bot_id, channel_id

        self.channel: Optional[discord.TextChannel] = None
        self.bot: Optional[discord.User] = None
        self.tasks = {
            '$work': timings.Cooldown(5 * 60 + 2),
            '$slut': timings.Cooldown(13 * 60 + 2),
            '$crime': timings.Cooldown(20 * 60 + 2),
            '$dep all': timings.Cooldown(30 * 60)
        }
        self.command_cooldown = timings.Cooldown(5)

        self.money = 0
        self.last_deposit = -1
        self.last_user_deposit = -1

        self.current_blackjack: Optional[discord.Message] = None

    async def on_ready(self):
        await self.wait_until_ready()

        self.channel: discord.TextChannel = self.get_channel(self.channel_id)
        self.bot = self.bot_id
        self.check_task_available.start()
        ctypes.windll.kernel32.SetConsoleTitleW(f"#{self.channel.name}/{self.channel.guild.name}")
        logger.info(f'Connected to #{self.channel.name} in {self.channel.guild.name}')

    async def on_message(self, message: discord.Message):
        # Ignore messages in other channels or sent by myself
        if message.channel != self.channel or message.author == self.user:
            return

        if message.author.id == self.bot and len(message.embeds) > 0:
            embed = message.embeds[0]
            is_self = embed.author.name == f'{self.user.name}#{self.user.discriminator}'

            if is_self:
                if parsers.TaskCooldownMessage.check_valid(message):
                    tcm = parsers.TaskCooldownMessage(message)

                    logger.debug(f'"{tcm.duration_unparsed}" => {tcm.duration}s')
                    logger.debug(f'Changed {tcm.task_type} to wait {tcm.duration + 2}s instead.')
                    self.tasks[tcm.task_type].change_expiration(tcm.available_at)

            # Handling earnings
            if parsers.TaskResponse.check_valid(message):
                tr = parsers.TaskResponse(message)
                self.money += tr.change
                logger.log(logging.INFO if is_self else logging.DEBUG, tr.log_message(embed.author.name))

            # Handling for blackjack
            if embed.description.startswith('Type `hit` to draw another card'):
                options = self.parse_options(embed.description)
                my_cards = self.parse_cards(embed.fields[0])
                dealer_cards = self.parse_cards(embed.fields[1])
                print(options, my_cards, dealer_cards)

    def parse_options(self, options_str: str) -> PlayOptions:
        """
        Return a tuple of booleans describing what the player can do.
        Tuple Options: [hit, stand, double_down, split]
        """
        options = [f'`{sub}`' in options_str for sub in ['hit', 'stand', 'double down', 'split']]
        # noinspection PyProtectedMember
        return PlayOptions._make(options)

    def parse_cards(self, card_str: discord.embeds.EmbedProxy) -> Tuple[str, Optional[str], Tuple[int, bool]]:
        """
        Parses a Embed Proxy

        :param card_str:
        :return: [Card1, Card2?, [Value, isSoft]]
        """
        emote_pattern = r'<:([A-z0-9]+):\d+>'
        value_pattern = r'Value: (Soft )?(\d+)'
        cards = list(re.finditer(emote_pattern, card_str.value))
        value = re.search(value_pattern, card_str.value)

        c2: Optional[str]
        c1, c2 = cards[0].group(1), cards[1].group(1)
        c2 = c2 if c2 != 'cardBack' else None

        return c1, c2, (int(value.group(2)), value.groups()[1] is None)

    def handle_blackjack(self):
        embed = self.current_blackjack.embeds[0]
        options = self.parse_options(embed.description)
        my_cards = self.parse_cards(embed.fields[0])
        dealer_cards = self.parse_cards(embed.fields[1])
        print(options, my_cards, dealer_cards)
        pass

    @loop(seconds=1)
    async def check_task_available(self):
        """
        Loop to run tasks as soon as they are available.
        """
        await self.wait_until_ready()

        for task, task_cooldown in self.tasks.items():
            # Task is ready to be ran again
            if task_cooldown.ready:
                # Ensure the cooldown between commands has ran.
                await self.command_cooldown.sleep()

                # Ready to execute the task.
                logger.debug(f'Executing {task} task.')
                await self.channel.send(task)

                # Activate the cooldowns
                task_cooldown.hit()
                self.command_cooldown.hit()

    async def command_sleep(self):
        """Sleep right before sending a command."""
        now = datetime.utcnow().timestamp()
        time_between = now - self.last_message
        wait_time = 6 - time_between

        if wait_time > 0:
            logger.debug(f'Sleeping for {round(wait_time, 2)}s before sending a command...')
            await asyncio.sleep(wait_time)

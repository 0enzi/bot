import asyncio
from typing import Dict, Optional

import discord
import discord.ext.commands

import bot.client
import bot.commands
import bot.locations
import bot.privileges
import bot.reactions
import util.discord

class AbortDueToUnpin(Exception):
    pass

class AbortDueToOtherPin(Exception):
    pass

unpin_requests: Dict[int, bot.reactions.ReactionMonitor[discord.RawReactionActionEvent]] = {}

@bot.commands.cleanup
@bot.commands.command("pin")
@bot.privileges.priv("pin")
@bot.locations.location("pin")
async def pin_command(ctx: bot.commands.Context, message: Optional[util.discord.ReplyConverter]) -> None:
    """Pin a message."""
    to_pin = util.discord.partial_from_reply(message, ctx)
    if ctx.guild is None:
        raise util.discord.UserError("Can only be used in a guild")
    guild = ctx.guild

    pin_msg_task = asyncio.create_task(
        bot.client.client.wait_for("message",
            check=lambda m: m.guild is not None and m.guild.id == guild.id
            and m.channel.id == ctx.channel.id
            and m.type == discord.MessageType.pins_add
            and m.reference is not None and m.reference.message_id == to_pin.id))
    try:
        while True:
            try:
                await to_pin.pin(reason=util.discord.format("Requested by {!m}", ctx.author))
                break
            except (discord.Forbidden, discord.NotFound):
                pin_msg_task.cancel()
                break
            except discord.HTTPException as exc:
                if exc.text == "Cannot execute action on a system message" or exc.text == "Unknown Message":
                    pin_msg_task.cancel()
                    break
                elif not exc.text.startswith("Maximum number of pins reached"):
                    raise
                pins = await ctx.channel.pins()

                oldest_pin = pins[-1]

                async with util.discord.TempMessage(ctx,
                    "No space in pins. Unpin or press \u267B to remove oldest") as confirm_msg:
                    await confirm_msg.add_reaction("\u267B")
                    await confirm_msg.add_reaction("\u274C")

                    with bot.reactions.ReactionMonitor(guild_id=guild.id, channel_id=ctx.channel.id,
                        message_id=confirm_msg.id, author_id=ctx.author.id, event="add",
                        filter=lambda _, p: p.emoji.name in ["\u267B","\u274C"], timeout_each=60) as mon:
                        try:
                            if ctx.author.id in unpin_requests:
                                unpin_requests[ctx.author.id].cancel(AbortDueToOtherPin())
                            unpin_requests[ctx.author.id] = mon
                            _, p = await mon
                            if p.emoji.name == "\u267B":
                                await oldest_pin.unpin(reason=util.discord.format("Requested by {!m}", ctx.author))
                            else:
                                break
                        except AbortDueToUnpin:
                            del unpin_requests[ctx.author.id]
                        except (asyncio.TimeoutError, AbortDueToOtherPin):
                            pin_msg_task.cancel()
                            break
                        else:
                            del unpin_requests[ctx.author.id]
    finally:
        try:
            pin_msg = await asyncio.wait_for(pin_msg_task, timeout=60)
            bot.commands.add_cleanup(ctx, pin_msg)
        except asyncio.TimeoutError:
            pin_msg_task.cancel()

@bot.commands.cleanup
@bot.commands.command("unpin")
@bot.privileges.priv("pin")
@bot.locations.location("pin")
async def unpin_command(ctx: bot.commands.Context, message: Optional[util.discord.ReplyConverter]) -> None:
    """Unpin a message."""
    to_unpin = util.discord.partial_from_reply(message, ctx)
    if ctx.guild is None:
        raise util.discord.UserError("Can only be used in a guild")

    try:
        await to_unpin.unpin(reason=util.discord.format("Requested by {!m}", ctx.author))
        if ctx.author.id in unpin_requests:
            unpin_requests[ctx.author.id].cancel(AbortDueToUnpin())

        await ctx.send("\u2705")
    except (discord.Forbidden, discord.NotFound):
        pass
    except discord.HTTPException as exc:
        if exc.text == "Cannot execute action on a system message":
            pass
        elif exc.text == "Unknown Message":
            pass
        else:
            raise

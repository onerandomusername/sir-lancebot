import asyncio
import random
from typing import Callable, Optional, Union

import discord
from discord.ext.commands import Cog, Context, check, group, guild_only

from bot.bot import Bot
from bot.constants import Emojis
from bot.utils.pagination import LinePaginator

CONFIRMATION_MESSAGE = (
    "{opponent}, {requester} wants to play Tic-Tac-Toe against you."
    f"\nReact to this message with {Emojis.confirmation} to accept or with {Emojis.decline} to decline."
)
TIMEOUT = 60.0
INTERACTION_ID_PREFIX = "tic-tac-toe-action-"


def check_win(board: dict[int, str]) -> tuple[bool, Optional[tuple[int, int, int]]]:
    """Check from board, is any player won game."""
    winning_combinations: list[tuple[int, int, int]] = [
        # Horizontal
        (1, 2, 3), (4, 5, 6), (7, 8, 9),
        # Vertical
        (1, 4, 7), (2, 5, 8), (3, 6, 9),
        # Diagonal
        (1, 5, 9), (3, 5, 7)
    ]
    for a, b, c in winning_combinations:
        if (board[a] == board[b] == board[c]) and board[a] in (Emojis.x_square, Emojis.o_square):
            return True, (a, b, c)
    return False, None


class Player:
    """Class that contains information about player and functions that interact with player."""

    def __init__(self, user: discord.User, ctx: Context, symbol: str):
        self.user = user
        self.ctx = ctx
        self.symbol = symbol

    async def get_move(
        self, board: dict[int, str], msg: discord.Message
    ) -> tuple[bool, Optional[int], Optional[discord.Interaction]]:
        """
        Get move from user.

        Return is timeout reached and position of field what user will fill when timeout don't reach.
        """
        def check_for_move(inter: discord.Interaction) -> bool:
            """Check does user who reacted is user who we want, message is board and emoji is in board values."""
            return not any(
                [
                    inter.type != discord.InteractionType.component,
                    not inter.data['custom_id'].startswith(INTERACTION_ID_PREFIX),
                    # inter.user.id != self.user.id,
                    inter.message.id != msg.id
                ]
            )
        while True:
            try:
                inter: discord.Interaction = await self.ctx.bot.wait_for(
                    "interaction",
                    timeout=TIMEOUT,
                    check=check_for_move,
                )
            except asyncio.TimeoutError:
                return True, None, None
            else:
                # its possible to get an interaction by the other person, in which case we should say its not your turn!
                if inter.user.id != self.user.id:
                    await inter.response.send_message(
                        "Its not your turn yet, or you aren't playing this game!",
                        ephemeral=True,
                    )
                    continue
                return False, int(inter.data["custom_id"][len(INTERACTION_ID_PREFIX):]), inter

    def __str__(self) -> str:
        """Return mention of user."""
        return self.user.mention


class AI:
    """Tic Tac Toe AI class for against computer gaming."""

    def __init__(self, bot_user: discord.Member, symbol: str):
        self.user = bot_user
        self.symbol = symbol

    @staticmethod
    async def get_move(board: dict[int, str], msg: discord.Message) -> tuple[bool, int, None]:
        """Get move from AI. AI use Minimax strategy."""
        possible_moves = [i for i, emoji in board.items() if emoji not in (Emojis.o_square, Emojis.x_square)]

        # give the ai some artifical delay
        await msg.channel.trigger_typing()
        await asyncio.sleep(random.random() * 1.5)

        for symbol in (Emojis.o_square, Emojis.x_square):
            for move in possible_moves:
                board_copy = board.copy()
                board_copy[move] = symbol
                if check_win(board_copy)[0]:
                    return False, move, None

        open_corners = [i for i in possible_moves if i in (1, 3, 7, 9)]
        if len(open_corners) > 0:
            return False, random.choice(open_corners), None

        if 5 in possible_moves:
            return False, 5, None

        open_edges = [i for i in possible_moves if i in (2, 4, 6, 8)]
        return False, random.choice(open_edges), None

    def __str__(self) -> str:
        """Return mention of @Sir Lancebot."""
        return self.user.mention


class Game(discord.ui.View):
    """Class that contains information and functions about Tic Tac Toe game."""

    def __init__(self, players: list[Union[Player, AI]], ctx: Context):
        self.players = players
        self.ctx = ctx
        self.channel = ctx.channel
        self.board = dict.fromkeys(range(1, 10), Emojis.empty_placeholder)

        # add the buttons
        # hack to not use the callbacks
        super().__init__(timeout=1)

        for k, v in self.board.items():
            self.add_item(
                discord.ui.Button(
                    style=discord.ButtonStyle.grey,
                    emoji=v,
                    row=(k-1)//3,
                    custom_id=INTERACTION_ID_PREFIX + str(k),
                )
            )

        self.current = self.players[0]
        self.next = self.players[1]

        self.winner: Optional[Union[Player, AI]] = None
        self.loser: Optional[Union[Player, AI]] = None
        self.over = False
        self.canceled = False
        self.draw = False

    async def get_confirmation(self) -> tuple[bool, Optional[str]]:
        """
        Ask does user want to play TicTacToe against requester. First player is always requester.

        This return tuple that have:
        - first element boolean (is game accepted?)
        - (optional, only when first element is False, otherwise None) reason for declining.
        """
        confirm_message = await self.ctx.send(
            CONFIRMATION_MESSAGE.format(
                opponent=self.players[1].user.mention,
                requester=self.players[0].user.mention
            )
        )
        await confirm_message.add_reaction(Emojis.confirmation)
        await confirm_message.add_reaction(Emojis.decline)

        def confirm_check(reaction: discord.Reaction, user: discord.User) -> bool:
            """Check is user who reacted from who this was requested, message is confirmation and emoji is valid."""
            return (
                reaction.emoji in (Emojis.confirmation, Emojis.decline)
                and reaction.message.id == confirm_message.id
                and user == self.players[1].user
            )

        try:
            reaction, user = await self.ctx.bot.wait_for(
                "reaction_add",
                timeout=60.0,
                check=confirm_check
            )
        except asyncio.TimeoutError:
            self.over = True
            self.canceled = True
            await confirm_message.delete()
            return False, "Running out of time... Cancelled game."

        await confirm_message.delete()
        if reaction.emoji == Emojis.confirmation:
            return True, None
        else:
            self.over = True
            self.canceled = True
            return False, "User declined"

    def disable(self) -> None:
        """Disable all components in this view."""
        for item in self.children:
            if hasattr(item, "disabled"):
                item.disabled = True

    def format_board(self) -> str:
        """Get formatted tic-tac-toe board for message."""
        board = list(self.board.values())
        return "\n".join(
            (f"{board[line]} {board[line + 1]} {board[line + 2]}" for line in range(0, len(board), 3))
        )

    async def play(self) -> None:
        """Start and handle game."""
        await self.ctx.send("It's time for the game! Let's begin.")
        board: discord.Message = await self.ctx.send(
            "**Tic Tac Toe**",
            view=self,
        )
        inter = None
        for _ in range(len(self.board)):
            if isinstance(self.current, Player):
                announce = await self.ctx.send(
                    f"{self.current.user.mention}, it's your turn! "
                    "Click a button to take your go."
                )
            # loop the last inter
            if inter and not inter.response.is_done():
                await inter.response.defer()
            # inter is only an interaction if it was a user who didn't timeout
            timeout, pos, inter = await self.current.get_move(self.board, board)
            if isinstance(self.current, Player):
                await announce.delete()
            if timeout:
                await self.ctx.send(f"{self.current.user.mention} ran out of time. Canceling game.")
                self.over = True
                self.canceled = True
                self.disable()
                await board.edit(view=self)
                return
            self.board[pos] = self.current.symbol
            button: discord.ui.Button = self.children[pos-1]
            button.disabled = True
            button.style = discord.ButtonStyle.blurple
            button.emoji = self.current.symbol
            self.children[pos-1] = button
            if (win := check_win(self.board))[0]:
                for i, button in enumerate(self.children):
                    button.disabled = True
                    if i+1 in win[1]:
                        button.style = discord.ButtonStyle.green
                    elif button.emoji != discord.PartialEmoji.from_str(Emojis.empty_placeholder):
                        button.style = discord.ButtonStyle.blurple
                if inter:
                    await inter.response.edit_message(view=self)
                else:
                    await board.edit(view=self)
                self.winner = self.current
                self.loser = self.next
                await self.ctx.send(
                    f":tada: {self.current} won this game! :tada:"
                )
                break
            if inter:
                if isinstance(self.next, AI):
                    # this is in order to be able to continue showing the processing animation by discord
                    # to make it look like the ai is thinking.
                    await board.edit(view=self)
                else:
                    await inter.response.edit_message(view=self)
            else:
                await board.edit(view=self)
            self.current, self.next = self.next, self.current
        if not self.winner:
            self.draw = True
            if inter:
                await inter.response.edit_message(view=self)
            else:
                await board.edit(view=self)
            await self.ctx.send("It's a DRAW!")
        self.over = True


def is_channel_free() -> Callable:
    """Check is channel where command will be invoked free."""
    async def predicate(ctx: Context) -> bool:
        return all(game.channel != ctx.channel for game in ctx.cog.games if not game.over)
    return check(predicate)


def is_requester_free() -> Callable:
    """Check is requester not already in any game."""
    async def predicate(ctx: Context) -> bool:
        return all(
            ctx.author not in (player.user for player in game.players) for game in ctx.cog.games if not game.over
        )
    return check(predicate)


class TicTacToe(Cog):
    """TicTacToe cog contains tic-tac-toe game commands."""

    def __init__(self):
        self.games: list[Game] = []

    @guild_only()
    @is_channel_free()
    @is_requester_free()
    @group(name="tictactoe", aliases=("ttt", "tic"), invoke_without_command=True)
    async def tic_tac_toe(self, ctx: Context, opponent: Optional[discord.User]) -> None:
        """Tic Tac Toe game. Play against friends or AI. Use buttons to add your mark to field."""
        if opponent == ctx.author:
            await ctx.send("You can't play against yourself.")
            return
        if opponent is not None and not all(
            opponent not in (player.user for player in g.players) for g in ctx.cog.games if not g.over
        ):
            await ctx.send("Opponent is already in game.")
            return
        if opponent is None:
            game = Game(
                [Player(ctx.author, ctx, Emojis.x_square), AI(ctx.me, Emojis.o_square)],
                ctx
            )
        else:
            game = Game(
                [Player(ctx.author, ctx, Emojis.x_square), Player(opponent, ctx, Emojis.o_square)],
                ctx
            )
        self.games.append(game)
        if opponent is not None:
            if opponent.bot:  # check whether the opponent is a bot or not
                await ctx.send("You can't play Tic-Tac-Toe with bots!")
                return

            confirmed, msg = await game.get_confirmation()

            if not confirmed:
                if msg:
                    await ctx.send(msg)
                return
        await game.play()

    @tic_tac_toe.group(name="history", aliases=("log",), invoke_without_command=True)
    async def tic_tac_toe_logs(self, ctx: Context) -> None:
        """Show most recent tic-tac-toe games."""
        if len(self.games) < 1:
            await ctx.send("No recent games.")
            return
        log_games = []
        for i, game in enumerate(self.games):
            if game.over and not game.canceled:
                if game.draw:
                    log_games.append(
                        f"**#{i+1}**: {game.players[0]} vs {game.players[1]} (draw)"
                    )
                else:
                    log_games.append(
                        f"**#{i+1}**: {game.winner} :trophy: vs {game.loser}"
                    )
        await LinePaginator.paginate(
            log_games,
            ctx,
            discord.Embed(title="Most recent Tic Tac Toe games")
        )

    @tic_tac_toe_logs.command(name="show", aliases=("s",))
    async def show_tic_tac_toe_board(self, ctx: Context, game_id: int) -> None:
        """View game board by ID (ID is possible to get by `.tictactoe history`)."""
        if len(self.games) < game_id:
            await ctx.send("Game don't exist.")
            return
        game = self.games[game_id - 1]

        if game.draw:
            description = f"{game.players[0]} vs {game.players[1]} (draw)\n\n{game.format_board()}"
        else:
            description = f"{game.winner} :trophy: vs {game.loser}\n\n{game.format_board()}"

        embed = discord.Embed(
            title=f"Match #{game_id} Game Board",
            description=description,
        )
        await ctx.send(embed=embed)


def setup(bot: Bot) -> None:
    """Load the TicTacToe cog."""
    bot.add_cog(TicTacToe())
